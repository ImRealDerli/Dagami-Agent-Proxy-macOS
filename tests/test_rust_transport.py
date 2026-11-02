import hashlib,os,socket,ssl,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg.core.rust_transport import RustTransport


@unittest.skipUnless(os.name=='posix' and os.environ.get('DAGAMI_TEST_RUST_BINARY'),'Explicit Rust fixture binary required')
class RustTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.cert=self.root/'cert.pem';key=self.root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(self.cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],check=True,capture_output=True)
        self.context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);self.context.load_cert_chain(self.cert,key)
        env=patch.dict(os.environ,{'DAGAMI_NETWORK_BINARY':os.environ['DAGAMI_TEST_RUST_BINARY'],'SSL_CERT_FILE':str(self.cert),'DEVPROXY_HOME':str(self.root)})
        env.start();self.addCleanup(env.stop);self.transport=RustTransport();self.addCleanup(self.transport.close)
    def server(self,tls=False):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(8);errors=[]
        def echo():
            try:
                peer=listener.accept()[0];peer.settimeout(8)
                if tls:peer=self.context.wrap_socket(peer,server_side=True)
                with peer:
                    while True:
                        data=peer.recv(65536)
                        if not data:break
                        peer.sendall(data)
            except ssl.SSLError:
                if not tls:errors.append('unexpected TLS')
            except OSError:pass
            finally:listener.close()
        worker=threading.Thread(target=echo,daemon=True);worker.start();return listener.getsockname()[1],worker,errors
    def exchange(self,tls,fragment=0):
        port,worker,errors=self.server(tls);payload=os.urandom(2*1024*1024);seen=bytearray();fail=[]
        with self.transport.connect('localhost',port,tls=tls,fragment=fragment) as peer:
            self.assertEqual(socket.AF_UNIX,peer.family)
            def upload():
                try:peer.sendall(payload);peer.shutdown(socket.SHUT_WR)
                except OSError as error:fail.append(error)
            sender=threading.Thread(target=upload);sender.start()
            while len(seen)<len(payload):
                data=peer.recv(65536)
                if not data:break
                seen.extend(data)
            sender.join(8);self.assertFalse(sender.is_alive());self.assertEqual([],fail)
        worker.join(8);self.assertFalse(worker.is_alive());self.assertEqual([],errors);self.assertEqual(len(payload),len(seen));self.assertEqual(hashlib.sha256(payload).digest(),hashlib.sha256(seen).digest())
    def test_large_plain_stream_and_ipv6_to_ipv4_fallback(self):self.exchange(False)
    def test_large_verified_tls_stream_and_half_close(self):self.exchange(True)
    def test_wrong_certificate_name_is_rejected(self):
        port,worker,_=self.server(True)
        with self.assertRaisesRegex(ConnectionError,'TLS'):
            self.transport.connect('127.0.0.1',port,tls=True)
        worker.join(8);self.assertFalse(worker.is_alive())
    def test_failed_connect_is_reported_and_service_stays_available(self):
        with socket.socket() as unused:unused.bind(('127.0.0.1',0));port=unused.getsockname()[1]
        with self.assertRaises(ConnectionError):self.transport.connect('127.0.0.1',port,timeout=.5)
        self.assertIsNone(self.transport.process.poll())
    def test_close_stops_worker_and_removes_private_socket(self):
        self.transport.start();process=self.transport.process;directory=self.transport.directory
        self.assertEqual(0o700,directory.stat().st_mode&0o777)
        self.assertEqual(0o600,self.transport.socket_path.stat().st_mode&0o777)
        self.transport.close();self.assertIsNotNone(process.poll());self.assertFalse(directory.exists())

    def proxy_exchange(self,protocol,retry=False):
        from devproxy_pkg.core.profile import ProxyProfile
        from devproxy_pkg.core.tunnel import LocalTunnel
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(8)
        port=listener.getsockname()[1];seen=[];errors=[]
        def exact(peer,count):
            result=bytearray()
            while len(result)<count:
                data=peer.recv(count-len(result))
                if not data:raise ConnectionError('Truncated proxy fixture')
                result.extend(data)
            return bytes(result)
        def serve():
            try:
                for attempt in range(2 if retry else 1):
                    peer=listener.accept()[0];peer.settimeout(8)
                    if protocol=='https':peer=self.context.wrap_socket(peer,server_side=True)
                    with peer:
                        if protocol.startswith('socks'):
                            version,count=exact(peer,2);self.assertEqual(5,version);self.assertIn(2,exact(peer,count));peer.sendall(b'\x05');peer.sendall(b'\x02')
                            version,count=exact(peer,2);self.assertEqual(1,version);self.assertEqual(b'fixture',exact(peer,count))
                            count=exact(peer,1)[0];self.assertEqual(b'password',exact(peer,count));peer.sendall(b'\x01\x00')
                            self.assertEqual(b'\x05\x01\x00\x03',exact(peer,4));count=exact(peer,1)[0]
                            self.assertEqual(b'fixture.example',exact(peer,count));self.assertEqual(b'\x01\xbb',exact(peer,2))
                            peer.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x01');seen.append(True)
                        else:
                            head=bytearray()
                            while not head.endswith(b'\r\n\r\n'):head.extend(exact(peer,1))
                            seen.append(b'Proxy-Authorization: Basic Zml4dHVyZTpwYXNzd29yZA==' in head)
                            if retry and attempt==0:peer.sendall(b'HTTP/1.1 503 Busy\r\nContent-Length: 0\r\n\r\n');continue
                            peer.sendall(b'HTTP/1.1 200 Established\r\n\r\n')
                        while True:
                            data=peer.recv(65536)
                            if not data:break
                            peer.sendall(data)
            except BaseException as error:errors.append(error)
            finally:listener.close()
        worker=threading.Thread(target=serve,daemon=True);worker.start()
        profile=ProxyProfile('fixture',protocol,'localhost',port,'fixture','password');tunnel=LocalTunnel(profile)
        payload=os.urandom(2*1024*1024);received=bytearray();upload_errors=[]
        try:
            local=tunnel.start()
            with socket.create_connection(('127.0.0.1',local),timeout=10) as client:
                client.sendall(b'CONNECT fixture.example:443 HTTP/1.1\r\nHost: fixture.example:443\r\n\r\n');head=bytearray()
                while not head.endswith(b'\r\n\r\n'):head.extend(exact(client,1))
                self.assertIn(b' 200 ',head)
                def upload():
                    try:client.sendall(payload);client.shutdown(socket.SHUT_WR)
                    except OSError as error:upload_errors.append(error)
                sender=threading.Thread(target=upload);sender.start()
                while len(received)<len(payload):
                    data=client.recv(65536)
                    if not data:break
                    received.extend(data)
                sender.join(10);self.assertFalse(sender.is_alive());self.assertEqual([],upload_errors)
            worker.join(10);self.assertFalse(worker.is_alive());self.assertEqual([],errors)
            self.assertEqual(len(payload),len(received));self.assertEqual(hashlib.sha256(payload).digest(),hashlib.sha256(received).digest());self.assertTrue(all(seen));self.assertEqual(2 if retry else 1,len(seen))
            self.assertIsNotNone(tunnel.transport.process)
        finally:tunnel.stop();listener.close();worker.join(2)
    def test_http_proxy_credentials_and_large_stream_use_rust(self):self.proxy_exchange('http')
    def test_https_proxy_reconnects_503_without_replaying_payload(self):self.proxy_exchange('https',retry=True)
    def test_socks5_credentials_and_large_stream_use_rust(self):self.proxy_exchange('socks5h')

    def test_fragmented_native_tls_keeps_certificates_and_stream_intact(self):self.exchange(True,fragment=8)
