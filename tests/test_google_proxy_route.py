import socket,socketserver,threading,unittest
from unittest.mock import patch
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.core.tunnel import LocalTunnel

class GoogleGatewayTests(unittest.TestCase):
    def exchange(self,host='accounts.google.ru',port=443,provider='test-dns.dagami.ru',first=403,alias=200):
        requests=[];dialed=[];original=socket.create_connection
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(3);header=b''
                while b'\r\n\r\n' not in header:
                    chunk=self.request.recv(4096)
                    if not chunk:return
                    header+=chunk
                target=header.split(b' ',2)[1].decode();requests.append((target,b'Proxy-Authorization: Basic Zml4dHVyZTpzZWNyZXQ=' in header))
                code=alias if target=='accounts.google.com:443' else first
                self.request.sendall(('HTTP/1.1 '+str(code)+' Result\r\nContent-Length: 0\r\n\r\n').encode())
                if code==200:
                    payload=self.request.recv(4096)
                    if payload:self.request.sendall(payload)
        class Server(socketserver.ThreadingTCPServer):daemon_threads=True
        server=Server(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def connect(address,*args,**kwargs):
            if address[0]==provider:
                dialed.append(address);return original(('127.0.0.1',server.server_address[1]),*args,**kwargs)
            return original(address,*args,**kwargs)
        profile=ProxyProfile(name='fixture',protocol='http',host=provider,port=server.server_address[1],username='fixture',password='secret')
        tunnel=LocalTunnel(profile)
        try:
            with patch('devproxy_pkg.core.tunnel.socket.create_connection',side_effect=connect):
                local=tunnel.start()
                with original(('127.0.0.1',local),timeout=5) as client:
                    client.sendall(f'CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n'.encode());response=b''
                    while b'\r\n\r\n' not in response:response+=client.recv(4096)
                    status=int(response.split()[1])
                    if status==200:
                        payload=b'opaque-original-TLS-SNI-and-HTTP-Host-bytes';client.sendall(payload);echo=b''
                        while len(echo)<len(payload):echo+=client.recv(4096)
                        self.assertEqual(payload,echo)
                self.assertTrue(all(target==(provider,server.server_address[1]) for target in dialed))
            return status,requests,dialed
        finally:tunnel.stop();server.shutdown();server.server_close();thread.join(timeout=2)
    def test_regional_403_retries_same_gateway_and_preserves_inner_tls_bytes(self):
        status,requests,dialed=self.exchange();self.assertEqual(200,status);self.assertEqual([('accounts.google.ru:443',True),('accounts.google.com:443',True)],requests);self.assertEqual(2,len(dialed))
    def test_successful_original_domain_is_not_changed(self):
        status,requests,dialed=self.exchange(first=200);self.assertEqual(200,status);self.assertEqual([('accounts.google.ru:443',True)],requests)
    def test_other_proxy_forbidden_response_is_preserved(self):
        status,requests,dialed=self.exchange(provider='custom.proxy');self.assertEqual(403,status);self.assertEqual(1,len(requests))
    def test_other_destination_forbidden_response_is_preserved(self):
        status,requests,dialed=self.exchange(host='other.google.ru');self.assertEqual(403,status);self.assertEqual(1,len(requests))
    def test_plain_http_port_is_not_mapped(self):
        status,requests,dialed=self.exchange(port=80);self.assertEqual(403,status);self.assertEqual(1,len(requests))
    def test_failed_alias_is_not_replaced_with_direct_connection(self):
        status,requests,dialed=self.exchange(alias=403);self.assertEqual(403,status);self.assertEqual(2,len(dialed))
    def test_authentication_failure_does_not_trigger_mapping(self):
        status,requests,dialed=self.exchange(first=407);self.assertEqual(407,status);self.assertEqual(1,len(requests))
