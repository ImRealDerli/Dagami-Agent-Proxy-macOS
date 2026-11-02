from pathlib import Path
from .macos_backend import record,managed_root,checked_executable
from .portable_shortcuts import PortableShortcuts


def inspect(app):
    try:
        if app in ('codex','codex-gui','chatgpt'):
            status=PortableShortcuts().status(app)
            if status['changed']:return {'prepared':False,'recoverable':True,'error':'Подготовленный запуск изменён или отсутствует. Выполните откат перед повторной подготовкой.'}
            return {'prepared':status['enabled'],'recoverable':False,'error':''}
        value=record(app)
        if value is None:return {'prepared':False,'recoverable':False,'error':''}
        if not isinstance(value,dict) or not isinstance(value.get('backends'),dict):raise ValueError('Повреждена запись подготовки.')
        checked_executable(app,verify=False)
        return {'prepared':True,'recoverable':False,'error':''}
    except Exception:
        return {'prepared':False,'recoverable':True,'error':'Подготовка повреждена или недоступна. Откат и ремонт доступны; запуск требует восстановления.'}
