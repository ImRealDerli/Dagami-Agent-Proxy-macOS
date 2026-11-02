
import hashlib
import hmac
import re
from .core.secrets import MacOSKeychainStore

ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
SALT = 'DagamiAgentProxySecretSalt2026'
BOT_URL = 'https://t.me/bright26bot?start=dagami'
ACCOUNT = 'dagami-activation-v1'


def normalize(raw):
    value = ''.join(c.upper() for c in str(raw) if c.isalnum())
    if not re.fullmatch(r'DAGAMI[A-Z0-9]{12}', value):
        return ''
    return 'DAGAMI-' + '-'.join(value[i:i+4] for i in (6, 10, 14))


def validate(raw):
    key = normalize(raw)
    if not key:
        return False
    body = key.replace('-', '')[6:]
    if any(c not in ALPHABET for c in body):
        return False
    checksum = ''.join(ALPHABET[b % 32] for b in hashlib.sha256((body[:8] + SALT).encode()).digest()[:4])
    return hmac.compare_digest(body[8:], checksum)


class License:
    @staticmethod
    def activated():
        return validate(MacOSKeychainStore.get_password(ACCOUNT) or '')

    @staticmethod
    def deactivate():
        if not MacOSKeychainStore.delete_password(ACCOUNT):
            raise RuntimeError('Не удалось сбросить ключ. Разрешите доступ к Keychain.')
        if MacOSKeychainStore.get_password(ACCOUNT):
            raise RuntimeError('Keychain не подтвердил удаление ключа.')

    @staticmethod
    def activate(raw):
        if not validate(raw):
            raise ValueError('Неверный ключ доступа. Проверьте правильность ввода.')
        if not MacOSKeychainStore.set_password(ACCOUNT, 'Dagami', normalize(raw)):
            raise RuntimeError('Не удалось сохранить ключ. '+(MacOSKeychainStore.last_error or 'Разрешите доступ в системном окне Связки ключей и повторите.'))


def ensure_activation(autostart=False):
    
    initial_error=''
    try:
        if License.activated():return True
    except Exception:
        initial_error='Связка ключей недоступна. Разблокируйте Keychain и повторите активацию.'
    if autostart:
        return False
    import tkinter as tk
    from tkinter import ttk
    import webbrowser
    root = tk.Tk()
    root.title('Dagami Agent Proxy — Активация')
    root.geometry('590x370')
    root.resizable(False, False)
    body = ttk.Frame(root, padding=28)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text='Dagami Agent Proxy', font=('TkDefaultFont', 22, 'bold')).pack(anchor='w')
    ttk.Label(body, text='Первый запуск · Активация', font=('TkDefaultFont', 13)).pack(anchor='w', pady=(8,18))
    ttk.Label(body, text='Введите ключ доступа из официального Telegram-бота.\nКлючи выдаются бесплатно.').pack(anchor='w')
    value = tk.StringVar()
    field = ttk.Entry(body, textvariable=value, font=('TkFixedFont', 17), show='•')
    field.pack(fill='x', pady=(18,6))
    ttk.Label(body, text='Формат: DAGAMI-XXXX-XXXX-XXXX').pack(anchor='w')
    error = tk.StringVar(value=initial_error)
    ttk.Label(body, textvariable=error, foreground='#b42318', wraplength=530).pack(anchor='w', pady=8)
    accepted = [False]
    def activate(*_):
        try:
            License.activate(value.get())
        except Exception as exc:
            error.set(str(exc)); field.focus_set(); return
        accepted[0] = True
        root.destroy()
    actions = ttk.Frame(body); actions.pack(fill='x', pady=8)
    ttk.Button(actions, text='Получить ключ в @bright26bot', command=lambda:webbrowser.open(BOT_URL)).pack(side='left')
    ttk.Button(actions, text='Активировать', command=activate).pack(side='right')
    root.bind('<Return>', activate)
    field.focus_set(); root.mainloop()
    return accepted[0]
