
import sys,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from devproxy_pkg.core.recovery import StateManager
from devproxy_pkg.portable_runtime import load_profile,launch_desktop_app,request,executable,runtime_dir,redact
from devproxy_pkg.adapters import list_adapters
from devproxy_pkg.core.smart_dns import PROVIDERS
from devproxy_pkg.auth_manager import AuthManager
AUTH=AuthManager()
import signal
def terminate_auth(signum,frame):
    AUTH.stop();raise SystemExit(0)
signal.signal(signal.SIGTERM,terminate_auth)

def snapshot():
    from devproxy_pkg.macos_activation import License
    from devproxy_pkg.system_dns import backend,Store
    profiles=[]
    for name,data in StateManager.list_profiles().items():
        profiles.append({'id':name,'name':name,'dns':bool(data.get('smart_dns')),'proxy':bool(data.get('proxy_enabled',True) and data.get('protocol')!='direct'),'endpoints':data.get('dns_endpoints',[]),'scope':data.get('dns_scope','ai'),'domains':data.get('dns_domains',[])})
    apps=[]
    for adapter in list_adapters():
        if adapter.app_id.startswith('custom_'):
            from devproxy_pkg.adapters.antigravity_ide import AntigravityIDEAdapter
            if AntigravityIDEAdapter.identify(adapter.detect_executable() or '') and not request(adapter.app_id):continue
        try:path=executable(adapter)
        except Exception:path=''
        from devproxy_pkg.preparation_state import inspect as preparation_state
        preparation=preparation_state(adapter.app_id);prepared=preparation['prepared']
        from devproxy_pkg.macos_architecture import compatibility_error
        launch_error=compatibility_error(path) if path else None
        apps.append({'preparationError':preparation['error'] or None,'recoverable':preparation['recoverable'],'launchError':launch_error,'prepared':prepared,'id':adapter.app_id,'name':adapter.display_name,'path':path,'installed':bool(path)})
    try:services=backend().services()
    except Exception:services=[]
    try:dns=json.loads((Store().root/'status.json').read_text());dns_status=dns.get('status','Не настроен')
    except Exception:dns_status='Нет данных'
    try:active=License.activated()
    except Exception:active=False
    from devproxy_pkg.portable_startup import Startup
    try:startup=Startup(command=[os.environ['DAGAMI_NATIVE_APP']]).enabled()
    except Exception:startup=False
    from devproxy_pkg.session_telemetry import enabled as monitoring_enabled
    from devproxy_pkg.desktop_monitoring import installed as desktop_monitoring
    from devproxy_pkg.core.rust_transport import binary_path
    return {'networkEngine':'Rust' if binary_path() else 'Python','monitoring':monitoring_enabled(),'desktopMonitoring':desktop_monitoring(),'profiles':profiles,'apps':apps,'services':services,'systemDNS':dns_status,'activated':active,'startup':startup,'providers':PROVIDERS}

def perform(data):
    action=data.get('action');args=data.get('args',{})
    if action=='snapshot':return snapshot()
    if action=='sessionMonitoring':
        state=StateManager.load_state();state['session_monitoring']=bool(args['enabled']);StateManager.save_state(state);return 'Настройка статистики сохранена. Для новых подключений перезапустите нужный клиент.'
    if action=='desktopMonitoring':
        from devproxy_pkg.desktop_monitoring import configure
        return configure(bool(args['enabled']))
    if action=='sessionQuota':
        from devproxy_pkg.macos_activity import sessions
        row=next((r for r in sessions() if r['id']==args['session']),None)
        if not row:raise ValueError('Сессия уже завершилась.')
        app=row.get('app') or row['id']
        if app in ('antigravity','antigravity-ide'):
            from devproxy_pkg.antigravity_limits import for_session
        else:
            from devproxy_pkg.codex_limits import for_session
        return for_session(args['session'])
    if action in ('profileDetails','profileSave','profileDelete'):
        from devproxy_pkg import macos_profile_editor
        name=args['name']
        if action=='profileDetails':return macos_profile_editor.details(name)
        if AUTH.session and not AUTH.session.closed and AUTH.session.profile==name:raise ValueError('Сначала завершите вход, который использует этот профиль.')
        if action=='profileDelete':return macos_profile_editor.delete(name)
        return macos_profile_editor.save(name,args,replace=args.get('replace',False))
    if action in ('sessions','journalEntries'):
        from devproxy_pkg import macos_activity
        return macos_activity.sessions() if action=='sessions' else macos_activity.entries()
    if action in ('updateCheck','updateInstall','updateAck'):
        from devproxy_pkg import macos_updates
        if action=='updateCheck':return macos_updates.check(args.get('profile',''))
        if action=='updateAck':return macos_updates.acknowledge()
        return macos_updates.install(args['tag'],args.get('profile',''))
    if action in ('appInspect','appClose'):
        from devproxy_pkg import desktop_processes
        return desktop_processes.inspect(args['app']) if action=='appInspect' else desktop_processes.close(args['app'])
    if action=='repairIDE':
        from devproxy_pkg.ide_repair import repair
        return repair(args['app'])
    if action=='journal':
        from devproxy_pkg.journal import read
        return read()
    if action=='prepareAuth':
        app=args.get('app','antigravity')
        if app not in ('antigravity','antigravity-ide'):raise ValueError('Неизвестное приложение.')
        from devproxy_pkg.auth_route import probe_profile
        probe_profile(args['profile'],'antigravity')
        AUTH.stop()
        from devproxy_pkg.macos_backend import record,restore,prepare
        from devproxy_pkg.portable_runtime import start_session
        import time
        if request(app):
            request(app,'stop')
            for _ in range(150):
                if not request(app):break
                time.sleep(.1)
            else:raise RuntimeError('Сессия IDE ещё завершается. Повторите после остановки.')
        if record(app):restore(app)
        if app=='antigravity-ide':
            from devproxy_pkg.ide_preparation import prepare as prepare_ide
            prepare_ide()
        else:prepare(app)
        start_session(app,args['profile'])
        return 'Вход в IDE настроен. Нажмите «Начать вход», затем «Войти» в Antigravity.'
    if action=='checkIDE':
        from devproxy_pkg.ide_readiness import check_manifest
        return check_manifest(args['profile'])
    if action=='probeAuth':
        from devproxy_pkg.auth_route import probe_profile
        return probe_profile(args['profile'],args['service'],args.get('url',''))
    if action=='authClipboard':
        if not AUTH.session or AUTH.session.closed:raise ValueError('Сначала начните ожидание входа.')
        if AUTH.session.profile!=args['profile'] or AUTH.session.service!=args['service']:raise ValueError('Сервис и профиль буфера не совпадают с активной сессией входа.')
        return AUTH.session.clipboard_url(args['url'])
    if action=='authStart':return AUTH.start(args['service'],args['profile'],args.get('mode','browser'),args.get('auto',True),args.get('url',''))
    if action=='authStatus':return AUTH.status()
    if action=='authStop':return AUTH.stop()
    if action=='authOpen':return AUTH.open(args['url'])
    if action=='authFind':
        if args['service'] in ('antigravity','antigravity-ide'):
            active=request(args['service'],'authStatus')
            if active:
                if active.get('profile')!=args.get('profile'):raise ValueError('Выберите тот же профиль, с которым запущена Antigravity.')
                if active.get('url'):return active['url']
        from devproxy_pkg.auth_manager import find_link
        return find_link(args['service'])
    if action=='licenseReset':
        AUTH.stop()
        from devproxy_pkg.macos_activation import License
        License.deactivate();return 'Ключ активации Dagami сброшен. Профили и аккаунты ИИ сохранены.'
    if action=='activate':
        from devproxy_pkg.macos_activation import License
        License.activate(args['key']);return 'Доступ активирован'
    if action=='saveDNS':
        from devproxy_pkg.dns_profile_editor import save_dns_profile
        from devproxy_pkg.macos_settings import active_sessions
        if active_sessions(args['name']):raise ValueError('Сначала остановите приложения этого профиля.')
        return save_dns_profile(args['name'],args['endpoints'],replace=args.get('replace',False),scope=args.get('scope','ai'),domains=args.get('domains',[]))
    if action=='saveProxy':
        from devproxy_pkg.proxy_editor import save_connection
        from devproxy_pkg.macos_settings import active_sessions
        if active_sessions(args['name']):raise ValueError('Сначала остановите приложения этого профиля.')
        return save_connection(args['name'],args['url'],replace=args.get('replace',False))
    if action=='launch':return launch_desktop_app(args['app'],args['profile'])
    if action=='stop':return request(args['app'],'stop') or 'Сессия не запущена'
    if action in ('check','checkConnection'):
        from devproxy_pkg.core.validator import ProxyValidator
        profile=load_profile(args['profile']);r=ProxyValidator.validate(profile,timeout=12)
        if action=='checkConnection':return {'success':r.overall_success,'targets':r.target_checks,'errors':r.errors}
        return '\n'.join(('✓ ' if v['success'] else '✕ ')+v['name']+': '+('TLS проверен' if v['success'] else v['error'] or 'Нет ответа') for v in r.target_checks) or '; '.join(r.errors)
    if action=='probeDNS':
        from devproxy_pkg.core.smart_dns import Resolver
        return Resolver(args['endpoints']).probe()
    if action=='systemDNS':
        from devproxy_pkg.system_dns import execute
        return execute(args['operation'],server=args.get('server','89.22.224.205'),mode=args.get('mode','domains'),services=args.get('services',[]),preset='Development',replace=args.get('replace',False),restore_global=args.get('restore_global',False),confirmed=False)
    if action=='startup':
        from devproxy_pkg.portable_startup import Startup
        return Startup(command=[os.environ['DAGAMI_NATIVE_APP']]).set_enabled(args['enabled'])
    if action in ('prepare','restore'):
        if args['app']=='antigravity-ide' and action=='prepare':
            from devproxy_pkg.ide_preparation import prepare as prepare_ide
            return prepare_ide()
        if args['app']=='chatgpt':
            from devproxy_pkg import chatgpt_preparation
            return chatgpt_preparation.prepare(args['profile']) if action=='prepare' else chatgpt_preparation.restore()
        if args['app'] in ('codex','codex-gui'):
            from devproxy_pkg import codex_preparation
            return codex_preparation.prepare(args['app'],args['profile']) if action=='prepare' else codex_preparation.restore(args['app'])
        from devproxy_pkg import macos_backend
        return getattr(macos_backend,action)(args['app'])
    if action=='shortcut':
        from devproxy_pkg.portable_shortcuts import PortableShortcuts
        return PortableShortcuts().enable(args['app'],args['profile'])
    if action=='unpatch':
        from devproxy_pkg.portable_shortcuts import PortableShortcuts
        from devproxy_pkg import macos_backend
        if macos_backend.record(args['app']):macos_backend.restore(args['app'])
        return PortableShortcuts().restore(args['app'])
    if action=='addApp':
        from devproxy_pkg.adapters.custom import add
        return add(args['path'],args.get('cli',False))
    if action=='removeApp':
        from devproxy_pkg.adapters.custom import remove
        return remove(args['app'])
    if action=='loginURL':
        from devproxy_pkg.macos_login import fresh_url
        return fresh_url()
    if action=='login':
        from devproxy_pkg.macos_login import choose_account
        url=choose_account(args['url']) if args.get('choose',True) else args['url']
        return request(args['app'],'login',url=url) or 'Сначала запустите приложение через Dagami'
    raise ValueError('Неизвестная команда')

if __name__=='__main__':
    for line in sys.stdin:
        data={}
        try:
            data=json.loads(line)
            value=perform(data)
            from devproxy_pkg.journal import append
            try:
                if data.get('action')=='checkConnection':
                    text='\n'.join(('✓ ' if v['success'] else '✕ ')+v['name']+': '+('TLS проверен' if v['success'] else v.get('error') or 'Нет ответа') for v in value['targets']) or '; '.join(value['errors'])
                    append('check',value['success'],text)
                else:append(data.get('action','unknown'),True,str(value))
            except Exception:pass
            answer={'ok':True,'result':value}
        except Exception as exc:
            try:
                from devproxy_pkg.journal import record_error
                record_error(data.get('action','unknown'),exc)
            except Exception:pass
            answer={'ok':False,'error':redact(str(exc))}
        print(json.dumps(answer,ensure_ascii=False),flush=True)
    AUTH.stop()
