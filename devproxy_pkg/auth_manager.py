import html,http.client,hmac,json,os,pty,re,secrets,select,shlex,signal,struct,subprocess,sys,threading,time,termios,fcntl
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .portable_runtime import load_profile,runtime_dir,_browser,executable,app_adapter,request,start_session,process_alive,signal_group
from .core.tunnel import LocalTunnel
from .core.launcher import Launcher
from .auth_route import verify_route
from .core.process_env import external_environment

SERVICES={
 'codex':{'name':'Codex / ChatGPT','url':'https://chatgpt.com/auth/login','hosts':('auth.openai.com','chatgpt.com','accounts.google.com','login.microsoftonline.com')},
 'claude':{'name':'Claude / Claude Code','url':'https://claude.ai/login','hosts':('claude.ai','claude.com','console.anthropic.com','platform.claude.com','accounts.google.com')},
 'agy':{'name':'Antigravity CLI','url':'','hosts':('accounts.google.com',)},
 'gemini':{'name':'Gemini / Google AI','url':'https://gemini.google.com/','hosts':('accounts.google.com','gemini.google.com','aistudio.google.com')},
 'antigravity':{'name':'Antigravity IDE','url':'','hosts':('accounts.google.com','antigravity.google','antigravity.google.com','gemini.google.com','aistudio.google.com')},
 'deepseek':{'name':'DeepSeek','url':'https://chat.deepseek.com/','hosts':('chat.deepseek.com','accounts.google.com')},
 'qwen':{'name':'Qwen','url':'https://chat.qwen.ai/','hosts':('chat.qwen.ai','qwen.ai','accounts.google.com')},
 'grok':{'name':'Grok','url':'https://grok.com/','hosts':('grok.com','accounts.x.ai','accounts.google.com')},
 'perplexity':{'name':'Perplexity','url':'https://www.perplexity.ai/','hosts':('perplexity.ai','www.perplexity.ai','accounts.google.com')},
 'mistral':{'name':'Mistral','url':'https://chat.mistral.ai/','hosts':('chat.mistral.ai','auth.mistral.ai','accounts.google.com')},
 'copilot':{'name':'Microsoft Copilot','url':'https://copilot.microsoft.com/','hosts':('copilot.microsoft.com','login.microsoftonline.com','login.live.com')},
 'openrouter':{'name':'OpenRouter','url':'https://openrouter.ai/sign-in','hosts':('openrouter.ai','accounts.google.com')},
 'custom':{'name':'Другой ИИ — своя HTTPS-ссылка','url':'','hosts':()}
}

SERVICES['antigravity-ide']=dict(SERVICES['antigravity'],name='Antigravity IDE (VS Code)')

def validate_url(url,service,manual=False):
    if service not in SERVICES:raise ValueError('Неизвестный сервис авторизации.')
    if not isinstance(url,str) or len(url)>16384 or any(ord(c)<33 for c in url) or any(c in url for c in ('"',"'",'\\')):raise ValueError('Некорректная ссылка авторизации.')
    try:p=urlsplit(url);port=p.port
    except ValueError:raise ValueError('Некорректная ссылка авторизации.') from None
    if p.scheme!='https' or not p.hostname or p.username or p.password or port not in (None,443):raise ValueError('Нужна HTTPS-ссылка авторизации без реквизитов в адресе.')
    if service=='custom' and manual:
        import ipaddress
        try:
            if not ipaddress.ip_address(p.hostname).is_global:raise ValueError('Локальные адреса нельзя использовать для начальной страницы входа.')
        except ValueError as exc:
            if '.' not in p.hostname or p.hostname in ('localhost','localhost.localdomain') or str(exc).startswith('Локальные'):raise ValueError('Укажите публичный домен сервиса.') from None
    elif p.hostname not in SERVICES[service]['hosts']:raise ValueError('Домен ссылки не соответствует выбранному сервису.')
    return url


def validate_initial_auth_url(url):
    parsed=urlsplit(url)
    if parsed.hostname=='accounts.google.com' and parsed.path not in ('/o/oauth2/auth','/o/oauth2/v2/auth'):
        raise ValueError('Это промежуточная страница Google. Нажмите «Войти» в клиенте заново. Для новой попытки нужна исходная OAuth-ссылка /o/oauth2/auth или /o/oauth2/v2/auth, а не адрес из уже открытого браузера.')
    return url


def validate_clipboard_url(url,service):
    validate_url(url,service)
    validate_initial_auth_url(url)
    p=urlsplit(url);query=parse_qs(p.query)
    if any(len(query.get(key,[]))!=1 or not query[key][0] for key in ('state','client_id')) or not any(word in p.path.lower() for word in ('auth','login','signin','authorize')):raise ValueError('В буфере нет полной ссылки OAuth с client_id и state.')
    redirect=query.get('redirect_uri',[])
    if len(redirect)!=1:raise ValueError('В ссылке OAuth отсутствует однозначный адрес возврата.')
    callback=urlsplit(redirect[0])
    if callback.username or callback.password:raise ValueError('Недопустимый адрес возврата OAuth.')
    hosted=service in ('agy','antigravity-ide') and callback.scheme=='https' and callback.hostname=='antigravity.google' and callback.port in (None,443) and callback.path=='/oauth-callback' and not callback.query and not callback.fragment
    if callback.scheme in ('http','https'):
        if callback.hostname not in ('localhost','127.0.0.1','::1') and not hosted:raise ValueError('Неподдерживаемый адрес возврата OAuth. Для Antigravity CLI разрешён также точный официальный https://antigravity.google/oauth-callback.')
    elif not (service in ('antigravity','antigravity-ide') and callback.scheme in ('antigravity','antigravity-ide')):raise ValueError('Неподдерживаемый адрес возврата OAuth.')
    return url


def auth_urls(text,service):
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    result=[]
    for raw in re.findall(r'https://[^\s<>"\x00\x1b]+',text):
        url=html.unescape(raw.rstrip("',);"))
        try:
            validate_url(url,service)
            validate_initial_auth_url(url)
            p=urlsplit(url);query=parse_qs(p.query)
            if not any(word in p.path.lower() for word in ('auth','oauth','login','signin','device','authorize')):continue
            if 'authorize' in p.path.lower() and not(query.get('state') and query.get('client_id')):continue
            if url not in result:result.append(url)
        except ValueError:continue
    return result


def find_link(service,home=None,now=None):
    home=Path(home or Path.home());now=now or time.time();roots=[home/'.codex/log',home/'.claude/logs',home/'.gemini/logs',home/'.agy/logs',home/'.local/state/opencode/log']
    for name in ('Antigravity','Antigravity IDE','Codex','Claude','Cursor','Windsurf','Code'):
        roots.extend([home/'Library/Application Support'/name/'logs',home/'Library/Logs'/name])
    files=[]
    for root in roots:
        if not root.is_dir() or root.is_symlink():continue
        for count,path in enumerate(root.rglob('*.log')):
            if count>=500:break
            try:
                if path.is_file() and not path.is_symlink() and now-600<=path.stat().st_mtime<=now+5:files.append(path)
            except OSError:continue
    for path in sorted(files,key=lambda p:p.stat().st_mtime,reverse=True)[:80]:
        try:
            with path.open('rb') as stream:
                stream.seek(max(0,path.stat().st_size-262144));links=auth_urls(stream.read(262144).decode('utf-8','replace'),service)
            if links:return links[-1]
        except OSError:continue
    return ''


class AuthSession:
    def __init__(self,service,profile,mode='browser',auto=True):
        if service not in SERVICES:raise ValueError('Неизвестный сервис.')
        self.service=service;self.profile=profile;self.mode=mode;self.auto=auto;self.url='';self.code='';self.message='Ожидается ссылка входа';self.closed=False;self.process=None;self.browser_processes=[];self.lock=threading.RLock();self.opened=set();self.capture=None;self.master=None;self.reader=None;self.created=time.monotonic();self.attached=False;self.retired=set();self.clipboard_seen=set()
        self.tunnel=LocalTunnel(load_profile(profile));self.local='http://127.0.0.1:'+str(self.tunnel.start())
        self.token=secrets.token_hex(32);self.hookdir=runtime_dir()/('auth-hook-'+secrets.token_hex(8));self.hookdir.mkdir(mode=0o700)
        self.env=external_environment({key:self.local for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')})
        self.env.update(NO_PROXY='localhost,127.0.0.1,::1',no_proxy='localhost,127.0.0.1,::1',AG_LS_PROXY=self.local,AGY_PROXY_URL=self.local,agy_proxy_url=self.local)
    def status(self):
        if self.attached and not self.closed:
            active=request(getattr(self,'attached_app','antigravity'),'authStatus')
            if active and active.get('url') and active['url']!=getattr(self,'initial_auth_url',''):self.url=active['url'];self.message='Ссылка открыта через маршрут Antigravity. Завершите вход в браузере.'
        return {'service':self.service,'profile':self.profile,'url':self.url,'code':self.code,'message':self.message,'running':not self.closed,'cli_running':self.process is not None and self.process.poll() is None}
    def check_route(self,url):
        try:verify_route(self.local,url,self.profile)
        except Exception as exc:self.message=str(exc);raise

    def open_url(self,url,manual=False):
        validate_url(url,self.service,manual)
        validate_initial_auth_url(url)
        with self.lock:
            if self.closed:raise ValueError('Сессия входа закрыта.')
            self.url=url
            if self.attached:
                self.check_route(url)
                active=request(getattr(self,'attached_app','antigravity'),'login',url=url)
                if not active:raise ValueError('Сессия Antigravity остановлена. Запустите вход заново.')
                self.message='Браузер открыт через тот же профиль, что и Antigravity.'
                return self.status()
            if not manual and url in self.opened and any(process_alive(p,self.retired) for p in self.browser_processes):return self.status()
            self.check_route(url)
            browser=_browser()
            import hashlib
            directory=getattr(self,'browser_directory',None) or runtime_dir()/('auth-browser-'+self.service+'-'+hashlib.sha256(self.profile.encode()).hexdigest()[:12]);directory.mkdir(mode=0o700,exist_ok=True)
            args=['--proxy-server='+self.local,'--proxy-bypass-list=localhost;127.0.0.1;[::1]','--disable-quic','--user-data-dir='+str(directory),url]
            env=dict(self.env);env['PATH']=os.environ.get('PATH','/usr/bin:/bin')
            if self.service=='agy' and callable(getattr(self,'code_callback',None)):
                from .selenium_code import SeleniumCodeBrowser
                existing=getattr(self,'code_browser',None)
                if existing and existing.process.poll() is None:existing.navigate(url);self.opened.add(url);return self.status()
                self.code_browser=SeleniumCodeBrowser(browser,args,env,url,self.code_callback,getattr(self,'code_error',None))
                proc=self.code_browser.process
            else:proc=Launcher.launch(browser,args,env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.browser_processes.append(proc)
            try:proc.wait(timeout=.3)
            except subprocess.TimeoutExpired:pass
            if proc.poll() not in (None,0):raise RuntimeError('Браузер не запустился (код '+str(proc.returncode)+'). Полностью закройте окно входа и повторите попытку.')
            self.opened.add(url);self.message='Браузер открыт через выбранный профиль. Завершите вход в окне сервиса.'
            return self.status()
    def clipboard_url(self,url):
        import hashlib
        validate_clipboard_url(url,self.service)
        key=hashlib.sha256(url.encode()).hexdigest()
        if key in self.clipboard_seen:return self.status()
        result=self.open_url(url,manual=True)
        self.clipboard_seen.add(key);return result

    def capture_url(self,url):
        validate_url(url,self.service)
        if self.service=='agy':
            from .cli_auth_runtime import complete_cli_oauth
            if not complete_cli_oauth(url):raise ValueError('CLI передал неполную OAuth-ссылку. Частичный client_id или отсутствующие параметры входа не открываются.')
        self.url=url;self.message='Свежая ссылка найдена'
        if self.auto:self.open_url(url)
    def attach_antigravity(self):
        if self.attached:return
        from .macos_backend import record
        self.attached_app='antigravity-ide' if self.service=='antigravity-ide' else 'antigravity'
        item=record(self.attached_app)
        if not item or not item.get('auth_routing') or item.get('auth_capture',0)<2:raise ValueError('Обновите подготовку Antigravity кнопкой «Настроить вход в IDE». Нужен перехват исходной ссылки непосредственно из backend, а не адреса из браузера.')
        active=start_session(self.attached_app,self.profile)
        if not active.get('auth_route'):raise ValueError('Старая сессия Antigravity ещё работает. Используйте «Настроить вход в IDE» для её перезапуска.')
        verify_route(active['bridge'],'https://accounts.google.com/',self.profile)
        self.initial_auth_url=(request(getattr(self,'attached_app','antigravity'),'authStatus') or {}).get('url','')
        self.tunnel.stop();self.local=active['bridge'];self.attached=True
        self.message='Нажмите «Войти» в Antigravity. Его ссылка автоматически откроется через тот же профиль; ждём новую попытку входа.'

    def start(self):
        if self.service in ('antigravity','antigravity-ide'):
            self.attach_antigravity();return self.status()
        if self.mode in ('cli','device'):
            if self.service not in ('codex','claude'):raise ValueError('Для этого сервиса начните вход в приложении, затем включите автоподхват ссылок.')
            app=self.service;exe=executable(app_adapter(app))
            args=['login'] if app=='codex' else ['auth','login']
            if self.mode=='device':
                if app!='codex':raise ValueError('Режим кода устройства доступен для Codex.')
                args.append('--device-auth')
            self.start_capture_server()
            hook=Path(__file__).with_name('auth_browser_hook.py')
            script='#!/bin/sh\nexec '+shlex.join([sys.executable,'-B',str(hook)])+' "$@"\n'
            for name in ('open','browser'):
                path=self.hookdir/name;path.write_text(script);path.chmod(0o700)
            env=dict(self.env);env.update(DAGAMI_AUTH_PORT=str(self.capture.server_port),DAGAMI_AUTH_TOKEN=self.token,BROWSER=str(self.hookdir/'browser'),PATH=str(self.hookdir)+os.pathsep+os.environ.get('PATH','/usr/bin:/bin'),TERM='xterm-256color',NO_COLOR='1')
            master,slave=pty.openpty();self.master=master;fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,2000,0,0))
            try:self.process=Launcher.launch(exe,args,env,stdin=slave,stdout=slave,stderr=slave)
            finally:os.close(slave)
            self.master=master;self.message='Штатная команда входа запущена. Ожидается ссылка.'
            self.reader=threading.Thread(target=self.watch_cli,daemon=True);self.reader.start()
        elif self.mode=='watch':
            self.initial_log_url=find_link(self.service)
            self.message='Начните вход в приложении. Свежие ссылки ищутся автоматически.'
            threading.Thread(target=self.watch_logs,daemon=True).start()
        else:
            url=SERVICES[self.service]['url']
            if not url:raise ValueError('Вставьте HTTPS-ссылку своего сервиса.')
            self.open_url(url)
        return self.status()
    def start_capture_server(self):
        session=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.connection.settimeout(5)
                if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+session.token):self.send_error(403);return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=32768:raise ValueError()
                    url=json.loads(self.rfile.read(size))['url'];session.capture_url(url)
                    self.send_response(200);self.end_headers();self.wfile.write(b'OK')
                except Exception:self.send_error(400,'Login URL rejected')
        self.capture=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.capture.daemon_threads=True
        threading.Thread(target=self.capture.serve_forever,daemon=True).start()
    def watch_cli(self):
        text='';pending=''
        try:
            while not self.closed:
                readable,_,_=select.select([self.master],[],[],0.3)
                if readable:
                    try:chunk=os.read(self.master,16384).decode('utf-8','replace')
                    except OSError:break
                    if not chunk:break
                    text=(text+chunk)[-65536:];pending+=chunk
                    if self.mode=='device':
                        codes=re.findall(r'(?m)^\s*([A-Z0-9]{4}-[A-Z0-9]{4})\s*$',re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text))
                        if codes:self.code=codes[-1]
                    if '\n' in pending:
                        complete,pending=pending.rsplit('\n',1)
                        for url in auth_urls(complete,self.service):
                            try:self.capture_url(url)
                            except Exception:self.message='Ссылка найдена. Не удалось открыть браузер; нажмите «Открыть». '
                if self.process.poll() is not None and not readable:break
            if not self.closed:
                code=self.process.poll()
                self.message='CLI сообщил об успешном завершении входа.' if code==0 else 'Команда входа завершилась без подтверждения. Начните вход заново или используйте код устройства.'
        finally:
            if self.master is not None:
                try:os.close(self.master)
                except OSError:pass
                self.master=None
    def watch_logs(self):
        while not self.closed and time.monotonic()-self.created<600:
            url=find_link(self.service)
            if url and url!=self.url and url!=getattr(self,'initial_log_url',''):
                try:self.capture_url(url)
                except Exception:self.message='Ссылка найдена; нажмите «Открыть».'
            time.sleep(2)
    def close(self):
        with self.lock:self.closed=True
        if getattr(self,'code_browser',None):self.code_browser.close()
        errors=[]
        for proc in ([self.process] if self.process is not None else [])+self.browser_processes:
            try:
                if process_alive(proc,self.retired):signal_group(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    signal_group(proc.pid,signal.SIGKILL);proc.wait(timeout=3)
                if process_alive(proc,self.retired):signal_group(proc.pid,signal.SIGKILL)
            except Exception as exc:errors.append(str(exc))
        if errors:
            self.closed=False;raise RuntimeError('Не удалось закрыть процесс входа. Сессия сохранена; повторите остановку. '+errors[0])
        if self.reader and self.reader is not threading.current_thread():self.reader.join(timeout=2)
        if self.master is not None:
            try:os.close(self.master)
            except OSError:pass
            self.master=None
        if self.capture:self.capture.shutdown();self.capture.server_close();self.capture=None
        self.tunnel.stop()
        import shutil
        shutil.rmtree(self.hookdir,ignore_errors=True)
        self.message='Ожидание входа остановлено. Antigravity продолжает работать.' if self.attached else 'Сессия входа остановлена. Сохранённые аккаунты клиента не удалены.'


class AuthManager:
    def __init__(self):self.session=None
    def start(self,service,profile,mode='browser',auto=True,url=''):
        if self.session:self.session.close();self.session=None
        session=AuthSession(service,profile,mode,auto)
        try:
            if url:
                if service=='antigravity':session.attach_antigravity()
                result=session.open_url(url,manual=True)
            else:result=session.start()
        except Exception:session.close();raise
        self.session=session;return result
    def status(self):return self.session.status() if self.session else {'message':'Сессия входа не запущена','url':'','code':'','running':False}
    def stop(self):
        if self.session:self.session.close();self.session=None
        return self.status()
    def open(self,url):
        if not self.session:raise ValueError('Сначала выберите профиль и начните сессию входа.')
        return self.session.open_url(url,manual=True)
