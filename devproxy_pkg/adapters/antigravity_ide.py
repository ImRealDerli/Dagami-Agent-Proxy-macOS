import os,plistlib,subprocess,sys
from pathlib import Path
from .antigravity import AntigravityAdapter
from ..core.recovery import StateManager
from ..core.process_env import external_environment


class AntigravityIDEAdapter(AntigravityAdapter):
    app_id='antigravity-ide'
    display_name='Google Antigravity IDE'

    @staticmethod
    def identify(path):
        path=Path(path).expanduser()
        bundle=path if path.suffix=='.app' else next((p for p in path.parents if p.suffix=='.app'),None)
        if bundle is None:return None
        try:
            info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes());name=info.get('CFBundleExecutable','')
            if info.get('CFBundleIdentifier')!='com.google.antigravity-ide' or not name or Path(name).name!=name:return None
            executable=bundle/'Contents/MacOS'/name
            if not executable.is_file() or not os.access(executable,os.X_OK):return None
            if path!=bundle and path.resolve()!=executable.resolve():return None
            return str(executable)
        except (OSError,ValueError,plistlib.InvalidFileException):return None

    def detect_executable(self):
        if sys.platform!='darwin':return None
        candidates=[Path('/Applications/Antigravity IDE.app'),Path.home()/'Applications/Antigravity IDE.app']
        candidates.extend(Path(v['path']) for v in StateManager.load_state().get('custom_apps',{}).values() if v.get('path') and not v.get('cli'))
        for path in candidates:
            executable=self.identify(path)
            if executable:return executable
        try:
            result=subprocess.run(['/usr/bin/mdfind',"kMDItemCFBundleIdentifier == 'com.google.antigravity-ide'"],capture_output=True,text=True,timeout=3,check=True,env=external_environment())
            for path in result.stdout.splitlines()[:64]:
                executable=self.identify(path)
                if executable:return executable
        except (OSError,subprocess.SubprocessError):pass
        return None

    def detect_config_files(self):return [str(Path.home()/'Library/Application Support/Antigravity IDE/User/settings.json')]
    def get_launch_environment(self,local_proxy,executable=''):
        return dict(super().get_launch_environment(local_proxy,executable),DAGAMI_IDE_PROXY=local_proxy)
