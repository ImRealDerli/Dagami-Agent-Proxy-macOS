import shutil
from pathlib import Path
from .core.recovery import StateManager
from .macos_backend import managed_root,record,checked_executable,codesign
from .portable_runtime import request,require_stopped,session_lock


def owned_directory(item):
    bundle=Path(item['bundle']);root=managed_root().resolve()
    if bundle.is_symlink() or not bundle.resolve().is_relative_to(root) or bundle.parent.resolve()==root:
        raise ValueError('Недопустимый путь подготовленной IDE. Файлы не изменены.')
    return bundle.parent


def repair(app):
    if app not in ('antigravity','antigravity-ide'):raise ValueError('Выберите Antigravity App или Antigravity IDE.')
    with session_lock('ide-repair'):
        if request(app):raise RuntimeError('Сначала закройте процессы IDE и остановите её управляемую сессию.')
        old=record(app);directory=owned_directory(old) if old else None
        state=StateManager.load_state();previous=state.get('executables',{}).get(app)
        if old:
            original=Path(old['original'])
            if not original.is_file():raise RuntimeError('Установленный оригинал IDE отсутствует. Укажите его расположение; повреждённая копия сохранена.')
            from .macos_architecture import require_compatible
            require_compatible(original)
            require_stopped(old['executable']);require_stopped(str(original))
            state.get('prepared_macos',{}).pop(app,None);state.setdefault('executables',{})[app]=str(original);StateManager.save_state(state)
        try:
            if app=='antigravity-ide':
                from .ide_preparation import prepare
                prepare()
            else:
                from .macos_backend import prepare
                prepare(app)
            checked_executable(app)
            current=record(app);codesign(current['bundle'],'--verify','--deep','--strict')
        except BaseException:
            failed=record(app)
            state=StateManager.load_state();state.setdefault('prepared_macos',{}).pop(app,None)
            if old:state['prepared_macos'][app]=old
            if previous is None:state.get('executables',{}).pop(app,None)
            else:state.setdefault('executables',{})[app]=previous
            StateManager.save_state(state)
            if failed and failed!=old:
                shutil.rmtree(owned_directory(failed),ignore_errors=True)
            raise
        warning=''
        if directory and directory!=owned_directory(current):
            try:shutil.rmtree(directory)
            except OSError:warning=' Старую копию не удалось удалить; новая подготовка действует.'
        return 'Подготовка IDE пересоздана. SHA-256 и строгая проверка подписи пройдены. Оригинал, настройки и аккаунты сохранены. Нажмите «Запустить». Доступность сервера и вход проверяются отдельно.'+warning
