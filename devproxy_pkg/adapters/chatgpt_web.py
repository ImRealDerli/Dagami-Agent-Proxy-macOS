import hashlib,os
from pathlib import Path
from .base import ApplicationAdapter
from ..macos_architecture import compatibility_error
from ..core.recovery import get_devproxy_state_path


class ChatGPTWebAdapter(ApplicationAdapter):
    app_id='chatgpt-web'
    display_name='ChatGPT — веб-версия'
    supported_os=['darwin']
    isolated_browser=True

    def detect_executable(self):
        browsers=(('Google Chrome','Google Chrome'),('Microsoft Edge','Microsoft Edge'),('Brave Browser','Brave Browser'),('Chromium','Chromium'))
        for root in (Path('/Applications'),Path.home()/'Applications'):
            for bundle,binary in browsers:
                path=root/(bundle+'.app')/'Contents/MacOS'/binary
                if path.is_file() and os.access(path,os.X_OK) and not compatibility_error(path):return str(path)
        return None

    def detect_config_files(self):return []
    def get_cli_launch_flags(self,profile):return self.launch_flags(profile)

    def launch_flags(self,profile,executable=None):
        root=Path(get_devproxy_state_path()).parent/'web-chatgpt';directory=root/hashlib.sha256(profile.name.encode()).hexdigest()[:24]
        if root.is_symlink() or directory.is_symlink():raise RuntimeError('Каталог браузера не должен быть символической ссылкой.')
        directory.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700);directory.chmod(0o700)
        return ['--proxy-server={PROXY_URL}','--proxy-bypass-list=localhost;127.0.0.1;[::1]','--disable-quic','--no-first-run','--no-default-browser-check','--user-data-dir='+str(directory),'--app=https://chatgpt.com/']

    def apply_persistent(self,profile):return False,'Для веб-версии используйте запуск через Dagami.'
    def restore_persistent(self):return False,'Оригинальное приложение и обычный браузер не изменялись.'
    def get_limitations(self):return ['Веб-версия ChatGPT в отдельном окне Chromium через выбранный профиль.','Данные входа сохраняются отдельно для каждого профиля Dagami. Обычные окна браузера не закрываются.','Функции нативного приложения доступны только в совместимом приложении. Доступность аккаунта проверяется отдельно.']
