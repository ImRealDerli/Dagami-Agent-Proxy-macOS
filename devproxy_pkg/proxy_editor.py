
import hmac
from .core.profile import ProxyProfile
from .core.recovery import StateManager
from .core.secrets import SecretStore,EphemeralStore


def parse_connection(raw,name):
    name=name.strip()
    if not name or len(name)>128 or any(ord(c)<32 for c in name):
        raise ValueError('Укажите название профиля без управляющих символов.')
    try:
        profile=ProxyProfile.parse(raw,name=name)
    except (ValueError,TypeError):
        raise ValueError('Некорректная ссылка прокси. Нужен формат https://логин:пароль@сервер:порт, http://, socks5:// или direct://.') from None
    if profile.username is not None and profile.password is None:
        raise ValueError('В ссылке указан логин без пароля. Вставьте полную ссылку с реквизитами.')
    if profile.username and ':' in profile.username:
        raise ValueError('Логин HTTP Basic не может содержать двоеточие.')
    return profile


def save_connection(name,raw,replace=False,settings=None):
    profile=parse_connection(raw,name);name=profile.name
    old=StateManager.get_profile(name)
    if old and not replace:raise ValueError('Профиль уже существует. Откройте «Изменить прокси» или выберите другое имя.')
    previous=SecretStore.get_password(name) if profile.password or (old and (old.get("requires_password") or old.get("username"))) else None
    if old and old.get('requires_password') and previous is None:
        raise RuntimeError('Прежний пароль недоступен. Разблокируйте Keychain и повторите сохранение.')
    data=profile.to_dict()
    if old:
                                                                                 
        data=dict(old,**{key:data[key] for key in ('name','protocol','host','port','username','dns_remote')})
    data.pop('password',None);data['requires_password']=bool(profile.password)
    if profile.protocol=='direct':data['proxy_enabled']=False
    elif not old or old.get('protocol')=='direct':data['proxy_enabled']=True
    if settings is not None:
        for key in ("proxy_enabled","smart_dns","dns_endpoints","dns_scope","dns_domains"):
            if key in settings:data[key]=settings[key]
    changed=False
    try:
        if profile.password:
            changed=True
            if SecretStore.store_password(name,profile.username or '',profile.password)!='os_keychain':
                raise RuntimeError('Пароль не сохранён в Keychain. Профиль не изменён.')
            stored=SecretStore.get_password(name)
            if stored is None or not hmac.compare_digest(stored.encode('utf-8'),profile.password.encode('utf-8')):
                raise RuntimeError('Keychain не подтвердил новый пароль. Профиль не изменён.')
        elif previous is not None:
            changed=True
            if not SecretStore.delete_password(name):raise RuntimeError('Не удалось удалить прежний пароль из Keychain.')
        StateManager.save_profile(data)
    except Exception:
        EphemeralStore.delete(name)
        if changed:
            if previous is not None:
                if SecretStore.store_password(name,(old or {}).get('username') or '',previous)!='os_keychain':
                    EphemeralStore.delete(name)
                    raise RuntimeError('Сохранение не завершено; прежний пароль не удалось восстановить. Разблокируйте Keychain и повторите ввод полной ссылки.') from None
            else:SecretStore.delete_password(name)
        raise
    return 'Профиль сохранён из полной ссылки. Пароль подтверждён в Keychain. Нажмите «Проверить».' if profile.password else 'Профиль сохранён из полной ссылки.'


class ProfileEditor:
    def __init__(self,parent,name=None):
        import tkinter as tk
        from tkinter import ttk
        self.parent=parent;self.editing=name is not None;self.parsed=None
        self.window=tk.Toplevel(parent);self.window.title('Изменить прокси' if self.editing else 'Новый профиль прокси');self.window.geometry('710x510');self.window.minsize(660,490)
        body=ttk.Frame(self.window,padding=20);body.pack(fill='both',expand=True);body.columnconfigure(1,weight=1)
        self.name=tk.StringVar(value=name or 'default');self.raw=tk.StringVar();self.status=tk.StringVar(value='Вставьте полную ссылку — все параметры заполнятся автоматически.')
        ttk.Label(body,text='Название профиля').grid(row=0,column=0,sticky='w',padx=(0,12),pady=5)
        ttk.Entry(body,textvariable=self.name,state='readonly' if self.editing else 'normal').grid(row=0,column=1,sticky='ew')
        ttk.Label(body,text='Полная ссылка прокси').grid(row=1,column=0,columnspan=2,sticky='w',pady=(18,5))
        self.url_entry=ttk.Entry(body,textvariable=self.raw,show='•');self.url_entry.grid(row=2,column=0,columnspan=2,sticky='ew')
        self.visible=tk.BooleanVar()
        ttk.Checkbutton(body,text='Показать ссылку',variable=self.visible,command=lambda:self.url_entry.configure(show='' if self.visible.get() else '•')).grid(row=3,column=0,columnspan=2,sticky='w',pady=(5,12))
        self.fields={}
        for row,(key,label) in enumerate((('protocol','Протокол'),('host','Сервер'),('port','Порт'),('username','Логин'),('password','Пароль')),4):
            ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',pady=5)
            var=tk.StringVar();self.fields[key]=var
            ttk.Entry(body,textvariable=var,state='readonly',show='•' if key=='password' else '').grid(row=row,column=1,sticky='ew',pady=5)
        ttk.Label(body,textvariable=self.status,wraplength=650).grid(row=9,column=0,columnspan=2,sticky='ew',pady=14)
        actions=ttk.Frame(body);actions.grid(row=10,column=0,columnspan=2,sticky='ew')
        ttk.Button(actions,text='Отмена',command=self.window.destroy).pack(side='left')
        ttk.Button(actions,text='Сохранить профиль',command=self.save).pack(side='right')
        self.raw.trace_add('write',self.preview);self.name.trace_add('write',self.preview)
        self.window.transient(parent);self.url_entry.focus_set()

    def preview(self,*_):
        try:
            self.parsed=parse_connection(self.raw.get(),self.name.get())
            for key,var in self.fields.items():var.set(str(getattr(self.parsed,key) or ''))
            self.status.set('Ссылка разобрана. Протокол, сервер, порт и реквизиты будут сохранены вместе.')
        except ValueError as exc:
            self.parsed=None
            for var in self.fields.values():var.set('')
            self.status.set(str(exc) if self.raw.get() else 'Вставьте полную ссылку — все параметры заполнятся автоматически.')

    def save(self):
        from tkinter import messagebox
        from .macos_settings import active_sessions,stop_sessions
        if self.parent.busy:return
        try:
            profile=parse_connection(self.raw.get(),self.name.get())
            old=StateManager.get_profile(profile.name)
            if old and not self.editing:
                if not messagebox.askyesno('Профиль уже существует','Заменить подключение существующего профиля полной ссылкой? Настройки Smart DNS сохранятся.',parent=self.window,default='no'):return
            sessions=active_sessions(profile.name) if old else []
            if sessions and not messagebox.askyesno('Изменение подключения','Сохраните работу. Закрыть приложения перед заменой прокси?\n\n'+'\n'.join(n for _,n in sessions),parent=self.window,default='no'):return
            raw=self.raw.get();name=profile.name
            self.parent.profile.set(name);self.parent.current_profile=name
            def commit():
                stop_sessions(sessions)
                return save_connection(name,raw,replace=bool(old))
            self.window.destroy();self.parent.work(commit)
        except Exception as exc:self.status.set(str(exc))
