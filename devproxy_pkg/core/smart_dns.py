
from dataclasses import dataclass
import http.client
import ipaddress
import plistlib
import secrets
import socket
import ssl
import struct
import threading
import time
from urllib.parse import urlsplit

SCOPED = frozenset('''cloudcode-pa.googleapis.com daily-cloudcode-pa.googleapis.com
accounts.google.com oauth2.googleapis.com www.googleapis.com lh3.googleusercontent.com
 gemini.google.com gemini.google www.gstatic.com ssl.gstatic.com geminiweb-pa.clients6.google.com
apis.google.com alkalimakersuite-pa.clients6.google.com alkalicore-pa.clients6.google.com
waa-pa.clients6.google.com generativelanguage.googleapis.com proactivebackend-pa.googleapis.com
robinfrontend-pa.googleapis.com aisandbox-pa.googleapis.com play.googleapis.com
antigravity-unleash.goog content-autofill.googleapis.com update.googleapis.com'''.split())
DNS_ONLY = frozenset('aicode.googleapis.com cloudaicompanion.googleapis.com cloudresourcemanager.googleapis.com aiplatform.googleapis.com developerconnect.googleapis.com'.split())
UPDATE_HOSTS = frozenset('antigravity-'+suffix+'-974169037036.us-central1.run.app' for suffix in ('auto-updater','cli-auto-updater','ide-auto-updater','auto-updater-insider','hub-auto-updater'))
SETUP_HOSTS=frozenset('antigravity-'+suffix+'-974169037036.us-central1.run.app' for suffix in ('cli-auto-updater','ide-auto-updater'))
BLOCKABLE_UPDATE_HOSTS=UPDATE_HOSTS-SETUP_HOSTS
PROVIDERS = {
 'Dagami': ['https://dns.dagami.ru/dns-query'],
 'MagicDNS': ['https://dns.magicdns.ru/dns-query'],
 'Comss.one': ['https://dns.comss.one/dns-query'],
 'GeoHide': ['https://dns.geohide.ru/dns-query'],
 'Malw.link': ['tls://dns.malw.link'],
 'Xbox DNS': ['https://dns.xbox-dns.ru/dns-query'],
}
SEEDS = {
 'dns.dagami.ru': ['89.22.224.205','89.125.103.139','45.147.31.32','46.29.165.108'],
 'dns.magicdns.ru': ['2.56.175.196','109.120.132.43','94.249.177.102'],
 'dns.comss.one': ['195.133.25.16','212.109.195.93','185.146.157.78','212.109.221.20'],
 'dns.geohide.ru': ['159.194.200.33','193.233.112.67','193.233.112.68','193.233.112.88','37.230.192.51'],
 'dns.malw.link': ['164.5.224.81','179.254.166.171'],
 'dns.xbox-dns.ru': ['111.88.96.56','111.88.96.57'],
}
DEFAULT_ENDPOINTS = PROVIDERS['Dagami'] + PROVIDERS['MagicDNS']


import json
from pathlib import Path
AI_EXACT=frozenset(json.loads((Path(__file__).resolve().parents[1]/'assets'/'dns-domains.json').read_text(encoding='utf-8'))['Development'])
AI_ROOTS=frozenset("chatgpt.com openai.com oaistatic.com oaiusercontent.com anthropic.com claude.ai claude.com deepseek.com qwen.ai qwenlm.ai grok.com x.ai perplexity.ai mistral.ai huggingface.co cohere.com together.ai groq.com openrouter.ai copilot.microsoft.com copilot.com notebooklm.google.com".split())


def validate_domains(domains):
    import re
    result=[]
    if len(domains)>256:raise ValueError('Укажите не более 256 своих доменов.')
    for value in domains:
        value=value.strip().lower().rstrip('.')
        if not value:continue
        base=value[2:] if value.startswith('*.') else value
        try:base=base.encode('idna').decode('ascii')
        except UnicodeError:raise ValueError('Некорректный домен DNS.') from None
        if len(base)>253 or '.' not in base or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in base.split('.')):
            raise ValueError('Укажите домен без URL, порта и пути; поддомены задаются как *.example.com.')
        result.append(('*.')+base if value.startswith('*.') else base)
    return list(dict.fromkeys(result))


def scoped(host, dns_only=False, mode='google', domains=()):
    host=host.lower().rstrip('.')
    if dns_only and host=='accounts.google.com':return False
    if host in SCOPED or host in SETUP_HOSTS or (dns_only and host in DNS_ONLY):return True
    if mode=='ai' and (host in AI_EXACT or any(host==root or host.endswith('.'+root) for root in AI_ROOTS)):return True
    for domain in domains:
        if domain.startswith('*.'):
            root=domain[2:]
            if host==root or host.endswith('.'+root):return True
        elif host==domain:return True
    return False


@dataclass(frozen=True)
class Endpoint:
    scheme: str
    host: str
    port: int
    path: str = ''

    @classmethod
    def parse(cls, value):
        value=value.strip()
        if '://' not in value:value='udp://'+value
        p=urlsplit(value)
        if p.scheme not in ('https','tls','udp','tcp') or not p.hostname or p.username or p.password or p.fragment:
            raise ValueError('DNS: нужен https://, tls://, udp:// или tcp:// endpoint без реквизитов.')
        if any(c in value for c in '\r\n\x00'):
            raise ValueError('Недопустимый DNS endpoint.')
        port=p.port or {'https':443,'tls':853,'udp':53,'tcp':53}[p.scheme]
        if not 1<=port<=65535:raise ValueError('Недопустимый DNS порт.')
        if p.scheme!='https' and (p.path not in ('','/') or p.query):raise ValueError('Путь разрешён только для DoH.')
        return cls(p.scheme,p.hostname,port,(p.path or '/dns-query')+('?' + p.query if p.query else ''))


def import_mobileconfig(data):
    if len(data)>2*1024*1024:raise ValueError('Слишком большой профиль DNS.')
    try:profile=plistlib.loads(data)
    except Exception as exc:raise ValueError('Нужен XML/binary plist .mobileconfig. Подписанный CMS-профиль сначала экспортируйте в plist.') from exc
    result=[]
    def visit(value):
        if isinstance(value,list):
            for v in value:visit(v)
        if not isinstance(value,dict):return
        settings=value.get('DNSSettings',{})
        if isinstance(settings,dict):
            protocol=settings.get('DNSProtocol')
            if protocol=='HTTPS' and settings.get('ServerURL'):result.append(settings['ServerURL'])
            elif protocol=='TLS' and settings.get('ServerName'):result.append('tls://'+settings['ServerName'])
            elif not protocol:
                for addr in settings.get('ServerAddresses',[]):result.append('udp://'+str(ipaddress.ip_address(addr)))
        if 'PayloadContent' in value:visit(value['PayloadContent'])
    visit(profile)
    for endpoint in result:Endpoint.parse(endpoint)
    if not result:raise ValueError('В профиле нет поддерживаемых DNSSettings.')
    return list(dict.fromkeys(result))


def question(host, padding=False):
    name=host.rstrip('.').encode('idna')
    labels=name.split(b'.')
    if len(name)>253 or any(not x or len(x)>63 for x in labels):raise ValueError('Некорректное DNS имя.')
    transaction=secrets.token_bytes(2)
    wire=transaction+struct.pack('!HHHHH',0x100,1,0,0,int(padding))
    wire+=b''.join(bytes([len(x)])+x for x in labels)+b'\0\0\1\0\1'
    if padding:
        count=(-len(wire)-15)%128
        wire+=b'\0'+struct.pack('!HHIH',41,1232,0,count+4)+struct.pack('!HH',12,count)+b'\0'*count
    return wire


def read_name(data, offset):
    labels=[];end=None;seen=set()
    for _ in range(128):
        if offset in seen or offset>=len(data):raise ValueError('Повреждённое DNS имя.')
        seen.add(offset);size=data[offset];offset+=1
        if size==0:return b'.'.join(labels).decode('ascii').lower(), end or offset
        if size&0xc0==0xc0:
            if offset>=len(data):raise ValueError('Обрезанный DNS указатель.')
            end=end or offset+1;offset=((size&63)<<8)|data[offset];continue
        if size>63 or offset+size>len(data):raise ValueError('Обрезанная DNS метка.')
        labels.append(data[offset:offset+size]);offset+=size
    raise ValueError('Слишком длинное DNS имя.')


def answer(data, query):
    if len(data)<12 or data[:2]!=query[:2]:raise ValueError('DNS transaction mismatch.')
    flags,qd,an,_,_=struct.unpack('!HHHHH',data[2:12])
    if not flags&0x8000 or flags&0x200 or flags&15 or qd!=1 or an>512:raise ValueError('DNS вернул ошибку/обрезанный ответ.')
    expected,_=read_name(query,12);actual,offset=read_name(data,12)
    if actual!=expected or data[offset:offset+4]!=b'\0\1\0\1':raise ValueError('DNS question mismatch.')
    offset+=4;records=[];aliases={};ttl=300
    for _ in range(an):
        owner,offset=read_name(data,offset)
        if offset+10>len(data):raise ValueError('Обрезанный DNS ответ.')
        kind,cls,life,size=struct.unpack('!HHIH',data[offset:offset+10]);offset+=10
        if offset+size>len(data):raise ValueError('Обрезанный DNS RDATA.')
        if cls==1:
            if kind==5:
                alias,_=read_name(data,offset);aliases[owner]=alias;ttl=min(ttl,life)
            if kind==1 and size==4:records.append((owner,str(ipaddress.ip_address(data[offset:offset+4])),life))
        offset+=size
    owners={expected}
    for _ in range(16):
        old=len(owners);owners.update(aliases[x] for x in list(owners) if x in aliases)
        if len(owners)==old:break
    for owner,addr,life in records:
        if owner in owners and ipaddress.ip_address(addr).is_global:return addr,max(1,min(ttl,life,300))
    raise ValueError('DNS не вернул публичный IPv4 для запрошенного имени.')


def read_exact(sock, count):
    data=bytearray()
    while len(data)<count:
        chunk=sock.recv(count-len(data))
        if not chunk:raise ConnectionError('Обрезанный DNS stream.')
        data.extend(chunk)
    return bytes(data)


def exchange(endpoint, wire, timeout=2.5, address=None):
    ep=Endpoint.parse(endpoint);destination=address or ep.host
    if ep.scheme=='https':
        class Connection(http.client.HTTPSConnection):
            def connect(self):
                self.sock=socket.create_connection((destination,ep.port),self.timeout)
                try:self.sock=self._context.wrap_socket(self.sock,server_hostname=ep.host)
                except BaseException:self.sock.close();raise
        conn=Connection(ep.host,ep.port,timeout=timeout,context=ssl.create_default_context())
        try:
            conn.request('POST',ep.path,wire,{'Content-Type':'application/dns-message','Accept':'application/dns-message'})
            res=conn.getresponse();data=res.read(65536)
            if res.status!=200 or len(data)>65535:raise ValueError('DoH HTTP '+str(res.status))
            if res.getheader('Content-Type','').split(';')[0].lower()!='application/dns-message':raise ValueError('Неверный MIME DoH.')
            return data
        finally:conn.close()
    family=socket.AF_INET6 if ':' in destination else socket.AF_INET
    if ep.scheme=='udp':
        with socket.socket(family,socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout);sock.connect((destination,ep.port));sock.send(wire);data=sock.recv(65535)
        if len(data)>3 and data[2]&2:return exchange('tcp://'+('['+ep.host+']' if ':' in ep.host else ep.host)+':'+str(ep.port),wire,timeout,address)
        return data
    with socket.create_connection((destination,ep.port),timeout=timeout) as raw:
        stream=ssl.create_default_context().wrap_socket(raw,server_hostname=ep.host) if ep.scheme=='tls' else raw
        try:
            stream.sendall(struct.pack('!H',len(wire))+wire)
            return read_exact(stream,struct.unpack('!H',read_exact(stream,2))[0])
        finally:
            if stream is not raw:stream.close()


class Resolver:
    def __init__(self,endpoints=None,padding=False):
        self.endpoints=endpoints or DEFAULT_ENDPOINTS;self.padding=padding;self.cache={};self.failed={};self.lock=threading.Lock()
        for value in self.endpoints:Endpoint.parse(value)

    def resolve(self,host):
        with self.lock:
            saved=self.cache.get(host)
            if saved and saved[1]>time.monotonic():return saved[0]
        wire=question(host,self.padding);deadline=time.monotonic()+12
                                                                                      
        for endpoint in self.endpoints:
            ep=Endpoint.parse(endpoint);nodes=SEEDS.get(ep.host,[ep.host])
            with self.lock:nodes=sorted(nodes,key=lambda n:self.failed.get((endpoint,n),0)>time.monotonic())
            for node in nodes:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Smart DNS: истёк срок ответа.')
                try:
                    ip,ttl=answer(exchange(endpoint,wire,min(1.5,remaining),node),wire)
                    with self.lock:self.cache[host]=(ip,time.monotonic()+ttl);self.failed.pop((endpoint,node),None)
                    return ip
                except (OSError,ValueError,http.client.HTTPException):
                    with self.lock:self.failed[(endpoint,node)]=time.monotonic()+30
        raise ConnectionError('Выбранные Smart DNS не ответили; проверьте DNS-узлы или upstream.')

    def probe(self,host='cloudcode-pa.googleapis.com'):
        rows=[]
        for endpoint in self.endpoints:
            start=time.monotonic()
            try:
                ip,_=answer(exchange(endpoint,question_wire:=question(host),2.5),question_wire)
                rows.append(f'{endpoint}: {ip}, {(time.monotonic()-start)*1000:.0f} мс')
            except Exception as exc:rows.append(f'{endpoint}: ошибка — {exc}')
        return '\n'.join(rows)
