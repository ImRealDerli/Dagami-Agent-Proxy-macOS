from pathlib import Path
import json,datetime,os,re,traceback,subprocess,threading
from urllib.parse import urlsplit,urlunsplit
from .core.recovery import get_devproxy_state_path
from .portable_runtime import redact

_secrets=set()
_secret_lock=threading.Lock()

def register_secret(value):
    if isinstance(value,str) and len(value)>=8:
        with _secret_lock:
            if len(_secrets)>=256:_secrets.clear()
            _secrets.add(value)


def location():
    root=Path(get_devproxy_state_path()).parent/'journal'
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    return root/'events.jsonl'

def clean(value,limit=4000):
    value=redact(str(value))
    with _secret_lock:
        for secret in _secrets:value=value.replace(secret,"[секрет скрыт]")
    def safe_url(match):
        raw=match.group()
        try:
            parsed=urlsplit(raw);host=parsed.hostname or ''
            if parsed.port:host+=':'+str(parsed.port)
            if parsed.username or parsed.password:host='***@'+host
            return urlunsplit((parsed.scheme,host,parsed.path,'[параметры скрыты]' if parsed.query else '','[фрагмент скрыт]' if parsed.fragment else ''))
        except ValueError:return '[URL скрыт]'
    value=re.sub(r'https?://[^\s<>"\']+',safe_url,value,flags=re.I)
    value=re.sub(r'(?i)(?:Bearer|Basic)\s+[A-Za-z0-9_+/=.-]+','[данные авторизации скрыты]',value)
    value=re.sub(r"(?i)(\b(?:password|proxy_password|access_token|refresh_token|api_key|secret)\b[\"']?\s*[:=]\s*)([\"'])(?:\\.|(?!\2).)*\2",r'\1[секрет скрыт]',value)
    value=re.sub(r"(?i)\b(?:access_token|refresh_token|id_token|authorization_code|auth_code|code|state|sidt|code_verifier|password|api_key|secret|license_key)\b[\"']?\s*[:=]\s*[\"']?[^\s\"',;}]+",'[секрет скрыт]',value)
    value=re.sub(r"(?i)((?:--(?:password|proxy-user|proxy-password|api-key|api_key|token|access-token|key|secret)|-w)[\"',\s=]+)[^\s\"',]+",r'\1[скрыто]',value)
    value=re.sub(r'\b4/[A-Za-z0-9._~+/-]{20,}','[код скрыт]',value)
    value=re.sub(r'\bDAGAMI-[A-Za-z0-9-]{8,}\b','[ключ скрыт]',value)
    return value if limit is None else value[:limit]


def record_error(action,error):
    parts=[''.join(traceback.format_exception(type(error),error,error.__traceback__))]
    current=error;seen=set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current,(subprocess.CalledProcessError,subprocess.TimeoutExpired)):
            parts.append('Команда: '+repr(current.cmd))
            if hasattr(current,'returncode'):parts.append('Код выхода: '+str(current.returncode))
            for name in ('stdout','stderr'):
                value=getattr(current,name,None)
                if value:
                    if isinstance(value,bytes):value=value.decode('utf-8','replace')
                    parts.append(name+':\n'+value)
        current=current.__cause__ or current.__context__
    append(action,False,'\n'.join(parts),detail=True)

def append(action,success,message='',detail=False):
    if success and action in ('snapshot','journal','loginURL','authStatus','updateAck'):return
    path=location()
    if path.is_symlink():raise RuntimeError('Недопустимый путь журнала.')
    if path.exists() and path.stat().st_size>2*1024*1024:
        old=path.with_suffix('.previous');old.unlink(missing_ok=True);path.replace(old)
    entry={'time':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'action':action,'success':bool(success),'message':clean(message,limit=None) if detail else clean(message) if not action.startswith('auth') and action not in ('activate','licenseReset','saveProxy','login') else ('Готово' if success else 'Операция не завершена')}
    with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(entry,ensure_ascii=False)+'\n')
    path.chmod(0o600)

def read():
    path=location()
    if not path.exists():return 'Журнал пока пуст.'
    lines=path.read_text(encoding='utf-8',errors='replace').splitlines()[-250:]
    result=[]
    for line in reversed(lines):
        try:
            item=json.loads(line);result.append(item['time']+'  '+('✓ ' if item['success'] else '✕ ')+item['action']+'\n'+item.get('message',''))
        except (ValueError,KeyError):continue
    return '\n\n'.join(result) or 'Журнал пока пуст.'
