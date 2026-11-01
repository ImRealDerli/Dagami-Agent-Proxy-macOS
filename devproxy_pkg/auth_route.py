import http.client,re,ssl
from urllib.parse import urlsplit


def verify_route(local,url,profile='',timeout=6):
    target=urlsplit(url);proxy=urlsplit(local)
    if target.scheme!='https' or not target.hostname or proxy.hostname not in ('127.0.0.1','localhost') or not proxy.port:raise ValueError('Недопустимый маршрут входа.')
    context=ssl.create_default_context()
    connection=http.client.HTTPSConnection(proxy.hostname,proxy.port,timeout=timeout,context=context)
    connection.set_tunnel(target.hostname,target.port or 443)
    try:connection.connect()
    except (OSError,http.client.HTTPException) as exc:
        match=re.search(r'\b(4\d\d|5\d\d)\b',str(exc));reason='HTTP '+match.group(1) if match else ('ошибка сертификата TLS' if isinstance(exc,ssl.SSLError) else 'соединение не установлено')
        raise RuntimeError('Профиль «'+profile+'»: вход на '+target.hostname+' недоступен ('+reason+'). Проверьте прокси этого профиля или явно выберите профиль Smart DNS. Прямой резервный маршрут не включался.') from None
    finally:connection.close()
    return 'TLS до '+target.hostname+' через профиль «'+profile+'» проверен.'


def probe_profile(name,service,url=''):
    from .auth_manager import SERVICES,validate_url
    from .portable_runtime import load_profile
    from .core.tunnel import LocalTunnel
    if service not in SERVICES:raise ValueError('Неизвестный сервис.')
    target=url or SERVICES[service]['url'] or ('https://accounts.google.com/' if service in ('antigravity','antigravity-ide','agy') else '')
    if not target:raise ValueError('Вставьте HTTPS-ссылку для проверки.')
    validate_url(target,service,manual=True)
    tunnel=LocalTunnel(load_profile(name))
    try:return verify_route('http://127.0.0.1:'+str(tunnel.start()),target,name)
    finally:tunnel.stop()
