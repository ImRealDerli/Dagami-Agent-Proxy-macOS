import hmac
from .core.recovery import StateManager
from .core.profile import ProxyProfile
from .core.secrets import SecretStore,EphemeralStore
from .core.smart_dns import Endpoint,validate_domains
from .proxy_editor import parse_connection,save_connection
from .macos_settings import active_sessions
from .journal import register_secret


def current(name):
    value=StateManager.get_profile(name)
    if value is None:raise ValueError('Профиль больше не существует. Обновите список.')
    return value


def details(name):
    data=current(name);profile=ProxyProfile.from_dict(data)
    if data.get('requires_password'):
        password=SecretStore.get_password(name)
        if password is None:raise RuntimeError('Не удалось прочитать сохранённый пароль. Разблокируйте Связку ключей и нажмите «Повторить». Профиль не изменён.')
        profile.password=password;register_secret(password)
    url=profile.to_url();register_secret(url)
    return {'name':name,'url':url,'proxy':bool(data.get('proxy_enabled',True) and profile.protocol!='direct'),
        'dns':bool(data.get('smart_dns')),'endpoints':list(data.get('dns_endpoints') or []),
        'scope':data.get('dns_scope','ai'),'domains':list(data.get('dns_domains') or [])}


def require_inactive(name):
    if active_sessions(name):raise ValueError('Профиль используется открытой сессией. Сначала остановите её в разделе «Сессии».')


def save(name,values,replace=False):
    name=name.strip()
    old=StateManager.get_profile(name)
    if replace and old is None:raise ValueError('Профиль больше не существует. Обновите список.')
    if old is not None:require_inactive(name)
    proxy=values['proxy'];dns=values['dns']
    if type(proxy) is not bool or type(dns) is not bool:raise ValueError('Некорректные флаги подключения.')
    raw=values.get('url','').strip() or 'direct://'
    parsed=parse_connection(raw,name)
    if proxy and parsed.protocol=='direct':raise ValueError('Вставьте ссылку прокси перед его включением.')
    endpoints=[v.strip() for v in values.get('endpoints',[]) if isinstance(v,str) and v.strip()]
    if dns and not 1<=len(endpoints)<=32:raise ValueError('Укажите от 1 до 32 DNS-серверов.')
    if len(endpoints)>32:raise ValueError('Укажите не больше 32 DNS-серверов.')
    for endpoint in endpoints:Endpoint.parse(endpoint)
    scope=values.get('scope','ai')
    if scope not in ('ai','google'):raise ValueError('Неизвестный набор доменов.')
    domains=validate_domains(values.get('domains',[]))
    save_connection(name,raw,replace=replace,settings={'proxy_enabled':proxy,'smart_dns':dns,'dns_endpoints':endpoints,'dns_scope':scope,'dns_domains':domains})
    return 'Профиль сохранён.'


def delete(name):
    old=current(name);require_inactive(name)
    previous=SecretStore.get_password(name) if old.get('requires_password') else None
    if old.get('requires_password') and previous is None:
        raise RuntimeError('Сохранённый пароль недоступен. Разблокируйте Связку ключей и повторите удаление. Профиль сохранён.')
    if previous is not None:register_secret(previous)
    changed=False
    try:
        if previous is not None:
            changed=True
            if not SecretStore.delete_password(name):raise RuntimeError('Не удалось удалить пароль из Связки ключей. Профиль сохранён.')
        if not StateManager.delete_profile(name):raise ValueError('Профиль больше не существует.')
    except Exception:
        if changed:
            stored=SecretStore.store_password(name,old.get('username') or '',previous)
            restored=SecretStore.get_password(name)
            if stored!='os_keychain' or restored is None or not hmac.compare_digest(restored.encode(),previous.encode()):
                EphemeralStore.delete(name)
                raise RuntimeError('Удаление не завершено, восстановить пароль не удалось. Профиль проверьте после разблокировки Связки ключей.') from None
        raise
    EphemeralStore.delete(name)
    return 'Профиль удалён.'
