
from .core.profile import ProxyProfile
from .core.recovery import StateManager
from .core.smart_dns import Endpoint,DEFAULT_ENDPOINTS,PROVIDERS,validate_domains


def save_dns_profile(name,endpoints,replace=False,scope='ai',domains=None):
    name=name.strip()
    if not name or len(name)>128 or any(ord(c)<32 for c in name):raise ValueError('Укажите название профиля.')
    endpoints=[v.strip() for v in endpoints if v.strip()]
    if not 1<=len(endpoints)<=32:raise ValueError('Укажите от 1 до 32 DNS endpoints.')
    for endpoint in endpoints:Endpoint.parse(endpoint)
    if scope not in ('google','ai'):raise ValueError('Неизвестный набор доменов.')
    domains=validate_domains(domains or [])
    old=StateManager.get_profile(name)
    if old and not replace:raise ValueError('Профиль уже существует.')
    data=dict(old) if old else ProxyProfile.parse('direct://',name=name).to_dict()
    data.update(smart_dns=True,proxy_enabled=False,dns_endpoints=endpoints,dns_scope=scope,dns_domains=domains)
    StateManager.save_profile(data)
    return 'DNS-профиль сохранён. Выберите приложение и запустите его через Dagami.'


class DnsProfileEditor:
    def __init__(self,parent,name=None):
        import tkinter as tk
        from tkinter import ttk
        self.parent=parent;self.editing=name is not None
        old=StateManager.get_profile(name) if name else None
        self.window=tk.Toplevel(parent);self.window.title('DNS-профиль без прокси');self.window.geometry('740x600');self.window.minsize(680,570)
        body=ttk.Frame(self.window,padding=20);body.pack(fill='both',expand=True)
        self.name=tk.StringVar(value=name or 'ИИ — Smart DNS');self.provider=tk.StringVar(value='Dagami → MagicDNS');self.status=tk.StringVar()
        ttk.Label(body,text='Название профиля').pack(anchor='w')
        ttk.Entry(body,textvariable=self.name,state='readonly' if self.editing else 'normal').pack(fill='x',pady=(4,12))
        ttk.Label(body,text='Smart DNS для ИИ при запуске через Dagami. Доступность зависит от DNS-провайдера.\nОстальные адреса используют обычную сеть macOS.').pack(anchor='w')
        self.scope=tk.StringVar(value='Все ИИ' if (old or {}).get('dns_scope','ai')=='ai' else 'Google / Antigravity')
        ttk.Combobox(body,textvariable=self.scope,values=['Все ИИ','Google / Antigravity'],state='readonly').pack(fill='x',pady=8)
        ttk.Label(body,text='ChatGPT, Claude, Gemini, DeepSeek, Qwen, Grok, Perplexity, Mistral и другие').pack(anchor='w')
        row=ttk.Frame(body);row.pack(fill='x',pady=12)
        choices=ttk.Combobox(row,textvariable=self.provider,values=['Dagami → MagicDNS',*PROVIDERS,'Свой DNS'],state='readonly',width=25);choices.pack(side='left')
        choices.bind('<<ComboboxSelected>>',self.choose)
        ttk.Label(body,text='DNS endpoints, по одному в строке (IP, https://, tls://, udp://, tcp://)').pack(anchor='w')
        self.view=tk.Text(body,height=5,wrap='none');self.view.pack(fill='both',expand=True,pady=6)
        self.view.insert('1.0','\n'.join((old or {}).get('dns_endpoints') or DEFAULT_ENDPOINTS))
        ttk.Label(body,text='Свои домены (необязательно), по одному в строке; *.example.com включает поддомены').pack(anchor='w')
        self.domains=tk.Text(body,height=2,wrap='none');self.domains.pack(fill='x',pady=6)
        self.domains.insert('1.0','\n'.join((old or {}).get('dns_domains',[])))
        ttk.Label(body,textvariable=self.status,wraplength=650).pack(anchor='w',pady=10)
        actions=ttk.Frame(body);actions.pack(fill='x')
        ttk.Button(actions,text='Проверить DNS',command=self.probe).pack(side='left')
        ttk.Button(actions,text='Сохранить DNS-профиль',command=self.save).pack(side='right')
        self.window.transient(parent)

    def choose(self,*_):
        provider=self.provider.get()
        if provider=='Свой DNS':self.view.focus_set();return
        self.view.delete('1.0','end');self.view.insert('1.0','\n'.join(DEFAULT_ENDPOINTS if provider=='Dagami → MagicDNS' else PROVIDERS[provider]))

    def endpoints(self):
        values=[v.strip() for v in self.view.get('1.0','end').splitlines() if v.strip()]
        if not 1<=len(values)<=32:raise ValueError('Укажите от 1 до 32 DNS endpoints.')
        for value in values:Endpoint.parse(value)
        return values

    def probe(self):
        from .core.smart_dns import Resolver
        try:resolver=Resolver(self.endpoints())
        except Exception as exc:self.status.set(str(exc));return
        self.window.destroy();self.parent.work(resolver.probe)

    def save(self):
        from tkinter import messagebox
        from .macos_settings import active_sessions,stop_sessions
        if self.parent.busy:return
        try:
            name=self.name.get().strip();endpoints=self.endpoints();old=StateManager.get_profile(name)
            scope='ai' if self.scope.get()=='Все ИИ' else 'google'
            domains=validate_domains(self.domains.get('1.0','end').splitlines())
            if old and not self.editing and not messagebox.askyesno('Профиль существует','Переключить этот профиль на Smart DNS без прокси? Адрес и реквизиты прокси сохранятся.',parent=self.window,default='no'):return
            sessions=active_sessions(name) if old else []
            if sessions and not messagebox.askyesno('Смена маршрута','Сохраните работу. Закрыть приложения перед включением DNS-профиля?\n\n'+'\n'.join(n for _,n in sessions),parent=self.window,default='no'):return
            self.parent.profile.set(name);self.parent.current_profile=name
            def commit():
                stop_sessions(sessions)
                return save_dns_profile(name,endpoints,replace=bool(old),scope=scope,domains=domains)
            self.window.destroy();self.parent.work(commit)
        except Exception as exc:self.status.set(str(exc))
