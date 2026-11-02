










import socket
import ipaddress
import ssl
import threading
import base64
import time
import urllib.parse
from typing import Optional
from .profile import ProxyProfile
from .transport import AdaptiveTLSGate, tune_socket, FastDuplexRelay
from .peer_identity import is_current_user
from . import http_wire


class LocalTunnel:
    MAX_CONNECTIONS = 128
    def __init__(self, profile: ProxyProfile, bind_host: str = "127.0.0.1", bind_port: int = 0):
        if not ipaddress.ip_address(bind_host).is_loopback:
            raise ValueError("The application proxy must bind loopback")
        self.profile = profile
        from .smart_dns import Resolver
        self.resolver = Resolver(profile.dns_endpoints,profile.dns_padding) if profile.smart_dns else None
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.server_sock: Optional[socket.socket] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.allocated_port: int = 0
        self.tls_gate = AdaptiveTLSGate()
        self._connections = set()
        self._work_slots = threading.BoundedSemaphore(self.MAX_CONNECTIONS)
        self._connections_lock = threading.Lock()

    def start(self, timeout: float = 3.0) -> int:

        family = socket.AF_INET6 if ":" in self.bind_host else socket.AF_INET
        self.server_sock = socket.socket(family, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.bind_host, self.bind_port))
        self.server_sock.listen(128)
        self.allocated_port = self.server_sock.getsockname()[1]
        self.is_running = True

        self._thread = threading.Thread(target=self._serve_loop, daemon=True, name="DevProxyTunnel")
        self._thread.start()


        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                test_sock = socket.create_connection((self.bind_host, self.allocated_port), timeout=0.2)
                test_sock.close()
                return self.allocated_port
            except Exception:
                time.sleep(0.05)

        return self.allocated_port

    def stop(self):

        self.is_running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
        with self._connections_lock:
            connections = list(self._connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _serve_loop(self):
        while self.is_running:
            try:
                client_sock, addr = self.server_sock.accept()
                if not self._work_slots.acquire(blocking=False):
                    try:
                        client_sock.settimeout(.5)
                        client_sock.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
                    finally:
                        client_sock.close()
                    continue
                try:
                    self._track_socket(client_sock, True)
                    tune_socket(client_sock)
                    threading.Thread(target=self._limited_client, args=(client_sock,), daemon=True).start()
                except Exception:
                    self._track_socket(client_sock, False)
                    client_sock.close()
                    self._work_slots.release()
                    raise
            except Exception:
                if not self.is_running:
                    break

    def _limited_client(self, client_sock):
        try:self._handle_client(client_sock)
        finally:self._work_slots.release()

    def _handle_client(self, client_sock: socket.socket):
        upstream_sock = None
        response_started = False
        def started():
            nonlocal response_started
            response_started = True
        try:
            client_sock.settimeout(15.0)
            if not is_current_user(client_sock):
                client_sock.sendall(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
                return
            req_data = self._recv_headers(client_sock)
            header_end = req_data.find(b"\r\n\r\n") + 4
            header_bytes = req_data[:header_end]
            initial_payload = req_data[header_end:]

            lines = header_bytes.split(b"\r\n")
            if not lines:
                client_sock.close()
                return

            first_line = lines[0].decode("latin-1", errors="replace")
            parts = first_line.split(" ")
            if len(parts) < 3:
                client_sock.close()
                return

            method, target_uri, proto = parts[0].upper(), parts[1], parts[2]

            dest_host = ""
            dest_port = 80

            if method == "CONNECT":
                parsed_target = urllib.parse.urlsplit("//" + target_uri)
                dest_host = parsed_target.hostname or ""
                dest_port = parsed_target.port or 443
            else:

                if target_uri.startswith("http://") or target_uri.startswith("https://"):
                    p = urllib.parse.urlsplit(target_uri)
                    dest_host = p.hostname
                    dest_port = p.port or (443 if p.scheme == "https" else 80)
                else:
                    for line in lines[1:]:
                        if line.lower().startswith(b"host:"):
                            hval = line.split(b":", 1)[1].strip().decode("latin-1")
                            parsed_host = urllib.parse.urlsplit("//" + hval)
                            dest_host = parsed_host.hostname or ""
                            dest_port = parsed_host.port or 80
                            break

            if not dest_host:
                client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                client_sock.close()
                return

            from .smart_dns import BLOCKABLE_UPDATE_HOSTS, scoped
            if self.profile.block_updates and dest_host.lower() in BLOCKABLE_UPDATE_HOSTS:
                client_sock.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                return
            if dest_host.lower() == 'metadata.google.internal' and dest_port == 80:
                client_sock.sendall(b'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                return




            try:
                address = ipaddress.ip_address('127.0.0.1' if dest_host.lower() == 'localhost' else dest_host)
                address = getattr(address, 'ipv4_mapped', None) or address
                local = address.is_loopback
            except ValueError:
                local = False
            dns_only = not self.profile.proxy_enabled or self.profile.protocol == 'direct'
            routed_ip = None
            if not local and self.resolver and scoped(dest_host,dns_only,self.profile.dns_scope,self.profile.dns_domains):
                try:
                    routed_ip = self.resolver.resolve(dest_host)
                    upstream_sock = socket.create_connection((routed_ip,dest_port),timeout=8.0)
                except (OSError, ValueError):
                    if upstream_sock:upstream_sock.close();upstream_sock=None
                    if dns_only:raise
                    routed_ip = None
            if local or routed_ip or dns_only:
                if local and dest_port == self.allocated_port and address == ipaddress.ip_address(self.bind_host):
                    client_sock.sendall(b'HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
                    return
                address = '127.0.0.1' if dest_host.lower() == 'localhost' else dest_host
                if upstream_sock is None:upstream_sock = socket.create_connection((address, dest_port), timeout=8.0)
                tune_socket(upstream_sock)
                if method != 'CONNECT' and target_uri.startswith('https://'):
                    upstream_sock = ssl.create_default_context().wrap_socket(upstream_sock, server_hostname=dest_host)
                self._track_socket(upstream_sock, True)
                if method == 'CONNECT':
                    client_sock.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    response_started = True
                    self._send_initial(upstream_sock,initial_payload)
                else:
                    authority = f'[{dest_host}]:{dest_port}' if ':' in dest_host else f'{dest_host}:{dest_port}'
                    absolute_target = target_uri if target_uri.startswith(('http://', 'https://')) else 'http://' + authority + target_uri
                    outgoing = http_wire.request_headers(header_bytes, absolute_target, False)
                    http_wire.exchange(client_sock, upstream_sock, header_bytes, outgoing, initial_payload, started, FastDuplexRelay.pipe)
                    return
                client_sock.settimeout(None)
                upstream_sock.settimeout(None)
                response_started = True
                FastDuplexRelay.pipe(client_sock, upstream_sock, self.profile.tls_fragment)
                return


            try:
                upstream_sock = self._open_upstream_socket()
            except TimeoutError:
                client_sock.sendall(b"HTTP/1.1 504 Gateway Timeout (TLS Handshake Queue Deadline Exceeded)\r\n\r\n")
                client_sock.close()
                return
            except Exception:

                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway (Proxy Unreachable)\r\n\r\n")
                client_sock.close()
                return


            if self.profile.is_socks:

                if not self._socks5_connect_upstream(upstream_sock, dest_host, dest_port):
                    client_sock.sendall(b"HTTP/1.1 502 Bad Gateway (SOCKS5 Handshake Failed)\r\n\r\n")
                    client_sock.close()
                    upstream_sock.close()
                    return

                if method == "CONNECT":

                    client_sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                else:

                    if target_uri.startswith('https://'):
                        upstream_sock = ssl.create_default_context().wrap_socket(upstream_sock, server_hostname=dest_host)
                        self._track_socket(upstream_sock, True)
                    authority = f'[{dest_host}]:{dest_port}' if ':' in dest_host else f'{dest_host}:{dest_port}'
                    absolute_target = target_uri if target_uri.startswith(('http://', 'https://')) else 'http://' + authority + target_uri
                    outgoing = http_wire.request_headers(header_bytes, absolute_target, False)
                    http_wire.exchange(client_sock, upstream_sock, header_bytes, outgoing, initial_payload, started, FastDuplexRelay.pipe)
                    return

            else:

                if method == "CONNECT":

                    resp_buf, response_end, status_code = self._http_proxy_connect(upstream_sock,dest_host,dest_port)
                    if status_code==403 and dest_host.lower().rstrip('.')=='accounts.google.ru' and dest_port==443 and self.profile.host.lower().rstrip('.') in ('test-dns.dagami.ru','dns.dagami.ru'):
                        self._track_socket(upstream_sock,False);upstream_sock.close()
                        upstream_sock=self._open_upstream_socket()
                        resp_buf,response_end,status_code=self._http_proxy_connect(upstream_sock,'accounts.google.com',443)
                    if status_code != 200:
                        client_sock.sendall(resp_buf if resp_buf else b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                        client_sock.close()
                        upstream_sock.close()
                        return


                    client_sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    if response_end < len(resp_buf):
                        client_sock.sendall(resp_buf[response_end:])
                else:
                    authorization = None
                    if self.profile.has_auth:
                        cred = f"{self.profile.username or ''}:{self.profile.password or ''}"
                        authorization = b'Basic ' + base64.b64encode(cred.encode('utf-8'))
                    authority = f'[{dest_host}]:{dest_port}' if ':' in dest_host else f'{dest_host}:{dest_port}'
                    absolute_target = target_uri if target_uri.startswith(('http://', 'https://')) else 'http://' + authority + target_uri
                    outgoing = http_wire.request_headers(header_bytes, absolute_target, True, authorization)
                    http_wire.exchange(client_sock, upstream_sock, header_bytes, outgoing, initial_payload, started, FastDuplexRelay.pipe)
                    return

            if method == "CONNECT" and initial_payload:
                self._send_initial(upstream_sock,initial_payload)


            client_sock.settimeout(None)
            upstream_sock.settimeout(None)
            response_started = True
            FastDuplexRelay.pipe(client_sock, upstream_sock, self.profile.tls_fragment)

        except Exception:
            if not response_started:
                try:
                    client_sock.sendall(b'HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
                except OSError:
                    pass
        finally:
            for connection in (client_sock, upstream_sock):
                if connection is None:
                    continue
                self._track_socket(connection, False)
                try:
                    connection.close()
                except Exception:
                    pass

    def _open_upstream_socket(self):
        connection=None
        try:
            with self.tls_gate.acquire(timeout=8.0):
                started=time.monotonic()
                connection=socket.create_connection((self.profile.host,self.profile.port),timeout=8.0)
                tune_socket(connection)
                if self.profile.protocol=='https':connection=ssl.create_default_context().wrap_socket(connection,server_hostname=self.profile.host)
                self.tls_gate.record_rtt(time.monotonic()-started)
                self._track_socket(connection,True)
                return connection
        except BaseException:
            if connection is not None:connection.close()
            raise

    def _http_proxy_connect(self,connection,host,port):
        headers=[f'CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n']
        if self.profile.has_auth:
            credentials=f'{self.profile.username or ""}:{self.profile.password or ""}'
            encoded=base64.b64encode(credentials.encode('utf-8')).decode('ascii')
            headers.append(f'Proxy-Authorization: Basic {encoded}\r\n')
        headers.append('\r\n');connection.sendall(''.join(headers).encode('latin-1'))
        response=self._recv_headers(connection);end=response.find(b'\r\n\r\n')+4
        status=response[:end].split(b'\r\n',1)[0].split()
        code=int(status[1]) if len(status)>=2 and status[1].isdigit() else 0
        return response,end,code

    def _send_initial(self,sock,data):
        size=self.profile.tls_fragment
        if size and data[:1]==b'\x16':
            for offset in range(0,len(data),size):sock.sendall(data[offset:offset+size])
        else:sock.sendall(data)

    @staticmethod
    def _recv_headers(sock: socket.socket, limit: int = 65536) -> bytes:
        data = bytearray()
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(min(4096, limit - len(data)))
            if not chunk:
                raise ConnectionError("Connection closed before complete HTTP headers")
            data.extend(chunk)
            if len(data) >= limit:
                raise ValueError("HTTP headers exceed 64 KiB")
        return bytes(data)

    @staticmethod
    def _origin_form_request(headers: bytes, target_uri: str) -> bytes:
        parsed = urllib.parse.urlsplit(target_uri)
        if parsed.scheme not in ("http", "https"):
            return headers
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        first_end = headers.find(b"\r\n")
        first_line = headers[:first_end].decode("latin-1").split(" ")
        first_line[1] = path
        return " ".join(first_line).encode("latin-1") + headers[first_end:]

    def _track_socket(self, sock: socket.socket, add: bool):
        with self._connections_lock:
            if add:
                if not self.is_running:
                    sock.close()
                    raise RuntimeError('Tunnel is stopping')
                self._connections.add(sock)
            else:
                self._connections.discard(sock)

    def _socks5_connect_upstream(self, sock: socket.socket, host: str, port: int) -> bool:

        try:
            sock.settimeout(10.0)
            if self.profile.has_auth:
                sock.sendall(b"\x05\x02\x00\x02")
            else:
                sock.sendall(b"\x05\x01\x00")

            resp = self._recv_exact(sock, 2)
            if len(resp) < 2 or resp[0] != 0x05:
                return False

            auth_method = resp[1]
            if auth_method == 0x02:
                user_b = (self.profile.username or "").encode("utf-8")
                pwd_b = (self.profile.password or "").encode("utf-8")
                req = bytearray([0x01, len(user_b)]) + user_b + bytearray([len(pwd_b)]) + pwd_b
                sock.sendall(req)
                auth_resp = self._recv_exact(sock, 2)
                if len(auth_resp) < 2 or auth_resp[1] != 0x00:
                    return False
            elif auth_method != 0x00:
                return False


            hb = host.encode("utf-8")
            pb = port.to_bytes(2, byteorder="big")
            cmd = bytearray([0x05, 0x01, 0x00, 0x03, len(hb)]) + hb + pb
            sock.sendall(cmd)

            conn_resp = self._recv_exact(sock, 4)
            if len(conn_resp) < 4 or conn_resp[1] != 0x00:
                return False

            atyp = conn_resp[3]
            if atyp == 0x01: self._recv_exact(sock, 4 + 2)
            elif atyp == 0x03:
                dlen = self._recv_exact(sock, 1)[0]
                self._recv_exact(sock, dlen + 2)
            elif atyp == 0x04: self._recv_exact(sock, 16 + 2)

            return True
        except Exception:
            return False

    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = sock.recv(length - len(chunks))
            if not chunk:
                raise ConnectionError("Unexpected end of SOCKS5 response")
            chunks.extend(chunk)
        return bytes(chunks)
