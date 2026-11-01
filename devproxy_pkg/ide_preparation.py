import hashlib,shutil,subprocess,uuid
from pathlib import Path
from .adapters.antigravity_ide import AntigravityIDEAdapter
from .core.recovery import StateManager
from .core.process_env import external_environment
from .macos_backend import managed_root,record,checked_executable,digest,sign_bundle

BOOTSTRAP='Contents/Resources/app/extensions/agy/vscode/extension.js'
NETWORK='Contents/Resources/app/extensions/agy/vscode/dagami-ide-net.cjs'
SUPPORTED_SHA256='8a517aadfd52620cd7376afe53a2fb6894a534d135dd818a8893b0c810896e7f'
FETCH_NEEDLE=b'async function Aa(a,b={},c={}){var d=f.asyncContextStart()'
TIMEOUT_NEEDLE=b'timeoutMs:(B=b==null?void 0:b.timeoutMs)!=null?B:5E3'
OPEN_NEEDLE=b'n.env.openExternal('


def patch_bootstrap(content):
    if hashlib.sha256(content).hexdigest()!=SUPPORTED_SHA256:raise ValueError('Неизвестная версия загрузчика Antigravity IDE. Сетевой патч подтверждён для официальной IDE 2.6.0; оригинал не изменён.')
    if content.count(FETCH_NEEDLE)!=1 or content.count(TIMEOUT_NEEDLE)!=1 or content.count(OPEN_NEEDLE)!=3:raise ValueError('Неизвестная структура загрузчика IDE. Подготовка отменена.')
    content=content.replace(FETCH_NEEDLE,b'async function Aa(a,b={},c={}){if(process.env.DAGAMI_IDE_PROXY)return require("./dagami-ide-net.cjs").fetch(a,b);var d=f.asyncContextStart()')
    content=content.replace(TIMEOUT_NEEDLE,TIMEOUT_NEEDLE.replace(b'5E3',b'30E3'))
    return content.replace(OPEN_NEEDLE,b'require("./dagami-ide-net.cjs").openExternal(n.env.openExternal.bind(n.env),')


def prepare():
    from .portable_runtime import app_adapter,executable,request,require_stopped,session_lock
    from .macos_architecture import require_compatible
    app='antigravity-ide'
    with session_lock('backend'):
        if request(app):raise RuntimeError('Сначала остановите управляемую сессию Antigravity IDE.')
        if record(app):checked_executable(app);return 'Подготовка Antigravity IDE уже действует.'
        source=Path(executable(app_adapter(app))).resolve()
        if not AntigravityIDEAdapter.identify(source):raise ValueError('Выбрано другое приложение. Требуется Antigravity IDE с bundle ID com.google.antigravity-ide.')
        require_compatible(source);require_stopped(str(source))
        bundle=next(p for p in source.parents if p.suffix=='.app');changed=patch_bootstrap((bundle/BOOTSTRAP).read_bytes())
        root=managed_root();root.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=root/uuid.uuid4().hex/bundle.name;target.parent.mkdir(mode=0o700)
        try:
            subprocess.run(['/usr/bin/ditto',str(bundle),str(target)],check=True,capture_output=True,env=external_environment())
            path=target/BOOTSTRAP;mode=path.stat().st_mode;path.chmod(mode|0o200);path.write_bytes(changed);path.chmod(mode)
            helper=Path(__file__).resolve().parent.parent/'native/macos/ide_network.cjs';shutil.copy2(helper,target/NETWORK)
            sign_bundle(target,[])
            state=StateManager.load_state();state.setdefault('prepared_macos',{})[app]={'original':str(source),'bundle':str(target),'executable':str(target/source.relative_to(bundle)),'backends':{name:digest(target/name) for name in (BOOTSTRAP,NETWORK)},'auth_routing':True,'auth_capture':2,'ide_network':1}
            StateManager.save_state(state)
        except BaseException:shutil.rmtree(target.parent);raise
        return 'Antigravity IDE подготовлена: установка CLI и вход направлены через выбранный профиль, тайм-аут manifest увеличен до 30 секунд. Подпись копии проверена; оригинал не изменён. Запустите IDE через Dagami.'
