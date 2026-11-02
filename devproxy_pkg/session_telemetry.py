import datetime,json,math,os,re,secrets,shlex,sys,tempfile,time,subprocess,shutil
try:import fcntl
except ImportError:fcntl=None
from pathlib import Path
from .core.recovery import StateManager

STATES={'idle','working','tool_use','reviewing','authenticating','initializing','error','permission','unknown'}
EVENTS={'PreInvocation':'working','PostInvocation':'working','SessionStart':'idle','UserPromptSubmit':'working','PreToolUse':'tool_use','PostToolUse':'working','PermissionRequest':'permission','Stop':'idle','Interrupt':'idle','SessionEnd':'idle'}

def enabled():return StateManager.load_state().get('session_monitoring',True) is True

def root():
    from .portable_runtime import runtime_dir
    path=runtime_dir()/'telemetry';path.mkdir(exist_ok=True,mode=0o700)
    if path.is_symlink() or path.stat().st_uid!=os.getuid():raise ValueError('Недопустимый каталог статистики.')
    return path

def number(value,low=0,high=100):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:return None
    return float(value)

def text(value):
    if not isinstance(value,str):return ''
    return ''.join(c for c in value if c.isprintable())[:80]

def timestamp(value):
    if isinstance(value,str):
        try:value=datetime.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
        except ValueError:return None
    return number(value,0,4102444800)

def clean_status(app,payload,event='status'):
    if not isinstance(payload,dict):return {}
    result={'updatedAt':time.time(),'source':'Официальные события клиента'}
    if event!='status':
        if event not in EVENTS:return {}
        result['state']=EVENTS[event];result['activityAt']=time.time()
        if payload.get('modelName'):result['model']=text(payload['modelName'])
        return result
    model=payload.get('model')
    if isinstance(model,dict):result['model']=text(model.get('display_name') or model.get('id'))
    context=payload.get('context_window')
    if isinstance(context,dict):
        percent=number(context.get('used_percentage'))
        if percent is not None:result['contextUsed']=percent
    quotas=[]
    if app=='agy':
        state=payload.get('agent_state','unknown')
        result['state']='permission' if payload.get('tool_confirmation_pending') is True else (state if state in STATES else 'unknown')
        result['activityAt']=time.time()
        buckets=payload.get('quota',{})
        if isinstance(buckets,dict):
            for key,value in list(buckets.items())[:16]:
                if not isinstance(value,dict):continue
                fraction=number(value.get('remaining_fraction'),0,1)
                amount=number(value.get('remaining_amount'),0,1e15)
                row={'id':text(key),'label':text(key),'resetAt':timestamp(value.get('reset_time')),'disabled':value.get('disabled') is True}
                if fraction is not None:row['usedPercent']=round((1-fraction)*100,2)
                elif amount is not None:row['remainingAmount']=amount
                quotas.append(row)
    elif app=='claude':
        rate=payload.get('rate_limits',{})
        if isinstance(rate,dict):
            for key,label in [('five_hour','5 часов'),('seven_day','7 дней'),('spend_limit','Лимит расходов')]:
                value=rate.get(key)
                if not isinstance(value,dict):continue
                percent=number(value.get('used_percentage'))
                if percent is not None:quotas.append({'id':key,'label':label,'usedPercent':percent,'resetAt':timestamp(value.get('resets_at')),'disabled':False})
    if app in ('agy','claude'):result['quotas']=quotas
    return result

def validate_path(path):
    path=Path(path)
    if path.parent.resolve()!=root().resolve() or not re.fullmatch('[a-f0-9]{32}\\.json',path.name) or path.is_symlink():raise ValueError('Недопустимый файл статистики.')
    return path

def read(path):
    path=validate_path(path)
    try:
        if path.stat().st_size>65536:return {}
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (FileNotFoundError,ValueError):return {}

def write(path,update):
    path=validate_path(path)
    fd=os.open(path.with_suffix('.lock'),os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=read(path);data.update(update)
        handle,temp=tempfile.mkstemp(prefix='.status-',dir=path.parent)
        try:
            with os.fdopen(handle,'w') as stream:json.dump(data,stream,ensure_ascii=False)
            os.replace(temp,path)
        finally:
            try:os.unlink(temp)
            except FileNotFoundError:pass

def receive(app,event,payload,path):
    if not enabled():return
    update=clean_status(app,payload,event)
    if update:write(path,update)

class Telemetry:
    def __init__(self,app,executable):
        self.app=app;self.path=None;self.flags=[];self.environment={};self.note='';self.plugin=None
        if sys.platform!='darwin' or not enabled() or app not in ('agy','claude','codex','antigravity','antigravity-ide'):return
        if app in ('agy','claude','codex'):
            try:
                result=subprocess.run([executable,'--help'],capture_output=True,text=True,timeout=3)
                help=(result.stdout or '')+'\n'+(getattr(result,'stderr','') or '')
            except (OSError,subprocess.SubprocessError):help=''
            if (app in ('agy','claude') and '--settings' not in help) or (app=='codex' and '--dangerously-bypass-hook-trust' not in help):
                self.note='Установленный клиент не объявляет поддержку интеграции событий. Лимиты доступны через родную панель.';return
        self.path=root()/(secrets.token_hex(16)+'.json')
        self.environment={'DAGAMI_SESSION_STATUS_PATH':str(self.path)}
        script=Path(__file__).resolve().parents[1]/'native/macos/session_status_hook.py'
        command=shlex.join([sys.executable,'-B','-I',str(script),app])
        if app in ('antigravity','antigravity-ide'):
            self.note='Для активности подключите официальные hooks Antigravity и перезапустите приложение.'
        elif app in ('agy','claude'):
            settings={'statusLine':{'type':'command','command':command+' status'}}
            if app=='agy':settings['statusLine'].update(stack_with_default=True,enabled=True)
            else:
                if '--plugin-dir' in help:
                    self.plugin=root()/(self.path.stem+'-plugin');self.plugin.mkdir(mode=0o700)
                    (self.plugin/'.claude-plugin').mkdir();(self.plugin/'hooks').mkdir()
                    (self.plugin/'.claude-plugin/plugin.json').write_text(json.dumps({'name':'dagami-session-monitor','version':'0.1.0','description':'Local session state only; no prompt or output retention'}))
                    hooks={event:[{'matcher':'','hooks':[{'type':'command','command':command+' '+event,'timeout':2}]}] for event in ('UserPromptSubmit','PreToolUse','PostToolUse','PermissionRequest','Stop')}
                    (self.plugin/'hooks/hooks.json').write_text(json.dumps({'hooks':hooks}))
            self.flags=['--settings',json.dumps(settings,separators=(',',':'))]
            if self.plugin:self.flags+=['--plugin-dir',str(self.plugin)]
            self.note='Статистика из официальной status line клиента. Личные настройки на диске не меняются.'
        else:
            for event in ('UserPromptSubmit','PreToolUse','PostToolUse','PermissionRequest','Stop','Interrupt'):
                value='[{hooks=[{type="command",command='+json.dumps(command+' '+event)+',timeout=2}]}]'
                self.flags+=['-c','hooks.'+event+'='+value]
            self.note='Для активности откройте /hooks в Codex и разрешите hook Dagami. Отказ не мешает работе CLI.'
    def snapshot(self):
        if not enabled():return {}
        if not self.path:return {'note':self.note} if self.note else {}
        raw=read(self.path);result={'source':'Официальные события клиента'}
        if raw.get('state') in STATES:result['state']=raw['state']
        for key in ('updatedAt','activityAt'):
            value=timestamp(raw.get(key))
            if value is not None:result[key]=value
        if raw.get('model'):result['model']=text(raw['model'])
        value=number(raw.get('contextUsed'))
        if value is not None:result['contextUsed']=value
        quotas=raw.get('quotas',[]);result['quotas']=[]
        if isinstance(quotas,list):
            for item in quotas[:32]:
                if not isinstance(item,dict):continue
                row={'id':text(item.get('id')),'label':text(item.get('label')),'resetAt':timestamp(item.get('resetAt')),'disabled':item.get('disabled') is True}
                used=number(item.get('usedPercent'));amount=number(item.get('remainingAmount'),0,1e15)
                if used is not None:row['usedPercent']=used
                if amount is not None:row['remainingAmount']=amount
                result['quotas'].append(row)
        result['note']=self.note
        if result.get('activityAt') and time.time()-result['activityAt']>300:result['state']='unknown'
        return result
    def close(self):
        if self.plugin and self.plugin.is_dir():shutil.rmtree(self.plugin)
        if self.path:
            self.path.unlink(missing_ok=True);self.path.with_suffix('.lock').unlink(missing_ok=True)
