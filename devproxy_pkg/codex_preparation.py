from .portable_shortcuts import PortableShortcuts
from .portable_runtime import app_adapter,executable,require_stopped,request
from .core.recovery import StateManager


def status(app):
    if app not in ('codex','codex-gui'):return False
    value=PortableShortcuts().status(app)
    return bool(value['enabled'])


def prepare(app,profile):
    if app not in ('codex','codex-gui'):raise ValueError('Неподдерживаемая интеграция Codex.')
    require_stopped(executable(app_adapter(app)))
    if request(app):raise ValueError('Остановите управляемую сессию Codex перед подготовкой.')
    links=PortableShortcuts();current=links.status(app)
    if current['changed']:raise ValueError('Подготовленный запуск изменён. Сначала выполните откат.')
    if current['enabled']:
        if current['profile']!=profile:raise ValueError('Для другого профиля сначала выполните откат.')
        return 'Codex уже подготовлен для выбранного профиля.'
    links.enable(app,profile)
    return 'Codex подготовлен: создан обратимый запуск с прокси-окружением и выбранным профилем. Для входа откройте «Авторизация → Codex». Учётные данные, sandbox и ограничения сервиса не изменялись.'


def restore(app):
    if request(app):raise ValueError('Сначала остановите управляемую сессию Codex.')
    PortableShortcuts().restore(app)
    return 'Подготовка Codex отменена. Аккаунт и настройки Codex сохранены.'
