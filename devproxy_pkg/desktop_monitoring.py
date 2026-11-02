import json,os,shlex,sys,tempfile
from pathlib import Path
from .core.recovery import get_devproxy_state_path

GROUP='dagami-session-monitor'

def paths():return Path.home()/'.gemini/config/hooks.json',Path(get_devproxy_state_path()).parent/'desktop-monitor.json'

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError('Файл настроек является символической ссылкой.')
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.dagami-hooks-')
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
        os.replace(temp,path)
    finally:
        try:os.unlink(temp)
        except FileNotFoundError:pass

def installed():
    config,record=paths()
    try:
        meta=json.loads(record.read_text());data=json.loads(config.read_text())
        return data.get(GROUP)==meta.get('managed')
    except (OSError,ValueError,AttributeError):return False

def configure(enabled):
    config,record=paths();data=json.loads(config.read_text()) if config.exists() else {}
    if not isinstance(data,dict):raise ValueError('Неизвестный формат Antigravity hooks.json.')
    meta=json.loads(record.read_text()) if record.exists() else None
    if meta and GROUP in data and data[GROUP]!=meta.get('managed'):raise RuntimeError('Правило Dagami изменено вручную. Оно не было заменено.')
    if not meta and GROUP in data:raise RuntimeError('Уже есть правило с именем Dagami. Проверьте hooks.json.')
    if enabled:
        script=Path(__file__).resolve().parents[1]/'native/macos/session_status_hook.py'
        command=shlex.join([sys.executable,'-B','-I',str(script),'antigravity-desktop'])
        rule={}
        for event in ('SessionStart','PreInvocation','PostInvocation','PreToolUse','PostToolUse','Stop'):
            handler={'type':'command','command':command+' '+event,'timeout':2}
            rule[event]=[{'matcher':'.*','hooks':[handler]}] if event in ('PreToolUse','PostToolUse') else [handler]
        previous=dict(data);data[GROUP]=rule;atomic(config,data)
        try:atomic(record,{'managed':rule})
        except Exception:
            atomic(config,previous);raise
        return 'Активность Antigravity подключена через официальные hooks. Перезапустите App/IDE через Dagami. Тексты запросов не сохраняются.'
    if meta and data.get(GROUP)==meta.get('managed'):
        del data[GROUP];atomic(config,data)
    record.unlink(missing_ok=True)
    return 'Активность Antigravity отключена.'
