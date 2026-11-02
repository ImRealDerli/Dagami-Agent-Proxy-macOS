import json,os,select,shutil,socket,ssl,subprocess,tempfile,threading,time
from pathlib import Path
from .process_env import external_environment


def binary_path():
    override=os.environ.get('DAGAMI_NETWORK_BINARY')
    candidate=Path(override) if override else Path(__file__).resolve().parents[2].parent.parent/'MacOS/DagamiNetwork'
    return candidate if candidate.is_file() and os.access(candidate,os.X_OK) else None


def read_frame(stream,deadline):
    data=bytearray()
    while len(data)<8192:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Истекло время ответа Rust-транспорта.')
        stream.settimeout(remaining);byte=stream.recv(1)
        if not byte:raise ConnectionError('Rust-транспорт закрыл управляющее соединение.')
        if byte==b'\n':return json.loads(data)
        data.extend(byte)
    raise ValueError('Слишком большой управляющий ответ Rust-транспорта.')


class RustTransport:
    def __init__(self):
        self.binary=binary_path();self.process=None;self.directory=None;self.socket_path=None
        self.lock=threading.Lock();self.stopping=False;self.error='';self.reader=None

    @property
    def available(self):return self.binary is not None

    def start(self):
        with self.lock:
            if self.stopping:raise ConnectionError('Rust-транспорт остановлен.')
            if self.process is not None:
                if self.process.poll() is not None:raise ConnectionError('Rust-транспорт аварийно завершился. Перезапустите сессию.')
                return
            if self.binary is None:raise FileNotFoundError('Rust-транспорт не входит в эту сборку.')
            directory=Path(tempfile.mkdtemp(prefix='dagami-net-',dir='/tmp'));directory.chmod(0o700);path=directory/'bridge.sock'
            if len(os.fsencode(path))>=104:shutil.rmtree(directory);raise ValueError('Слишком длинный путь сокета Rust-транспорта.')
            from .transport import ensure_socket_capacity
            ensure_socket_capacity()
            config={'socket':str(path),'ca_file':ssl.get_default_verify_paths().cafile}
            process=None
            try:
                process=subprocess.Popen([str(self.binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=external_environment(),start_new_session=True)
                process.stdin.write((json.dumps(config)+'\n').encode());process.stdin.flush()
                if not select.select([process.stdout],[],[],8)[0]:raise TimeoutError('Rust-транспорт не подтвердил запуск.')
                data=process.stdout.readline(8193)
                ready=json.loads(data)
                if ready!={'ready':True,'version':1}:raise RuntimeError('Несовместимая версия Rust-транспорта.')
                self.process=process;self.directory=directory;self.socket_path=path
                self.reader=threading.Thread(target=self._errors,args=(process,),daemon=True,name='DagamiNetworkStatus');self.reader.start()
            except BaseException:
                if process is not None:
                    process.terminate()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                    for stream in (process.stdin,process.stdout,process.stderr):stream.close()
                shutil.rmtree(directory);raise

    def _errors(self,process):
        last_report=0
        for line in process.stderr:
            text=line.decode('utf-8','replace').strip()
            if text.startswith('Dagami network:') or text.startswith('Dagami network relay:'):
                self.error=text[:160]
                if not self.stopping and time.monotonic()-last_report>30:
                    last_report=time.monotonic()
                    try:
                        from ..journal import append
                        append('proxyTunnel',False,self.error)
                    except Exception:pass

    def connect(self,host,port,tls=False,timeout=8,fragment=0):
        host=host.encode('idna').decode('ascii')
        self.start();deadline=time.monotonic()+timeout;stream=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            stream.settimeout(timeout);stream.connect(str(self.socket_path))
            request={'host':host,'port':port,'tls':tls,'timeout_ms':max(1,min(15000,int(timeout*1000))),'fragment':fragment}
            stream.sendall((json.dumps(request)+'\n').encode());reply=read_frame(stream,deadline)
            if not reply.get('ok'):
                errors={'connect_timeout':'Истекло время подключения к прокси.','tcp_connect_failed':'Не удалось подключиться к адресу прокси.','tls_verification_or_handshake_failed':'Прокси не прошёл TLS-проверку или прервал рукопожатие.','capacity':'Rust-транспорт перегружен.','invalid_server_name':'Некорректное имя TLS-сервера.'}
                raise ConnectionError(errors.get(reply.get('error'),'Rust-транспорт отклонил подключение.'))
            stream.settimeout(timeout);return stream
        except BaseException:stream.close();raise

    def close(self):
        with self.lock:
            self.stopping=True;process=self.process
            if process is not None:
                try:process.stdin.close()
                except OSError:pass
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                if self.reader:self.reader.join(timeout=1)
                process.stdout.close();process.stderr.close()
            if self.directory:shutil.rmtree(self.directory,ignore_errors=True)
