import select,socket,ssl,threading,time


class TLSChannel:
    def __init__(self,stream):
        self._stream=stream;self._timeout=stream.gettimeout();self._ssl_lock=threading.RLock()
        self._read_lock=threading.Lock();self._write_lock=threading.Lock();self._closed=False
        stream.setblocking(False)

    def _deadline(self):return None if self._timeout is None else time.monotonic()+self._timeout

    def _call(self,operation,deadline):
        while True:
            try:
                with self._ssl_lock:
                    if self._closed:raise OSError('TLS channel is closed')
                    return operation()
            except (ssl.SSLWantReadError,ssl.SSLWantWriteError) as error:
                if self._timeout==0:raise
                remaining=None if deadline is None else deadline-time.monotonic()
                if remaining is not None and remaining<=0:raise socket.timeout('TLS operation timed out') from None
                delay=.1 if remaining is None else min(.1,remaining)
                readers=[self._stream] if isinstance(error,ssl.SSLWantReadError) else []
                writers=[] if readers else [self._stream]
                try:select.select(readers,writers,[],delay)
                except (OSError,ValueError):raise OSError('TLS channel was closed while waiting') from None

    def recv(self,count,flags=0):
        if flags:raise ValueError('TLS receive flags are not supported')
        with self._read_lock:return self._call(lambda:self._stream.recv(count),self._deadline())

    def send(self,data,flags=0):
        if flags:raise ValueError('TLS send flags are not supported')
        with self._write_lock:return self._call(lambda:self._stream.send(data),self._deadline())

    def sendall(self,data,flags=0):
        if flags:raise ValueError('TLS send flags are not supported')
        view=memoryview(data);deadline=self._deadline()
        with self._write_lock:
            offset=0
            while offset<len(view):
                part=view[offset:offset+65536]
                count=self._call(lambda:self._stream.send(part),deadline)
                if count<=0:raise ConnectionError('TLS channel stopped accepting data')
                offset+=count

    def settimeout(self,value):
        if value is not None and value<0:raise ValueError('Timeout must be nonnegative')
        self._timeout=value

    def gettimeout(self):return self._timeout
    def setblocking(self,enabled):self.settimeout(None if enabled else 0)
    def fileno(self):return self._stream.fileno()
    def setsockopt(self,*args):return self._stream.setsockopt(*args)
    def getsockname(self):return self._stream.getsockname()
    def getpeername(self):return self._stream.getpeername()

    def pending(self):
        with self._ssl_lock:return self._stream.pending()

    def getpeercert(self,binary_form=False):
        with self._ssl_lock:return self._stream.getpeercert(binary_form=binary_form)

    def shutdown(self,how):
        with self._ssl_lock:
            if how==socket.SHUT_WR:return socket.socket.shutdown(self._stream,how)
            return self._stream.shutdown(how)

    def close(self):
        with self._ssl_lock:
            if not self._closed:self._closed=True;self._stream.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def wrap_tls(context,stream,hostname):
    return TLSChannel(context.wrap_socket(stream,server_hostname=hostname))
