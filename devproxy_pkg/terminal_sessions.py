import concurrent.futures,ctypes,hmac,http.client,json,os,re,secrets,signal,struct,subprocess,sys,threading,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .core.recovery import StateManager
from .core.process_env import external_environment

ID=re.compile(r'cli_[0-9a-f]{32}')

def root():
    from .portable_runtime import runtime_dir
    path=runtime_dir()/'terminal';path.mkdir(mode=0o700,exist_ok=True)
    if path.is_symlink() or (os.name!='nt' and path.stat().st_uid!=os.getuid()):raise RuntimeError('Недопустимый каталог терминальных сессий.')
    return path

def stop_owned_process(process):
    if process.poll() is not None:return
    if os.name!='nt' and os.getpgid(process.pid)==process.pid:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL)
        return
    from .desktop_processes import inventory
    data=inventory();owned={process.pid};changed=True
    while changed:
        children={pid for pid,item in data.items() if item['parent'] in owned and item['uid']==os.getuid()}
        new=children-owned;owned|=new;changed=bool(new)
    for pid in reversed(sorted(owned)):
        before=data.get(pid);now=inventory().get(pid)
        if before and now and before==now and now['uid']==os.getuid():
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass
    if process.poll() is None:process.terminate()
    try:process.wait(timeout=3)
    except subprocess.TimeoutExpired:process.kill()

class TerminalSession:
    def __init__(self,app,profile,process,bridge,telemetry=None):
        from .portable_runtime import app_adapter
        self.application=app_adapter(app).display_name;self.telemetry=telemetry
        self.id='cli_'+uuid.uuid4().hex;self.app=app;self.profile=profile;self.process=process;self.bridge=bridge
        self.token=secrets.token_hex(32);self.server=None;self.thread=None;self.stopping=False;self.error='';self.path=None
    def status(self):
        running=self.process.poll() is None
        return {'id':self.id,'app':self.app,'application':self.application,'profile':self.profile,
            'pid':os.getpid(),'application_pids':[self.process.pid] if running else [],'bridge':self.bridge,
            'running':running,'stopping':self.stopping,'browser_running':False,'terminal':True,'canStop':True,'error':self.error,'telemetry':self.telemetry.snapshot() if self.telemetry else {}}
    def stop(self):
        try:stop_owned_process(self.process)
        except Exception as error:
            from .journal import clean,record_error
            self.error=clean(error);self.stopping=False;record_error('session:'+self.app,error)
    def start(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.connection.settimeout(3)
                if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+owner.token):self.send_error(403);return
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2048:raise ValueError('Некорректный запрос сессии.')
                    command=json.loads(self.rfile.read(length)).get('command')
                    if command not in ('status','stop'):raise ValueError('Неизвестная команда терминальной сессии.')
                    if command=='stop' and not owner.stopping:
                        owner.stopping=True;threading.Thread(target=owner.stop,daemon=True).start()
                    payload=json.dumps(owner.status()).encode();code=200
                except Exception:
                    payload=b'{"error":"Invalid session request"}';code=400
                self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        try:
            self.path=root()/(self.id+'.json')
            fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:json.dump({'port':self.server.server_port,'token':self.token,'pid':os.getpid(),'app':self.app,'profile':self.profile},stream)
            self.thread=threading.Thread(target=self.server.serve_forever,daemon=True,name='DagamiTerminalSession');self.thread.start()
            return self
        except BaseException:
            self.server.server_close()
            if self.path:self.path.unlink(missing_ok=True)
            raise
    def close(self):
        if self.server:
            if self.thread:self.server.shutdown();self.thread.join(timeout=2)
            self.server.server_close();self.server=None
        if self.path:self.path.unlink(missing_ok=True)
        if self.telemetry:self.telemetry.close()

def request(identifier,command='status',timeout=1.5):
    if not ID.fullmatch(identifier):raise ValueError('Некорректный идентификатор терминальной сессии.')
    path=root()/(identifier+'.json')
    if path.is_symlink():raise RuntimeError('Недопустимый дескриптор терминальной сессии.')
    try:record=json.loads(path.read_text())
    except FileNotFoundError:return None
    if type(record.get('port')) is not int or not 1<=record['port']<=65535 or not re.fullmatch('[0-9a-f]{64}',record.get('token','')):raise RuntimeError('Повреждён дескриптор терминальной сессии.')
    client=http.client.HTTPConnection('127.0.0.1',record['port'],timeout=timeout)
    try:
        client.request('POST','/',json.dumps({'command':command}),{'Authorization':'Bearer '+record['token'],'Content-Type':'application/json'})
        reply=client.getresponse();data=json.loads(reply.read(32768))
        if reply.status!=200:raise RuntimeError('Терминальная сессия отклонила запрос.')
        return data
    except (ConnectionRefusedError,ConnectionResetError,TimeoutError,OSError):
        if command!='status':raise RuntimeError('Сессия не подтвердила остановку. Обновите её состояние.') from None
        try:os.kill(record['pid'],0)
        except (ProcessLookupError,KeyError):return None
        return {'id':identifier,'app':record.get('app',''),'application':record.get('app','CLI'),'profile':record.get('profile',''),
            'pid':record['pid'],'application_pids':[],'running':False,'stopping':False,'bridge':'','terminal':True,'canStop':True,'error':'Контроллер терминала пока не отвечает.'}
    finally:client.close()

def list_sessions():
    paths=[path for path in root().glob('cli_*.json') if ID.fullmatch(path.stem) and not path.is_symlink()]
    def inspect(path):
        try:return request(path.stem)
        except Exception:return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:return [row for row in pool.map(inspect,paths) if row]

def process_arguments(pid):
    if sys.platform!='darwin':return []
    libc=ctypes.CDLL(None,use_errno=True);mib=(ctypes.c_int*3)(1,49,pid);length=ctypes.c_size_t(1024*1024);buffer=ctypes.create_string_buffer(length.value)
    if libc.sysctl(mib,3,buffer,ctypes.byref(length),None,0):return []
    raw=buffer.raw[:length.value]
    if len(raw)<4:return []
    count=struct.unpack_from('i',raw)[0]
    if not 0<count<4096:return []
    index=raw.find(b'\0',4)+1
    if index<=0:return []
    while index<len(raw) and raw[index]==0:index+=1
    return [value.decode('utf-8','surrogateescape') for value in raw[index:].split(b'\0',count)[:count]]

def legacy_sessions(excluded=()):
    if sys.platform!='darwin':return []
    from .adapters import list_adapters
    apps={a.app_id:a.display_name for a in list_adapters() if a.is_cli};profiles=StateManager.list_profiles();result=[]
    listing=subprocess.run(['ps','-axo','pid=,uid=,args='],capture_output=True,text=True,timeout=3,check=True,env=external_environment()).stdout
    for line in listing.splitlines():
        fields=line.strip().split(None,2)
        if len(fields)!=3 or not fields[0].isdigit() or not fields[1].isdigit():continue
        pid=int(fields[0])
        if pid in excluded or int(fields[1])!=os.getuid() or 'devproxy_gui.py' not in fields[2] or ' run ' not in fields[2]:continue
        args=process_arguments(pid)
        for index,value in enumerate(args):
            if Path(value).name!='devproxy_gui.py' or index+4>=len(args) or args[index+1]!='run':continue
            app=args[index+2]
            if app not in apps or args[index+3]!='--profile' or args[index+4] not in profiles:continue
            result.append({'id':'legacy_cli_'+str(pid),'app':app,'application':apps[app],'profile':args[index+4],
                'pid':pid,'application_pids':[],'bridge':'','running':True,'stopping':False,'terminal':True,'canStop':False,
                'notice':'Запущено до обновления. Перезапустите CLI через Dagami, чтобы управлять остановкой.','error':''})
            break
    return result
