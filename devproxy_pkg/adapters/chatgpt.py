import os,plistlib,subprocess,sys
from pathlib import Path
from .base import ApplicationAdapter
from ..core.process_env import external_environment


class ChatGPTAdapter(ApplicationAdapter):
    app_id='chatgpt'
    display_name='ChatGPT Desktop'
    supported_os=['darwin']

    @staticmethod
    def bundle_executable(bundle):
        bundle=Path(bundle)
        try:
            info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
            name=info.get('CFBundleExecutable','')
            if info.get('CFBundleIdentifier') not in ('com.openai.chat','com.openai.chatgpt','com.openai.ChatGPT','com.openai.codex'):return None
            if not name or Path(name).name!=name:return None
            if info.get('CFBundleIdentifier')=='com.openai.codex' and name!='ChatGPT':return None
            path=bundle/'Contents/MacOS'/name
            return str(path) if path.is_file() and os.access(path,os.X_OK) else None
        except (OSError,ValueError,plistlib.InvalidFileException):return None

    def detect_executable(self):
        if sys.platform!='darwin':return None
        candidates=[Path('/Applications/ChatGPT.app'),Path.home()/'Applications/ChatGPT.app']
        for bundle in candidates:
            path=self.bundle_executable(bundle)
            if path:return path
        try:
            result=subprocess.run(['/usr/bin/mdfind',"kMDItemFSName == 'ChatGPT.app'"],capture_output=True,text=True,timeout=3,check=True,env=external_environment())
            for line in result.stdout.splitlines()[:64]:
                bundle=Path(line)
                if bundle.is_absolute() and bundle.suffix=='.app':
                    path=self.bundle_executable(bundle)
                    if path:return path
        except (OSError,subprocess.SubprocessError):pass
        return None

    @staticmethod
    def is_electron(executable):
        if not executable:return False
        bundle=next((p for p in Path(executable).parents if p.suffix=='.app'),None)
        if not bundle or not (bundle/'Contents/Resources/app.asar').is_file():return False
        return any((bundle/'Contents/Frameworks'/name).is_dir() for name in ('Electron Framework.framework','ChatGPT Framework.framework','Codex Framework.framework'))

    def detect_config_files(self):return []
    def get_cli_launch_flags(self,profile):return self.launch_flags(profile,self.detect_executable())

    def launch_flags(self,profile,executable=None):
        if self.is_electron(executable):
            return ['--proxy-server={PROXY_URL}','--proxy-bypass-list=localhost;127.0.0.1;[::1]','--disable-quic']
        if profile.proxy_enabled and profile.protocol!='direct':
            raise RuntimeError('Эта версия ChatGPT использует нативную сеть macOS. Прокси-флаги Electron для неё не подходят. Используйте профиль DNS-only с настроенным системным DNS; прокси-патч для этой версии не применяется.')
        return []

    def apply_persistent(self,profile):return False,'Используйте кнопку «Патч»: создаётся обратимый запуск ChatGPT через Dagami.'
    def restore_persistent(self):return False,'Настройки и бинарные файлы ChatGPT не изменялись.'
    def get_limitations(self):return ['Для версии Electron используется локальный мост с прокси-флагами и окружением backend.','Нативные версии ChatGPT требуют отдельного сетевого адаптера для upstream-прокси; для DNS-only нужен системный DNS.','Старые процессы нужно закрыть перед запуском. Доступность аккаунта и сервиса проверяется отдельно.']
