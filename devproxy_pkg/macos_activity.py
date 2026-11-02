import concurrent.futures
import json
from urllib.parse import urlsplit
from . import journal
from .adapters import list_adapters
from .portable_runtime import request, runtime_dir

TITLES={
 'sessionQuota':'Чтение лимитов','sessionMonitoring':'Статистика сессий','desktopMonitoring':'Активность Antigravity',
 'profileSave':'Сохранение профиля','profileDelete':'Удаление профиля','profileDetails':'Загрузка настроек профиля',
 'launch':'Запуск приложения','stop':'Остановка сессии','check':'Проверка подключения','checkConnection':'Проверка подключения',
 'prepare':'Применение патча','restore':'Откат патча','unpatch':'Отмена подготовки',
 'repairIDE':'Ремонт Antigravity IDE','prepareAuth':'Настройка входа в IDE',
 'appInspect':'Проверка открытых процессов','appClose':'Закрытие процессов',
 'saveDNS':'Сохранение DNS-профиля','saveProxy':'Сохранение прокси-профиля',
 'systemDNS':'Системный DNS','probeDNS':'Проверка DNS-серверов',
 'probeAuth':'Проверка маршрута входа','checkIDE':'Проверка сервера IDE',
 'authStart':'Начало входа','authStop':'Завершение входа','authOpen':'Открытие страницы входа',
 'authClipboard':'Подхват ссылки входа','authFind':'Поиск ссылки входа',
 'login':'Вход в аккаунт','activate':'Активация Dagami','licenseReset':'Сброс ключа',
 'updateCheck':'Проверка обновлений','updateInstall':'Установка обновления',
 'startup':'Автозапуск','shortcut':'Создание ярлыка','addApp':'Добавление приложения','removeApp':'Удаление приложения',
}

def entries():
    path=journal.location()
    if not path.exists():return []
    result=[]
    for index,line in reversed(list(enumerate(path.read_text(encoding='utf-8',errors='replace').splitlines()[-250:]))):
        try:
            item=json.loads(line)
            action=str(item['action']);success=bool(item['success'])
            detail=journal.clean(item.get('message',''),limit=None)
            lines=[s.strip() for s in detail.splitlines() if s.strip()]
            passed=sum(s.startswith('✓') for s in lines);failed=sum(s.startswith('✕') for s in lines)
            if action=='check' and passed+failed:
                success=success and not failed
                summary=f'Доступны сервисы: {passed} из {passed+failed}.'
            elif not success:
                lower=detail.lower()
                if '407' in lower:summary='Прокси отклонил авторизацию. Проверьте данные профиля.'
                elif 'codesign' in lower:summary='Проверка подписи приложения не прошла. Откройте подробности.'
                elif 'operation not permitted' in lower:summary='macOS запретила операцию. Проверьте доступ к файлу или папке.'
                elif 'timed out' in lower or 'timeout' in lower:summary='Не дождались ответа. Проверьте маршрут и повторите.'
                elif '502' in lower or '503' in lower:summary='Сервер или прокси временно недоступен.'
                else:summary=(lines[-1] if lines else 'Операция не завершена.')[:240]
            elif action=='launch':summary='Команда запуска отправлена. Состояние приложения — в разделе «Сессии».'
            elif action=='stop':summary='Запрошена остановка. Состояние обновится в разделе «Сессии».'
            else:summary=(lines[0] if lines and not lines[0].startswith(('{','[')) else 'Операция выполнена.')[:240]
            result.append({'id':str(index)+':'+str(item['time']),'time':str(item['time']),'action':action,
                'title':TITLES.get(action,'Сессия приложения' if action.startswith('session:') else action),
                'success':success,'summary':summary,'detail':detail})
        except (ValueError,KeyError,TypeError):continue
    return result

def sessions():
    root=runtime_dir()
    candidates=[a for a in list_adapters() if (root/(a.app_id+'.json')).is_file() and not (root/(a.app_id+'.json')).is_symlink()]
    def inspect(adapter):
        try:
            value=request(adapter.app_id,_timeout=1.5)
            if not value:return None
            bridge=str(value.get('bridge',''));url=urlsplit(bridge)
            if url.scheme!='http' or url.hostname!='127.0.0.1' or url.username or url.password:bridge=''
            pending=bool(value.get('stopping')) and not value.get('bridge')
            return {'id':adapter.app_id,'name':adapter.display_name,'profile':str(value.get('profile','')),
                'running':bool(value.get('running')),'browser':bool(value.get('browser_running')),
                'stopping':bool(value.get('stopping')) and not pending,'pid':value.get('pid') if type(value.get('pid')) is int else 0,
                'pids':[p for p in value.get('application_pids',[]) if type(p) is int],
                'telemetry':value.get('telemetry',{}),'bridge':bridge,'error':'Контроллер не ответил вовремя. Обновите статус через несколько секунд.' if pending else ''}
        except Exception as exc:
            return {'id':adapter.app_id,'name':adapter.display_name,'profile':'','running':False,'browser':False,
                'stopping':False,'pid':0,'pids':[],'bridge':'','error':journal.clean(str(exc),limit=400)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:result=[s for s in pool.map(inspect,candidates) if s]
    from .terminal_sessions import list_sessions,legacy_sessions
    terminals=list_sessions()
    terminals+=legacy_sessions({row.get('pid') for row in terminals})
    for row in terminals:
        result.append({'id':row['id'],'app':row.get('app'),'name':row.get('application','CLI'),'profile':row.get('profile',''),
            'running':bool(row.get('running')),'browser':False,'stopping':bool(row.get('stopping')),'pid':row.get('pid',0),
            'pids':row.get('application_pids',[]),'bridge':row.get('bridge',''),'error':row.get('error',''),
            'telemetry':row.get('telemetry',{}),'terminal':True,'canStop':row.get('canStop',True),'notice':row.get('notice','')})
    return result
