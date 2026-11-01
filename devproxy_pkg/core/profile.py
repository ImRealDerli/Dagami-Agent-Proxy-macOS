











import urllib.parse
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class ProxyProfile:
    name: str
    protocol: str                                        
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = field(default=None, repr=False)
    dns_remote: bool = False                                                  
    notes: Optional[str] = None

    tls_fragment: int = 0
    proxy_enabled: bool = True
    smart_dns: bool = False
    dns_endpoints: list = field(default_factory=list)
    dns_scope: str = 'google'
    dns_domains: list = field(default_factory=list)
    dns_padding: bool = False
    block_updates: bool = False

    def __post_init__(self):
        if self.tls_fragment not in (0,1,8,32):raise ValueError('Недопустимый размер разделения TLS.')
        self.protocol = self.protocol.lower()
        if self.protocol == "socks5h":
            self.dns_remote = True
        if not self.port or self.port < 1 or self.port > 65535:
            raise ValueError(f"Invalid port: {self.port}. Must be 1-65535.")
        if not self.host:
            raise ValueError("Host cannot be empty.")

    @property
    def is_socks(self) -> bool:
        return self.protocol in ("socks5", "socks5h")

    @property
    def has_auth(self) -> bool:
        return bool(self.username or self.password)

    def to_url(self, include_auth: bool = True) -> str:
        
        if self.protocol=='direct':return 'direct://'
        proto = self.protocol
        host_str = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        if include_auth and self.has_auth:
            user = urllib.parse.quote(self.username or "", safe="")
            pwd = urllib.parse.quote(self.password or "", safe="")
            return f"{proto}://{user}:{pwd}@{host_str}:{self.port}"
        return f"{proto}://{host_str}:{self.port}"

    def to_safe_url(self) -> str:
        
        if not self.has_auth:
            return self.to_url(include_auth=False)
        if self.protocol=='direct':return 'direct://'
        proto = self.protocol
        host_str = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        user = urllib.parse.quote(self.username or "", safe="")
        return f"{proto}://{user}:***@{host_str}:{self.port}"

    def to_dict(self, include_password: bool = False) -> dict:
        d = {
            "name": self.name,
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "dns_remote": self.dns_remote,
            "tls_fragment": self.tls_fragment,
            "proxy_enabled": self.proxy_enabled,
            "smart_dns": self.smart_dns,
            "dns_endpoints": self.dns_endpoints,
            "dns_scope": self.dns_scope,
            "dns_domains": self.dns_domains,
            "dns_padding": self.dns_padding,
            "block_updates": self.block_updates,
            "notes": self.notes
        }
        if include_password and self.password:
            d["password"] = self.password
        return d

    @classmethod
    def from_dict(cls, data: dict, password: Optional[str] = None) -> "ProxyProfile":
        return cls(
            name=data["name"],
            protocol=data.get("protocol", "http"),
            host=data["host"],
            port=int(data["port"]),
            username=data.get("username"),
            password=password or data.get("password"),
            dns_remote=bool(data.get("dns_remote", False)),
            tls_fragment=int(data.get("tls_fragment",0)),
            proxy_enabled=bool(data.get("proxy_enabled",True)),
            smart_dns=bool(data.get("smart_dns",False)),
            dns_endpoints=list(data.get("dns_endpoints",[])),
            dns_scope=data.get("dns_scope","google"),
            dns_domains=list(data.get("dns_domains",[])),
            dns_padding=bool(data.get("dns_padding",False)),
            block_updates=bool(data.get("block_updates",False)),
            notes=data.get("notes")
        )

    @classmethod
    def parse(cls, raw: str, name: str = "default", fallback_protocol: str = "http") -> "ProxyProfile":
        







        if raw.strip().lower() == 'direct://':
            return cls(name=name, protocol='direct', host='direct', port=1)
        raw = raw.strip().strip("'\"")
        if not raw:
            raise ValueError("Proxy string cannot be empty.")

                         
        if "://" in raw:
            parsed = urllib.parse.urlsplit(raw)
            scheme = parsed.scheme.lower()
            if scheme not in ("http", "https", "socks5", "socks5h"):
                raise ValueError(f"Unsupported proxy scheme: '{scheme}'. Use http, https, socks5, or socks5h.")
            
            host = parsed.hostname
            port = parsed.port
            if not host:
                raise ValueError(f"Invalid host in proxy URL: '{raw}'")
            if not port:
                               
                port = 443 if scheme == "https" else 1080 if "socks" in scheme else 8080

            username = urllib.parse.unquote(parsed.username) if parsed.username is not None else None
            password = urllib.parse.unquote(parsed.password) if parsed.password is not None else None

            dns_remote = (scheme == "socks5h")
            return cls(
                name=name,
                protocol=scheme,
                host=host,
                port=port,
                username=username,
                password=password,
                dns_remote=dns_remote
            )

                                                                                   
        if raw.startswith("["):
            end_bracket = raw.find("]")
            if end_bracket != -1:
                host = raw[1:end_bracket]
                remainder = raw[end_bracket+1:]
                if remainder.startswith(":"):
                    parts = remainder[1:].split(":")
                    if len(parts) == 1:
                        port = int(parts[0])
                        return cls(name=name, protocol=fallback_protocol, host=host, port=port)
                    elif len(parts) == 3:
                        port = int(parts[0])
                        user, pwd = parts[1], parts[2]
                        return cls(name=name, protocol=fallback_protocol, host=host, port=port, username=user, password=pwd)

                                                                  
        parts = raw.split(":")
        if len(parts) == 4:
                                 
            host, port_str, user, pwd = parts
            try:
                port = int(port_str)
                return cls(name=name, protocol=fallback_protocol, host=host, port=port, username=user, password=pwd)
            except ValueError:
                raise ValueError(f"Invalid port in 'host:port:user:pass': '{port_str}'")

        if len(parts) == 2:
                       
            host, port_str = parts
            try:
                port = int(port_str)
                return cls(name=name, protocol=fallback_protocol, host=host, port=port)
            except ValueError:
                raise ValueError(f"Invalid port in 'host:port': '{port_str}'")

                                               
        raise ValueError(
            f"Cannot deterministically parse proxy string '{raw}'. "
            "Please use full URL (e.g. 'http://user:pass@host:port' or 'socks5://host:port') "
            "or 'host:port'."
        )
