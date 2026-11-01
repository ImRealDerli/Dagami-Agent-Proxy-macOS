
from pathlib import Path
import html
import re
import time
from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit
from .portable_runtime import validate_login


def fresh_url(home=None,now=None):
    home=Path(home or Path.home());now=now or time.time();files=[]
    for name in ('Antigravity','Antigravity IDE'):
        root=home/'Library'/'Application Support'/name/'logs'
        if not root.is_dir():continue
        for path in root.rglob('*.log'):
            try:
                if path.is_file() and not path.is_symlink() and now-600<=path.stat().st_mtime<=now+5:files.append(path)
            except OSError:pass
    for path in sorted(files,key=lambda p:p.stat().st_mtime,reverse=True)[:40]:
        try:
            with path.open('rb') as stream:
                stream.seek(max(0,path.stat().st_size-262144));raw=stream.read(262144).decode('utf-8','replace')
            urls=re.findall(r'https://accounts\.google\.com/[^\s<>"\x00]+',raw)
            for url in reversed(urls):
                url=html.unescape(url.rstrip("',);"))
                validate_login(url)
                from .auth_manager import validate_initial_auth_url
                validate_initial_auth_url(url)
                query=dict(parse_qsl(urlsplit(url).query))
                if query.get('client_id') and query.get('redirect_uri') and query.get('state'):return url
        except (OSError,ValueError):continue
    return ''


def choose_account(url):
    validate_login(url);p=urlsplit(url)
    query=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if k!='prompt']
    query.append(('prompt','select_account'))
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(query),p.fragment))


def dialog(parent):
    import tkinter as tk
    from tkinter import ttk,messagebox
    from .portable_runtime import request
    window=tk.Toplevel(parent);window.title('Google — вход через маршрут Dagami');window.geometry('680x260')
    body=ttk.Frame(window,padding=20);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Нажмите «Войти» в Antigravity, затем найдите свежую ссылку.\nСсылка действует только для начавшего вход приложения.').pack(anchor='w')
    value=tk.StringVar();error=tk.StringVar();account=tk.BooleanVar(value=True)
    field=ttk.Entry(body,textvariable=value);field.pack(fill='x',pady=12)
    ttk.Checkbutton(body,text='Предложить выбор Google-аккаунта',variable=account).pack(anchor='w')
    ttk.Label(body,textvariable=error,wraplength=620).pack(anchor='w',pady=10)
    def find():
        value.set(fresh_url());error.set('Ссылка найдена.' if value.get() else 'Свежая ссылка не найдена. Начните вход в Antigravity или вставьте её вручную.')
    def url():return choose_account(value.get()) if account.get() else validate_login(value.get())
    def copy():
        try:window.clipboard_clear();window.clipboard_append(url());error.set('Ссылка скопирована. Она содержит данные входа — не публикуйте её.')
        except ValueError as exc:error.set(str(exc))
    def login():
        try:app=parent.selected();target=url()
        except ValueError as exc:error.set(str(exc));return
        def open_login():
            if not request(app,'login',url=target):raise RuntimeError('Сначала запустите приложение через Dagami.')
            return 'Открыт браузер через маршрут активной сессии.'
        window.destroy();parent.work(open_login)
    buttons=ttk.Frame(body);buttons.pack(fill='x')
    for text,action in [('Найти ссылку',find),('Копировать',copy),('Открыть вход',login)]:ttk.Button(buttons,text=text,command=action).pack(side='left',padx=(0,8))
    window.transient(parent);find()
