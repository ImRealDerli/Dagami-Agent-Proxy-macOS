










import socket
import ssl
import time
import base64
import urllib.parse
from typing import Dict, Any, List, Optional
from .profile import ProxyProfile


DEFAULT_TARGETS = [
    ("Google AI (Generative Language)", "generativelanguage.googleapis.com", 443),
    ("OpenAI API", "api.openai.com", 443),
    ("Anthropic API", "api.anthropic.com", 443),
    ("GitHub", "github.com", 443),
]


class ValidationResult:
    def __init__(self, profile: ProxyProfile):
        self.profile = profile
        self.tcp_reachable: bool = False
        self.tcp_latency_ms: Optional[float] = None
        self.auth_required: bool = False
        self.auth_success: bool = False
        self.tls_strict_verified: bool = False
        self.target_checks: List[Dict[str, Any]] = []
        self.overall_success: bool = False
        self.errors: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile.name,
            "url": self.profile.to_safe_url(),
            "tcp_reachable": self.tcp_reachable,
            "tcp_latency_ms": self.tcp_latency_ms,
            "auth_required": self.auth_required,
            "auth_success": self.auth_success,
            "tls_strict_verified": self.tls_strict_verified,
            "targets": self.target_checks,
            "overall_success": self.overall_success,
            "errors": self.errors
        }


class ProxyValidator:
    @staticmethod
    def test_tcp_connect(host: str, port: int, timeout: float = 4.0) -> (bool, Optional[float], Optional[str]):
        
        t0 = time.monotonic()
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            latency = (time.monotonic() - t0) * 1000.0
            sock.close()
            return True, round(latency, 2), None
        except Exception as e:
            return False, None, str(e)

    @classmethod
    def test_http_proxy(cls, profile, target_host="generativelanguage.googleapis.com", target_port=443, timeout=6.0):
        if profile.protocol != 'https':
            return cls._test_http_connect(profile,target_host,target_port,timeout)
                                                                           
                                                                               
        from .tunnel import LocalTunnel
        tunnel=LocalTunnel(profile)
        try:
            port=tunnel.start()
            local=ProxyProfile(name=profile.name,protocol='http',host='127.0.0.1',port=port)
            ok,auth,tls,error=cls._test_http_connect(local,target_host,target_port,timeout)
            if error and 'HTTP 407' in error:
                if profile.username:error=error.replace('логин не задан','логин задан')
                if profile.password:error=error.replace('пароль не задан','пароль задан')
            return ok,auth,tls,error
        finally:tunnel.stop()

    @classmethod
    def _test_http_connect(cls, profile: ProxyProfile, target_host: str = "generativelanguage.googleapis.com", target_port: int = 443, timeout: float = 6.0) -> (bool, bool, bool, Optional[str]):
        



        try:
            sock = socket.create_connection((profile.host, profile.port), timeout=timeout)
            
                                                                     
            if profile.protocol == "https":
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=profile.host)

                                   
            connect_line = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n"
            headers = [connect_line, "Proxy-Connection: Keep-Alive\r\n"]

            if profile.has_auth:
                cred = f"{profile.username or ''}:{profile.password or ''}"
                b64 = base64.b64encode(cred.encode("utf-8")).decode("ascii")
                headers.append(f"Proxy-Authorization: Basic {b64}\r\n")

            headers.append("\r\n")
            req_data = "".join(headers).encode("latin-1")
            sock.sendall(req_data)

                           
            resp_buf = b""
            while b"\r\n\r\n" not in resp_buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp_buf += chunk
                if len(resp_buf) > 16384:
                    break

            if not resp_buf:
                sock.close()
                return False, False, False, "Empty response from proxy on CONNECT"

            first_line = resp_buf.split(b"\r\n")[0].decode("latin-1", errors="replace")
            parts = first_line.split(" ")
            status_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

            if status_code == 407:
                sock.close()
                schemes=[]
                for line in resp_buf.split(b"\r\n")[1:]:
                    if line.lower().startswith(b'proxy-authenticate:'):
                        value=line.split(b':',1)[1].strip().split(None,1)
                        if value:
                            scheme=value[0].decode('ascii','ignore')
                            if scheme.isalpha() and len(scheme)<20 and scheme not in schemes:schemes.append(scheme)
                state=('логин задан' if profile.username else 'логин не задан')+', '+('пароль задан' if profile.password else 'пароль не задан')
                method=', '.join(schemes) if schemes else 'сервер не указал схему'
                hint='Проверьте логин, пароль и привязку IP в кабинете провайдера.'
                if schemes and 'basic' not in [x.lower() for x in schemes]:hint='Этот прокси требует другую схему авторизации. В приложении поддержана Basic; выберите у провайдера HTTP Basic или SOCKS5.'
                return False, False, False, f"HTTP 407 Proxy Authentication Required: upstream-прокси отклонил доступ; {state}; схема: {method}. {hint}"

            if status_code != 200:
                sock.close()
                return False, False, False, f"Proxy returned HTTP {status_code}: {first_line}"

                                                                                        
            ctx = ssl.create_default_context()
                                                                                                  
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            
            tls_sock = ctx.wrap_socket(sock, server_hostname=target_host)
                               
            cert = tls_sock.getpeercert()
            tls_sock.close()

            if cert:
                return True, True, True, None
            return True, True, False, "TLS certificate verification failed"

        except ssl.SSLCertVerificationError as e:
            return False, False, False, f"Strict TLS Verification Failed: {e}"
        except Exception as e:
            return False, False, False, str(e)

    @classmethod
    def test_socks5_proxy(cls, profile: ProxyProfile, target_host: str = "generativelanguage.googleapis.com", target_port: int = 443, timeout: float = 6.0) -> (bool, bool, bool, Optional[str]):
        



        try:
            sock = socket.create_connection((profile.host, profile.port), timeout=timeout)
            
                             
            if profile.has_auth:
                sock.sendall(b"\x05\x02\x00\x02")                                         
            else:
                sock.sendall(b"\x05\x01\x00")

            resp = cls._recv_exact(sock, 2)
            if len(resp) < 2 or resp[0] != 0x05:
                sock.close()
                return False, False, False, "Invalid SOCKS5 greeting response"

            auth_method = resp[1]
            if auth_method == 0xFF:
                sock.close()
                return False, False, False, "SOCKS5 No acceptable authentication methods"

            if auth_method == 0x02:
                                                  
                user_bytes = (profile.username or "").encode("utf-8")
                pwd_bytes = (profile.password or "").encode("utf-8")
                if len(user_bytes) > 255 or len(pwd_bytes) > 255:
                    return False, False, False, "SOCKS5 credentials exceed the 255-byte protocol limit"
                auth_req = bytearray([0x01, len(user_bytes)]) + user_bytes + bytearray([len(pwd_bytes)]) + pwd_bytes
                sock.sendall(auth_req)
                auth_resp = cls._recv_exact(sock, 2)
                if len(auth_resp) < 2 or auth_resp[1] != 0x00:
                    sock.close()
                    return False, False, False, "SOCKS5 Authentication failed (bad username or password)"

                             
                                                                       
            host_bytes = target_host.encode("utf-8")
            if len(host_bytes) > 255:
                return False, True, False, "SOCKS5 target hostname exceeds the 255-byte protocol limit"
            port_bytes = target_port.to_bytes(2, byteorder="big")
            cmd = bytearray([0x05, 0x01, 0x00, 0x03, len(host_bytes)]) + host_bytes + port_bytes
            sock.sendall(cmd)

            conn_resp = cls._recv_exact(sock, 4)
            if len(conn_resp) < 4 or conn_resp[1] != 0x00:
                rep_code = conn_resp[1] if len(conn_resp) >= 2 else -1
                sock.close()
                return False, True, False, f"SOCKS5 Connect rejected by proxy (code 0x{rep_code:02x})"

                                
            atyp = conn_resp[3]
            if atyp == 0x01:
                cls._recv_exact(sock, 4 + 2)
            elif atyp == 0x03:
                dlen = cls._recv_exact(sock, 1)[0]
                cls._recv_exact(sock, dlen + 2)
            elif atyp == 0x04:
                cls._recv_exact(sock, 16 + 2)

                                                        
            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            tls_sock = ctx.wrap_socket(sock, server_hostname=target_host)
            cert = tls_sock.getpeercert()
            tls_sock.close()

            return True, True, bool(cert), None

        except ssl.SSLCertVerificationError as e:
            return False, False, False, f"Strict TLS Verification Failed: {e}"
        except Exception as e:
            return False, False, False, str(e)

    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError("Unexpected end of proxy response")
            data.extend(chunk)
        return bytes(data)

    @classmethod
    def validate(cls, profile: ProxyProfile, targets: Optional[List[tuple]] = None, timeout: float = 5.0) -> ValidationResult:
        
        if profile.protocol == 'direct' or not profile.proxy_enabled or profile.smart_dns:
            from .tunnel import LocalTunnel
            tunnel=LocalTunnel(profile)
            try:
                port=tunnel.start()
                result=cls.validate(ProxyProfile(name=profile.name,protocol='http',host='127.0.0.1',port=port),targets,timeout)
                result.profile=profile
                return result
            finally:tunnel.stop()
        res = ValidationResult(profile)
        check_targets = targets or DEFAULT_TARGETS

                             
        tcp_ok, latency, err = cls.test_tcp_connect(profile.host, profile.port, timeout=timeout)
        res.tcp_reachable = tcp_ok
        res.tcp_latency_ms = latency
        if not tcp_ok:
            res.errors.append(f"Proxy host unreachable ({profile.host}:{profile.port}): {err}")
            return res

                              
        passed_any = False
        for label, host, port in check_targets:
            t_start = time.monotonic()
            if profile.is_socks:
                ok, auth_ok, tls_ok, msg = cls.test_socks5_proxy(profile, host, port, timeout=timeout)
            else:
                ok, auth_ok, tls_ok, msg = cls.test_http_proxy(profile, host, port, timeout=timeout)
            
            elapsed = round((time.monotonic() - t_start) * 1000.0, 1)
            target_entry = {
                "name": label,
                "host": host,
                "port": port,
                "success": ok and tls_ok,
                "latency_ms": elapsed,
                "error": msg
            }
            res.target_checks.append(target_entry)

            if ok and tls_ok:
                passed_any = True
                res.auth_success = True
                res.tls_strict_verified = True
            elif msg and "Authentication" in msg:
                res.auth_required = True
                res.errors.append(f"Auth error on {label}: {msg}")
                if "HTTP 407" in msg:break                                                          
            elif not (ok and tls_ok):
                res.errors.append(f"{label} ({host}): {msg or 'TLS не подтверждён'}")

        res.overall_success = bool(res.target_checks) and all(item["success"] for item in res.target_checks)
        if not res.overall_success and not res.errors:
            res.errors.append("Failed to establish a secure tunnel to every requested target endpoint.")
        return res
