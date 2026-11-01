
import time
from .core.profile import ProxyProfile
from .core.recovery import StateManager
from .core.smart_dns import DEFAULT_ENDPOINTS,PROVIDERS,Endpoint,Resolver,import_mobileconfig


def active_sessions(profile):
    from .adapters import list_adapters
    from .portable_runtime import request
    result=[]
    for adapter in list_adapters():
        status=request(adapter.app_id)
        if status and status.get('profile')==profile:result.append((adapter.app_id,adapter.display_name))
    return result


def stop_sessions(sessions):
    from .portable_runtime import request
    for app,_ in sessions:request(app,'stop')
    deadline=time.monotonic()+20
    for app,_ in sessions:
        while request(app):
            if time.monotonic()>deadline:raise RuntimeError('Приложение не подтвердило остановку: '+app+'. Настройки не сохранены.')
            time.sleep(.2)


def dialog(parent):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    from .portable_runtime import load_profile
    name=parent.current_profile
    try:profile=load_profile(name)
    except Exception as exc:messagebox.showerror('Настройки',str(exc),parent=parent);return
    window=tk.Toplevel(parent);window.title('Маршрут — '+name);window.geometry('720x570')
    body=ttk.Frame(window,padding=20);body.pack(fill='both',expand=True)
    upstream=tk.BooleanVar(value=profile.proxy_enabled and profile.protocol!='direct')
    smart=tk.BooleanVar(value=profile.smart_dns);padding=tk.BooleanVar(value=profile.dns_padding);block=tk.BooleanVar(value=profile.block_updates)
    ttk.Checkbutton(body,text='Использовать прокси (адрес и пароль сохраняются при выключении)',variable=upstream).pack(anchor='w')
    ttk.Checkbutton(body,text='Использовать Smart DNS для ИИ-сервисов',variable=smart).pack(anchor='w',pady=6)
    ttk.Label(body,text='DNS endpoints, по одному в строке: HTTPS / TLS / UDP / TCP').pack(anchor='w',pady=(14,4))
    view=tk.Text(body,height=6,wrap='none');view.pack(fill='x');view.insert('1.0','\n'.join(profile.dns_endpoints or DEFAULT_ENDPOINTS))
    row=ttk.Frame(body);row.pack(fill='x',pady=8);provider=tk.StringVar(value='Dagami → MagicDNS')
    ttk.Combobox(row,textvariable=provider,values=['Dagami → MagicDNS',*PROVIDERS],state='readonly',width=22).pack(side='left')
    def use():view.delete('1.0','end');view.insert('1.0','\n'.join(DEFAULT_ENDPOINTS if provider.get()=='Dagami → MagicDNS' else PROVIDERS[provider.get()]))
    ttk.Button(row,text='Выбрать',command=use).pack(side='left',padx=6)
    def import_profile():
        path=filedialog.askopenfilename(parent=window,filetypes=[('Профиль DNS','*.mobileconfig'),('Все файлы','*')])
        if not path:return
        from pathlib import Path
        try:
            endpoints=import_mobileconfig(Path(path).read_bytes());view.delete('1.0','end');view.insert('1.0','\n'.join(endpoints))
        except Exception as exc:messagebox.showerror('Импорт',str(exc),parent=window)
    ttk.Button(row,text='Импорт .mobileconfig',command=import_profile).pack(side='left')
    ttk.Checkbutton(body,text='DNS padding (экспериментально)',variable=padding).pack(anchor='w')
    ttk.Checkbutton(body,text='Блокировать известные автообновления Antigravity в мосте',variable=block).pack(anchor='w',pady=5)
    frag=tk.StringVar(value=str(profile.tls_fragment))
    row=ttk.Frame(body);row.pack(fill='x',pady=8)
    ttk.Label(row,text='Разделение TLS при отправке (эксперимент):').pack(side='left')
    ttk.Combobox(row,textvariable=frag,values=['0','1','8','32'],state='readonly',width=6).pack(side='left',padx=8)
    status=tk.StringVar(value='Без прокси и Smart DNS используется сеть macOS, включая системный VPN.')
    ttk.Label(body,textvariable=status,wraplength=670).pack(anchor='w',pady=12)
    def endpoints():
        values=[line.strip() for line in view.get('1.0','end').splitlines() if line.strip()]
        if not values or len(values)>32:raise ValueError('Укажите от 1 до 32 DNS endpoints.')
        for v in values:Endpoint.parse(v)
        return values
    def probe():
        try:resolver=Resolver(endpoints(),padding.get())
        except Exception as exc:status.set(str(exc));return
        window.destroy();parent.work(resolver.probe)
    def save():
        try:
            values=endpoints()
            if upstream.get() and profile.protocol=='direct':raise ValueError('Сначала добавьте профиль с адресом прокси.')
            captured=profile.to_dict();captured.update(proxy_enabled=upstream.get(),smart_dns=smart.get(),dns_endpoints=values,dns_padding=padding.get(),block_updates=block.get(),tls_fragment=int(frag.get()))
            old=StateManager.get_profile(name);captured['requires_password']=bool(old.get('requires_password'))
            sessions=active_sessions(name)
            if sessions and not messagebox.askyesno('Смена маршрута','Сохраните работу. Закрыть приложения и их фоновые процессы перед сменой маршрута?\n\n'+'\n'.join(n for _,n in sessions),parent=window,default='no'):return
            def commit():
                stop_sessions(sessions)
                StateManager.save_profile(captured)
                return 'Маршрут сохранён. Запустите приложение заново.'
            window.destroy();parent.work(commit)
        except Exception as exc:status.set(str(exc))
    buttons=ttk.Frame(body);buttons.pack(fill='x',pady=8)
    ttk.Button(buttons,text='Проверить DNS-узлы',command=probe).pack(side='left')
    ttk.Button(buttons,text='Сохранить маршрут',command=save).pack(side='right')
    window.transient(parent)
