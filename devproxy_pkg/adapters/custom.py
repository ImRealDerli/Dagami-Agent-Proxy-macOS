
from pathlib import Path
import hashlib
import os
import plistlib
from .cli_tools import CliToolAdapter
from ..core.recovery import StateManager


class CustomAdapter(CliToolAdapter):
    def __init__(self,app,record):
        super().__init__(app,record['name'],record['path'])
        self.record=record;self.is_cli=record.get('cli',False)
    def get_cli_launch_flags(self,profile):
        if not self.is_cli:
            path=Path(self.record['path']);bundle=next((p for p in path.parents if p.suffix=='.app'),None)
            if bundle and any((bundle/'Contents/Resources'/name).is_file() for name in ('app.asar','app/product.json')):
                return ['--proxy-server={PROXY_URL}','--disable-quic','--proxy-bypass-list=localhost;127.0.0.1;[::1]']
        return super().get_cli_launch_flags(profile)

    def detect_executable(self):
        return self.record['path'] if Path(self.record['path']).is_file() else None


def adapters():
    return [CustomAdapter(app,record) for app,record in StateManager.load_state().get('custom_apps',{}).items()]


def add(path,is_cli=False):
    path=Path(path).expanduser().resolve();name=path.stem
    if path.suffix=='.app' and path.is_dir():
        info=plistlib.loads((path/'Contents'/'Info.plist').read_bytes())
        exe=info.get('CFBundleExecutable','')
        if not exe or Path(exe).name!=exe:raise ValueError('Некорректный bundle macOS.')
        path=path/'Contents'/'MacOS'/exe;is_cli=False
    if not path.is_file() or not os.access(path,os.X_OK):raise ValueError('Выберите исполняемый файл или .app.')
    from .antigravity_ide import AntigravityIDEAdapter
    if not is_cli and AntigravityIDEAdapter.identify(path):
        from ..portable_runtime import register_executable
        register_executable('antigravity-ide',str(path));return 'antigravity-ide'
    from . import list_adapters
    from ..portable_runtime import executable
    for adapter in list_adapters():
        try:
            if Path(executable(adapter)).resolve()==path:return adapter.app_id
        except RuntimeError:pass
    app='custom_'+hashlib.sha256(str(path).encode()).hexdigest()[:16]
    state=StateManager.load_state();state.setdefault('custom_apps',{})[app]={'name':name,'path':str(path),'cli':bool(is_cli)}
    StateManager.save_state(state);return app


def remove(app):
    from ..portable_runtime import request
    from ..portable_shortcuts import PortableShortcuts
    if request(app) or PortableShortcuts().status(app)['files'] or StateManager.get_applied_record(app):
        raise RuntimeError('Сначала остановите сессию и отмените подготовку приложения.')
    state=StateManager.load_state()
    if app not in state.get('custom_apps',{}):raise ValueError('Удалять можно только добавленные вручную приложения.')
    del state['custom_apps'][app];state.get('executables',{}).pop(app,None);StateManager.save_state(state)
