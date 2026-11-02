import dataclasses,os,shlex
from .core.profile import ProxyProfile

ROUTING={'--proxy-server','--proxy-pac-url','--proxy-auto-detect','--no-proxy-server','--proxy-bypass-list'}
VALUES={'--proxy-server','--proxy-pac-url','--proxy-bypass-list'}

def clean_flags(arguments):
    result=[];index=0
    while index<len(arguments):
        value=arguments[index];key=value.split('=',1)[0].lower()
        if key in ROUTING:
            index+=1
            if key in VALUES and '=' not in value and index<len(arguments) and not arguments[index].startswith('--'):index+=1
            continue
        result.append(value);index+=1
    return result

def route_profile(app,profile):
    if app=='gemini' and profile.proxy_enabled and profile.protocol!='direct':return dataclasses.replace(profile,smart_dns=False)
    return profile

def environment(adapter,local,executable):
    result=adapter.get_launch_environment(local,executable)
    for key in ('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS','QTWEBENGINE_CHROMIUM_FLAGS'):
        existing=result.get(key,os.environ.get(key))
        if existing is None:continue
        try:arguments=shlex.split(existing)
        except ValueError:raise ValueError('Не удалось разобрать параметры браузера. Маршрут не изменён.') from None
        arguments=clean_flags(arguments)+['--proxy-server='+local,'--proxy-bypass-list=localhost;127.0.0.1;[::1]','--disable-quic']
        result[key]=shlex.join(arguments)
    return result
