
from .core.recovery import StateManager
from .core.secrets import SecretStore, EphemeralStore


def update_credentials(name, username, password):
    if not username or not password:
        raise ValueError('Введите логин и пароль, выданные провайдером прокси.')
    if ':' in username or '\x00' in username or '\x00' in password:
        raise ValueError('Логин Basic не должен содержать двоеточие или NUL.')
    old=StateManager.get_profile(name)
    if not old or old.get('protocol')=='direct':
        raise ValueError('Выберите существующий профиль upstream-прокси.')
    previous=SecretStore.get_password(name)
    if old.get('requires_password') and previous is None:
        raise RuntimeError('Предыдущий пароль недоступен. Разблокируйте Keychain перед изменением.')
    updated=dict(old,username=username,requires_password=True)
    updated.pop('password',None)
    try:
        if SecretStore.store_password(name,username,password)!='os_keychain':
            EphemeralStore.delete(name)
            raise RuntimeError('Пароль не записан в Keychain. Профиль не изменён.')
        StateManager.save_profile(updated)
    except Exception:
        EphemeralStore.delete(name)
        if previous is not None:
            if SecretStore.store_password(name,old.get('username') or '',previous)!='os_keychain':
                EphemeralStore.delete(name)
                raise RuntimeError('Не удалось сохранить профиль и восстановить прежний пароль. Разблокируйте Keychain и повторно задайте реквизиты.') from None
        else:
            SecretStore.delete_password(name)
        raise
    return 'Логин и пароль обновлены. Нажмите «Проверить» и заново запустите приложение.'
