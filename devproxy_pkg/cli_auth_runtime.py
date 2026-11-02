import codecs,fcntl,os,pty,queue,re,select,shlex,signal,struct,subprocess,sys,termios,threading,time,tty
from urllib.parse import urlsplit,parse_qs
from pathlib import Path
from .auth_manager import AuthSession,validate_clipboard_url
from .core.launcher import Launcher
from .portable_runtime import signal_group,process_alive
from .cli_code_gate import CliCodeGate


def complete_cli_oauth(url):
    try:
        validate_clipboard_url(url,'agy');p=urlsplit(url);query=parse_qs(p.query)
        keys=('client_id','state','redirect_uri','response_type','scope','code_challenge','code_challenge_method')
        if any(len(query.get(key,[]))!=1 for key in keys):return False
        if not query['client_id'][0].endswith('.apps.googleusercontent.com') or len(query['state'][0])<16:return False
        if query['response_type']!=['code'] or query['code_challenge_method']!=['S256'] or not query['scope'][0]:return False
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',query['code_challenge'][0]) or re.search(r'%(?![0-9A-Fa-f]{2})',url):return False
        return True
    except ValueError:return False


def cli_auth_urls(text,settled=False):
    clean=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    clean=re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)','',clean)
    lines=clean.replace('\r','').split('\n');found=[]
    for url in re.findall(r'\x1b\]8;[^;]*;(https://[^\x1b\x07]+)(?:\x07|\x1b\\)',text):
        if complete_cli_oauth(url) and url not in found:found.append(url)
    for i,line in enumerate(lines):
        match=re.search(r'https://',line)
        if not match:continue
        candidate=line[match.start():].strip(' \t│┃║┆┊┇┋╎╏|')
        if not re.fullmatch(r'[A-Za-z0-9:/?&=%_.~+!$()*;,\[\]#@-]+',candidate):continue
        closed=settled
        for j in range(i+1,min(len(lines),i+65)):
            part=lines[j].strip(' \t│┃║┆┊┇┋╎╏|')
            if not part or part.startswith('https://') or part in ('Continue','Login','Cancel','Back','Retry','Done','Enter') or not re.fullmatch(r'[A-Za-z0-9:/?&=%_.~+!$()*;,\[\]#@-]+',part):
                closed=settled or j<len(lines)-1 or bool(part);break
            candidate+=part
            if len(candidate)>16384:break
        if closed and complete_cli_oauth(candidate) and candidate not in found:found.append(candidate)
    return found


def run_cli(executable,profile,args=None,environment_factory=None,stdin_fd=None,stdout_fd=None):
    certificate=Path(__file__).resolve().parents[2]/'cacert.pem'
    if certificate.is_file():os.environ.setdefault('SSL_CERT_FILE',str(certificate))
    input_fd=sys.stdin.fileno() if stdin_fd is None else stdin_fd
    output_fd=sys.stdout.fileno() if stdout_fd is None else stdout_fd
    session=AuthSession('agy',profile,mode='watch',auto=True)
    session.browser_directory=session.hookdir/'browser-data'
    codes=queue.Queue(maxsize=2);auth_requests=queue.Queue(maxsize=8);gate=CliCodeGate()
    stage_seen=set()
    def stage(message):
        key=(gate.state,message)
        if key in stage_seen:return
        if len(stage_seen)>=256:stage_seen.clear()
        stage_seen.add(key)
        try:
            from .journal import append
            append('cliAuth',True,message)
        except Exception:pass
    original_capture=session.capture_url
    def capture(url):
        if not complete_cli_oauth(url):raise ValueError("CLI передал неполную OAuth-ссылку.")
        try:auth_requests.put_nowait(url)
        except queue.Full:pass
        stage('CLI: исходная ссылка входа получена; ожидается код в браузере.')
        return original_capture(url)
    session.capture_url=capture
    def received_code(code,state):
        stage('CLI: браузер передал код; ожидается подходящее приглашение в этой терминальной сессии.')
        try:codes.put_nowait((code,state))
        except queue.Full:pass
    session.code_callback=received_code
    def report_error(message):
        try:os.write(output_fd,('\r\nDagami: '+message+'\r\n').encode())
        except OSError:pass
    session.code_error=report_error
    master=slave=None;process=None;monitor=None;telemetry=None;original=None;old_resize=None;worker=None;old_signals={}
    links=queue.Queue(maxsize=8);done=threading.Event();seen=set()
    def dispatch():
        while not done.is_set():
            try:url=links.get(timeout=.1)
            except queue.Empty:continue
            if done.is_set():return
            try:session.capture_url(url)
            except Exception as exc:
                try:os.write(output_fd,('\r\nDagami: '+str(exc)+'\r\n').encode())
                except OSError:pass
    try:
        session.start_capture_server()
        hook=Path(__file__).with_name('auth_browser_hook.py')
        script='#!/bin/sh\nexec '+shlex.join([sys.executable,'-B','-I',str(hook)])+' "$@"\n'
        for name in ('open','browser'):
            path=session.hookdir/name;path.write_text(script);path.chmod(0o700)
        from .session_telemetry import Telemetry
        telemetry=Telemetry('agy',executable)
        env=dict(session.env);env.update(telemetry.environment)
        if environment_factory:env.update(environment_factory(session.local,executable))
        env.update(ANTIGRAVITY_VSCODE_HOST='1',DAGAMI_AUTH_PORT=str(session.capture.server_port),DAGAMI_AUTH_TOKEN=session.token,BROWSER=str(session.hookdir/'browser'),PATH=str(session.hookdir)+os.pathsep+os.environ.get('PATH','/usr/bin:/bin'))
        master,slave=pty.openpty()
        def resize(*unused):
            try:size=fcntl.ioctl(input_fd,termios.TIOCGWINSZ,b'\0'*8)
            except OSError:size=struct.pack('HHHH',24,120,0,0)
            if not all(struct.unpack('HHHH',size)[:2]):size=struct.pack('HHHH',24,120,0,0)
            try:fcntl.ioctl(master,termios.TIOCSWINSZ,size)
            except OSError:pass
        resize()
        if threading.current_thread() is threading.main_thread():
            old_resize=signal.signal(signal.SIGWINCH,resize)
            def terminate(signum,frame):raise SystemExit(128+signum)
            for signum in (signal.SIGTERM,signal.SIGHUP):old_signals[signum]=signal.signal(signum,terminate)
        helper=Path(__file__).resolve().parent.parent/'native/macos/cli_pty_exec.py'
        process=Launcher.launch(sys.executable,['-B','-I',str(helper),str(executable),*telemetry.flags,*(args or [])],env,stdin=slave,stdout=slave,stderr=slave,new_session=True)
        from .terminal_sessions import TerminalSession
        monitor=TerminalSession("agy",profile,process,session.local,telemetry=telemetry).start()
        os.close(slave);slave=None
        worker=threading.Thread(target=dispatch,daemon=True,name='DagamiCLILogin');worker.start()
        if os.isatty(input_fd):original=termios.tcgetattr(input_fd);tty.setraw(input_fd)
        pending='';decoder=codecs.getincrementaldecoder('utf-8')('replace');read_input=True;enter_due=None
        while True:
            readable,_,_=select.select([master]+([input_fd] if read_input else []),[],[],.15)
            if master in readable:
                try:data=os.read(master,16384)
                except OSError:break
                if not data:break
                os.write(output_fd,data);pending=(pending+decoder.decode(data))[-65536:]
            if read_input and input_fd in readable:
                data=os.read(input_fd,4096)
                if data:
                    if gate.user_input(data):
                        enter_due=None
                        if gate.waiting:stage('CLI: обнаружен ручной ввод; автоматическая отправка приостановлена.')
                    os.write(master,data)
                else:read_input=False;os.write(master,b'\x04')
            for url in cli_auth_urls(pending,settled=master not in readable):
                if url in seen:continue
                if len(seen)>=64:seen.clear()
                try:gate.begin(url);links.put_nowait(url);seen.add(url)
                except queue.Full:pass
            while not auth_requests.empty():
                try:
                    requested=auth_requests.get_nowait()
                    if requested not in seen or not gate.state:gate.begin(requested);seen.add(requested)
                except queue.Empty:break
            was_waiting=gate.waiting
            gate.observe(pending)
            if gate.waiting and not was_waiting:stage('CLI: обнаружено приглашение для кода авторизации.')
            while not codes.empty():
                try:authorization,state=codes.get_nowait();gate.offer(authorization,state)
                except queue.Empty:break
            authorization=gate.take()
            if authorization and process.poll() is None:
                os.write(master,authorization.encode());authorization=None;enter_due=time.monotonic()+.12
            if enter_due is not None and time.monotonic()>=enter_due and process.poll() is None:
                os.write(master,b'\r');enter_due=None
                stage('CLI: код отправлен в собственный PTY процесса; Enter отправлен. Успех входа подтверждает сам CLI.')
                os.write(output_fd,'\r\nDagami: код передан в эту CLI-сессию, Enter отправлен.\r\n'.encode())
            if process.poll() is not None and not readable:break
        code=process.wait()
        return code if code>=0 else 128-code
    finally:
        if monitor:monitor.close()
        if telemetry:telemetry.close()
        if original is not None:
            try:termios.tcsetattr(input_fd,termios.TCSADRAIN,original)
            except (OSError,termios.error):pass
        if old_resize is not None:signal.signal(signal.SIGWINCH,old_resize)
        for signum,handler in old_signals.items():signal.signal(signum,handler)
        done.set()
        if process is not None:
            retired=set()
            if process_alive(process,retired):signal_group(process.pid,signal.SIGTERM)
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:signal_group(process.pid,signal.SIGKILL);process.wait(timeout=3)
            if process_alive(process,retired):signal_group(process.pid,signal.SIGKILL)
        if worker:worker.join(timeout=8)
        for fd in (master,slave):
            if fd is not None:
                try:os.close(fd)
                except OSError:pass
        session.close()
