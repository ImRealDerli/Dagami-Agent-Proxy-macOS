
from __future__ import annotations
from pathlib import Path
import json
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import webbrowser
from .adapters import list_adapters
from .core.profile import ProxyProfile
from .core.recovery import StateManager
from .core.secrets import SecretStore
from .core.validator import ProxyValidator
from .portable_runtime import launch_desktop_app, request, load_profile, runtime_dir, redact, executable, register_executable
from .portable_shortcuts import PortableShortcuts

class Desktop(tk.Tk):
    def __init__(self, tray=True, autostart=False, first_run=False):
        super().__init__();self.title('Dagami Agent Proxy 0.4.0 mac.6 — прокси и DNS-профили');self.geometry('1000x680');self.minsize(900,600)
        self.app_icon=tk.PhotoImage(file=str(Path(__file__).parent/'assets'/'icon-64.png'));self.iconphoto(True,self.app_icon)
        style=ttk.Style(self);style.theme_use('clam')
        for name,color,active in [('Accent','#087fc1','#06659a'),('Danger','#c62626','#a61d1d')]:
            style.configure(name+'.TButton',background=color,foreground='white',padding=(10,7))
            style.map(name+'.TButton',background=[('disabled','#8b969e'),('active',active)],foreground=[('disabled','#eeeeee')])
        self.tray_events=queue.Queue();self.tray=None;self.dns_dialog=None
        self.events=queue.Queue();self.busy=False;self.profile=tk.StringVar(value='default');self.current_profile='default';self.notice=tk.StringVar(value='Выберите профиль и приложение. Закрытие окна оставляет фоновые сессии активными.')
        self.shortcuts=PortableShortcuts();self.adapters={a.app_id:a for a in list_adapters() if sys.platform in a.supported_os}
        root=ttk.Frame(self,padding=14);root.pack(fill='both',expand=True);root.columnconfigure(0,weight=1);root.rowconfigure(2,weight=1)
        header=ttk.Frame(root);header.grid(row=0,column=0,sticky='ew',pady=(0,10))
        branding=ttk.Frame(header);branding.pack(fill='x');self.brand_icon=self.app_icon.subsample(2,2)
        ttk.Label(branding,image=self.brand_icon).pack(side='left',padx=(0,8));ttk.Label(branding,text='Dagami Agent Proxy',font=('TkDefaultFont',17,'bold')).pack(side='left')
        top=ttk.Frame(header);top.pack(fill='x',pady=(10,0))
        ttk.Label(top,text='Профиль:').pack(side='left',padx=(0,6));self.profiles=ttk.Combobox(top,textvariable=self.profile,state='readonly',width=24);self.profiles.pack(side='left');self.profiles.bind('<<ComboboxSelected>>',lambda _:self.select_profile())
        add=ttk.Menubutton(top,text='Добавить профиль');add.pack(side='left',padx=6)
        choices=tk.Menu(add,tearoff=False);add.configure(menu=choices)
        choices.add_command(label='Прокси из ссылки',command=self.add_profile)
        choices.add_command(label='Smart DNS без прокси',command=self.add_dns_profile)
        ttk.Button(top,text='Маршрут / Smart DNS',command=self.route_settings).pack(side='left',padx=6)
        ttk.Button(top,text='Проверить',command=lambda:self.work(self.check_proxy)).pack(side='right')
        flags=ttk.Frame(header);flags.pack(fill='x',pady=(8,0))
        self.proxy_on=tk.BooleanVar();self.smart_on=tk.BooleanVar()
        ttk.Checkbutton(flags,text='Использовать прокси',variable=self.proxy_on,command=self.toggle_route).pack(side='left')
        ttk.Checkbutton(flags,text='Использовать Smart DNS',variable=self.smart_on,command=self.toggle_route).pack(side='left',padx=15)
        ttk.Button(flags,text='Изменить профиль',command=self.edit_credentials).pack(side='left',padx=6)
        tools=ttk.Frame(root);tools.grid(row=1,column=0,sticky='ew',pady=(0,6));ttk.Button(tools,text='Найти приложения',command=self.refresh).pack(side='left')
        ttk.Button(tools,text='Добавить',command=self.add_app).pack(side='left',padx=6)
        ttk.Button(tools,text='Указать путь',command=self.set_executable).pack(side='left',padx=6)
        if sys.platform != 'win32':
            ttk.Button(tools,text='DNS в системе',command=self.open_dns,style='Accent.TButton').pack(side='left',padx=6)
            from .portable_startup import Startup
            self.startup=Startup();self.login_start=tk.BooleanVar()
            try:self.login_start.set(self.startup.enabled())
            except Exception as exc:self.notice.set(str(exc))
            ttk.Checkbutton(tools,text='При входе в систему',variable=self.login_start,command=self.change_startup).pack(side='left',padx=6)
        ttk.Button(tools,text='Журнал',command=self.show_log).pack(side='right')
        box=ttk.Frame(root);box.grid(row=2,column=0,sticky='nsew');box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
        self.apps=ttk.Treeview(box,columns=('state','path'),show='tree headings',selectmode='browse');self.apps.heading('#0',text='Приложение');self.apps.heading('state',text='Наличие');self.apps.heading('path',text='Расположение');self.apps.column('#0',width=190,stretch=False);self.apps.column('state',width=110,stretch=False);self.apps.column('path',width=440)
        self.apps.grid(row=0,column=0,sticky='nsew');bar=ttk.Scrollbar(box,command=self.apps.yview);bar.grid(row=0,column=1,sticky='ns');self.apps.configure(yscrollcommand=bar.set)
        self.apps.bind('<<TreeviewSelect>>',lambda _:self.update_state())
        actions=ttk.Frame(root,padding=(0,10,0,0));actions.grid(row=3,column=0,sticky='ew')
        self.launch=ttk.Button(actions,text='Запустить',command=lambda:self.act(lambda app:launch_desktop_app(app,self.current_profile)),style='Accent.TButton');self.launch.pack(side='left')
        ttk.Button(actions,text='Создать запуск через Dagami',command=lambda:self.act(lambda app:self.shortcuts.enable(app,self.current_profile)),style='Accent.TButton').pack(side='left',padx=6)
        ttk.Button(actions,text='Отменить подготовку',command=lambda:self.act(self.restore_preparation)).pack(side='left',padx=6)
        menu=ttk.Menubutton(actions,text='Ещё');menu.pack(side='left');more=tk.Menu(menu,tearoff=False);menu.configure(menu=more)
        more.add_command(label='Восстановить ярлыки',command=lambda:self.act(self.shortcuts.restore));more.add_command(label='Остановить сессию',command=self.stop_session);more.add_command(label='Вход Google через прокси',command=self.login)
        more.add_command(label='Подготовить backend Antigravity',command=lambda:self.act(self.prepare_backend))
        more.add_command(label='Откатить backend Antigravity',command=lambda:self.act(self.restore_backend))
        more.add_command(label='Удалить добавленное приложение',command=self.remove_app)
        more.add_command(label='Релизы и обновления',command=lambda:webbrowser.open('https://github.com/j46871417-ui/Dagami-Agent-Proxy/releases'))
        more.add_command(label='Сообщить об ошибке',command=lambda:webbrowser.open('https://dns.dagami.ru/support/agent-proxy/'))
        more.add_separator();more.add_command(label='Выход из Dagami Agent Proxy',command=self.exit_app)
        self.session_state=ttk.Label(root,text='');self.session_state.grid(row=4,column=0,sticky='w',pady=(6,0))
        ttk.Label(root,textvariable=self.notice,wraplength=860).grid(row=5,column=0,sticky='ew',pady=8)
        links=ttk.Frame(root);links.grid(row=6,column=0,sticky='ew')
        for text,url in [('Поддержать','https://pay.cloudtips.ru/p/671fda86'),('t.me/dagamvi','https://t.me/dagamvi'),('@bright26bot','https://t.me/bright26bot')]:
            ttk.Button(links,text=text,command=lambda u=url:webbrowser.open(u)).pack(side='left',padx=(0,6))
        ttk.Label(links,text='Получить прокси · кодовое слово DAGAMI').pack(side='left',padx=8)
        self.refresh();self.after(100,self.pump);self.protocol('WM_DELETE_WINDOW',self.close)
        if tray:
            from .portable_tray import Tray
            self.tray=Tray(self.tray_events)
        if autostart:self.after(1500,self.hide_after_login)
        elif first_run and not StateManager.list_profiles():self.after(500,self.first_setup)

    def first_setup(self):
        if messagebox.askyesno('Первый запуск','Настроить upstream-прокси?\n\nВыберите «Нет», чтобы создать прямой маршрут macOS. Smart DNS можно включить в настройках маршрута.',parent=self):
            self.add_profile()
        else:
            StateManager.save_profile(ProxyProfile.parse('direct://',name='default').to_dict());self.refresh()

    def show(self):
        self.deiconify();self.lift()
        if self.dns_dialog and self.dns_dialog.winfo_exists():self.dns_dialog.lift()

    def hide_after_login(self):
        if self.tray and self.tray.available:self.withdraw()
        else:self.notice.set('Значок трея недоступен в этой среде. Окно оставлено открытым.')

    def open_dns(self):
        if self.dns_dialog and self.dns_dialog.winfo_exists():self.dns_dialog.lift();return
        from .dns_desktop import DnsDialog
        self.dns_dialog=DnsDialog(self)

    def change_startup(self):
        try:
            enabled=self.startup.set_enabled(self.login_start.get())
            self.login_start.set(enabled);self.notice.set('Автозапуск при следующем входе '+('включён.' if enabled else 'выключен.'))
        except Exception as exc:
            self.login_start.set(not self.login_start.get());messagebox.showerror('Автозапуск',str(exc),parent=self)
    def selected(self):
        selected=self.apps.selection()
        if not selected:raise ValueError('Выберите приложение.')
        return selected[0]
    def refresh(self):
        old=self.apps.selection();self.apps.delete(*self.apps.get_children())
        for app,a in self.adapters.items():
            try:exe=executable(a)
            except RuntimeError:exe=None
            self.apps.insert('',tk.END,iid=app,text=a.display_name,values=('Установлено' if exe else 'Не найдено',exe or ''))
        first=old[0] if old and old[0] in self.adapters else next(iter(self.adapters),None)
        if first:self.apps.selection_set(first)
        names=list(StateManager.list_profiles());self.profiles['values']=names
        if self.profile.get() not in names and names:self.profile.set(names[0])
        self.current_profile=self.profile.get();self.update_state()
    def update_state(self):
        data=StateManager.get_profile(self.current_profile) or {}
        self.proxy_on.set(data.get('proxy_enabled',True) and data.get('protocol')!='direct');self.smart_on.set(data.get('smart_dns',False))
        try:
            app=self.selected();s=self.shortcuts.status(app)
            self.session_state.configure(text='Ярлыки: '+('включены' if s['enabled'] else 'изменены — нужен откат' if s['changed'] else 'выключены')+' · Вход в аккаунт и модели проверяются в приложении.')
        except Exception as exc:self.session_state.configure(text=redact(exc))
    def work(self,action):
        if self.busy:return
        self.busy=True;self.notice.set('Выполняется…')
        def run():
            try:self.events.put((True,action()))
            except Exception as exc:self.events.put((False,redact(exc)))
        threading.Thread(target=run,daemon=True).start()
    def act(self,action):
        try:app=self.selected()
        except Exception as exc:messagebox.showwarning('Dagami Agent Proxy',str(exc),parent=self);return
        self.work(lambda:action(app))
    def pump(self):
        try:
            while True:
                action=self.tray_events.get_nowait()
                if action=='open':self.show()
                elif action=='quit':
                    if self.exit_app():return
        except queue.Empty:pass
        try:
            while True:
                ok,result=self.events.get_nowait();self.busy=False
                self.notice.set(str(result) if ok and isinstance(result,str) else 'Готово. Управление фоновыми сессиями доступно в меню «Ещё».' if ok else str(result))
                if not ok:messagebox.showerror('Dagami Agent Proxy',str(result),parent=self)
                self.refresh()
        except queue.Empty:pass
        self.after(100,self.pump)
    def add_profile(self):
        from .proxy_editor import ProfileEditor
        if not self.busy:ProfileEditor(self)

    def add_dns_profile(self):
        from .dns_profile_editor import DnsProfileEditor
        if not self.busy:DnsProfileEditor(self)

    def set_executable(self):
        try:
            app=self.selected();path=filedialog.askopenfilename(parent=self,title='Выберите исполняемый файл приложения')
            if path:register_executable(app,path);self.refresh()
        except Exception as exc:messagebox.showerror('Dagami Agent Proxy',redact(exc),parent=self)
    def edit_credentials(self):
        from .proxy_editor import ProfileEditor
        if self.busy:return
        if not StateManager.get_profile(self.current_profile):
            self.add_profile();return
        data=StateManager.get_profile(self.current_profile)
        if data.get('smart_dns') and not data.get('proxy_enabled',True):
            from .dns_profile_editor import DnsProfileEditor
            DnsProfileEditor(self,name=self.current_profile)
        else:ProfileEditor(self,name=self.current_profile)

    def check_proxy(self):
        profile=load_profile(self.current_profile)
        dns_only=profile.smart_dns and (not profile.proxy_enabled or profile.protocol=='direct')
        targets=[('Antigravity','cloudcode-pa.googleapis.com',443),('Google AI','generativelanguage.googleapis.com',443)] if dns_only and profile.dns_scope=='google' else None
        result=ProxyValidator.validate(profile,targets=targets)
        if not result.overall_success:raise RuntimeError('; '.join(result.errors) or 'Не все сетевые проверки прошли.')
        return 'Маршрут доступен; TLS проверен. Аккаунт, регион и доступ к моделям проверяются в самом приложении.'
    def stop_session(self):
        if messagebox.askyesno('Остановить','Сохраните работу. Завершить приложение и его прокси-сессию?',parent=self):self.act(lambda app:request(app,'stop'))
    def select_profile(self):
        self.current_profile=self.profile.get();self.update_state()

    def toggle_route(self):
        from .macos_settings import active_sessions,stop_sessions
        data=StateManager.get_profile(self.current_profile)
        if self.busy or not data:self.update_state();return
        proposed=dict(data,proxy_enabled=self.proxy_on.get(),smart_dns=self.smart_on.get())
        if self.proxy_on.get() and data.get('protocol')=='direct':
            messagebox.showinfo('Прокси','Сначала добавьте профиль с адресом upstream-прокси.',parent=self);self.update_state();return
        try:
            sessions=active_sessions(self.current_profile)
            if sessions and not messagebox.askyesno('Смена маршрута','Сохраните работу. Закрыть приложения и фоновые процессы?\n\n'+'\n'.join(n for _,n in sessions),parent=self,default='no'):
                self.update_state();return
            def commit():
                stop_sessions(sessions);StateManager.save_profile(proposed)
                return 'Маршрут сохранён. Приложения можно запустить заново.'
            self.work(commit)
        except Exception as exc:messagebox.showerror('Маршрут',str(exc),parent=self);self.update_state()

    def prepare_backend(self,app):
        from .macos_backend import prepare
        return prepare(app)

    def restore_preparation(self,app):
        from .macos_backend import restore,record
        messages=[]
        if record(app):messages.append(restore(app))
        self.shortcuts.restore(app)
        return '\n'.join(messages+['Управляемые ярлыки восстановлены.'])

    def restore_backend(self,app):
        from .macos_backend import restore
        return restore(app)

    def route_settings(self):
        from .macos_settings import dialog
        dialog(self)

    def add_app(self):
        path=filedialog.askopenfilename(parent=self,title='Выберите .app или исполняемый файл')
        if not path:return
        from .adapters.custom import add
        try:
            cli=not ('.app/' in path or path.endswith('.app')) and messagebox.askyesno('Тип приложения','Это консольная команда? Открывать её в Terminal?',parent=self)
            app=add(path,cli);self.adapters={a.app_id:a for a in list_adapters() if sys.platform in a.supported_os}
            self.refresh();self.apps.selection_set(app)
            self.notice.set('Добавлено. Программа получает HTTP(S)-окружение. Приложения, игнорирующие proxy-env, требуют отдельного адаптера.')
        except Exception as exc:messagebox.showerror('Добавление',str(exc),parent=self)

    def remove_app(self):
        from .adapters.custom import remove
        try:
            remove(self.selected());self.adapters={a.app_id:a for a in list_adapters() if sys.platform in a.supported_os};self.refresh()
        except Exception as exc:messagebox.showerror('Удаление',str(exc),parent=self)

    def login(self):
        from .macos_login import dialog
        dialog(self)
    def show_log(self):
        try:
            app=self.selected();path=runtime_dir()/(app+'.log');text=redact(path.read_text(encoding='utf-8',errors='replace')[-65536:]) if path.exists() else 'Журнал пока пуст.'
            dialog=tk.Toplevel(self);dialog.title('Журнал — '+app);dialog.geometry('780x440');view=tk.Text(dialog,wrap='word');view.pack(fill='both',expand=True);view.insert('1.0',text);view.configure(state='disabled')
        except Exception as exc:messagebox.showerror('Dagami Agent Proxy',redact(exc),parent=self)
    def close(self):
        if not self.can_close():return
        if self.tray and self.tray.available:self.withdraw()
        else:self.exit_app()

    def can_close(self):
        if self.busy or (self.dns_dialog and self.dns_dialog.winfo_exists() and self.dns_dialog.busy):
            messagebox.showinfo('Dagami Agent Proxy','Дождитесь завершения операции.',parent=self);return False
        return True

    def exit_app(self):
        if not self.can_close():return False
        if self.tray:self.tray.stop()
        self.destroy()
        return True

    def destroy(self):
                                                                              
        for timer in self.tk.splitlist(self.tk.call('after','info')):
            self.tk.call('after','cancel',timer)
        super().destroy()

def main(autostart=False):
    from .portable_instance import Instance
    with Instance() as instance:
        if not instance.primary:return 0
        if sys.platform == 'darwin':
            from .macos_activation import ensure_activation
            if not ensure_activation(autostart):return 0
        app=Desktop(autostart=autostart,first_run=not autostart)
        def incoming():
            if instance.consume_show():app.show()
            app.after(200,incoming)
        app.after(200,incoming);app.mainloop()
    return 0
