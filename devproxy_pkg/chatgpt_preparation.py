from .portable_shortcuts import PortableShortcuts
from .portable_runtime import app_adapter,executable,require_stopped,request,load_profile


def status():return bool(PortableShortcuts().status('chatgpt')['enabled'])


def prepare(profile):
    adapter=app_adapter('chatgpt');path=executable(adapter)
    from .macos_architecture import require_compatible
    require_compatible(path)
    adapter.launch_flags(load_profile(profile),path)
    require_stopped(path)
    if request('chatgpt'):raise ValueError('Остановите управляемую сессию ChatGPT перед подготовкой.')
    links=PortableShortcuts();current=links.status('chatgpt')
    if current['changed']:raise ValueError('Ярлык ChatGPT изменён. Сначала выполните откат.')
    if current['enabled']:
        if current['profile']!=profile:raise ValueError('Для другого профиля сначала выполните откат.')
        return 'ChatGPT уже подготовлен для выбранного профиля.'
    links.enable('chatgpt',profile)
    return 'ChatGPT подготовлен: создан обратимый запуск через выбранный профиль Dagami. Запускайте кнопкой «Запустить» или созданным ярлыком. Оригинал, подпись и аккаунт ChatGPT сохранены.'


def restore():
    if request('chatgpt'):raise ValueError('Сначала остановите управляемую сессию ChatGPT.')
    PortableShortcuts().restore('chatgpt')
    return 'Подготовка запуска ChatGPT отменена. Аккаунт и настройки сохранены.'
