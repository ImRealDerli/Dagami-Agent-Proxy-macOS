
import io
import os
from pathlib import Path
import plistlib
import socket
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from devproxy_pkg.macos_activation import validate,License
from devproxy_pkg.macos_backend import patch_data,PATTERNS
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.core.smart_dns import question,answer,Endpoint,scoped,import_mobileconfig,Resolver
from devproxy_pkg.core.tunnel import LocalTunnel
from devproxy_pkg.core.recovery import StateManager
from devproxy_pkg import macos_login


class ActivationTests(unittest.TestCase):
    def test_native_csharp_vectors(self):
        for value in ('DAGAMI-TEST-9999-XVSF','dagami test 9999 xvsf','DAGAMITEST9999XVSF'):
            self.assertTrue(validate(value))
        for value in ('',None,'DAGAMI-TEST-9999-XXXX','OTHER-TEST-9999-XVSF','DAGAMI-01OI-9999-XVSF'):
            self.assertFalse(validate(value))

    def test_invalid_key_never_touches_keychain(self):
        with patch('devproxy_pkg.macos_activation.MacOSKeychainStore.set_password') as store:
            with self.assertRaises(ValueError):License.activate('invalid')
            store.assert_not_called()

    def test_keychain_refusal_is_not_success(self):
        with patch('devproxy_pkg.macos_activation.MacOSKeychainStore.set_password',return_value=False):
            with self.assertRaises(RuntimeError):License.activate('DAGAMI-TEST-9999-XVSF')

    def test_autostart_does_not_show_activation(self):
        from devproxy_pkg.macos_activation import ensure_activation
        with patch.object(License,'activated',return_value=False),patch('tkinter.Tk') as root:
            self.assertFalse(ensure_activation(True));root.assert_not_called()


class PatchTests(unittest.TestCase):
    def test_all_eight_patterns_and_private_proxy_env_preserve_length(self):
        source=b'header\0'+b'\0'.join(PATTERNS)+b'\0https_proxy\0tail'
        result=patch_data(source)
        self.assertEqual(len(source),len(result));self.assertIn(b'AG_LS_PROXY',result)
        for p in PATTERNS:self.assertIn(p.replace(b'ineligible',b'dpeligible'),result)
        self.assertIn(PATTERNS[0],source)

    def test_partial_duplicate_and_unknown_shapes_rejected(self):
        source=b'\0'.join(PATTERNS)
        for value in (source.replace(PATTERNS[0],b'unknown'),source+PATTERNS[0],b'unknown',patch_data(source)):
            with self.assertRaises(ValueError):patch_data(value)


class DnsTests(unittest.TestCase):
    def fixture(self,host='cloudcode-pa.googleapis.com',ip=b'\x08\x08\x08\x08'):
        q=question(host)
        response=q[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+q[12:]+b'\xc0\x0c'+struct.pack('!HHIH',1,1,120,4)+ip
        return q,response
    def test_compressed_answer_and_ttl(self):
        q,response=self.fixture();self.assertEqual(('8.8.8.8',120),answer(response,q))
    def test_transaction_private_question_and_truncation_rejected(self):
        q,response=self.fixture()
        for bad in (b'xx'+response[2:],response[:-1],response[:2]+b'\x83'+response[3:]):
            with self.assertRaises(ValueError):answer(bad,q)
        q,response=self.fixture(ip=b'\x7f\0\0\1')
        with self.assertRaises(ValueError):answer(response,q)
        q,response=self.fixture()
        with self.assertRaises(ValueError):answer(response,question('other.example'))
    def test_unrelated_address_rejected(self):
        q=question('cloudcode-pa.googleapis.com');other=question('other.example')[12:-4]
        data=q[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+q[12:]+other+struct.pack('!HHIH',1,1,120,4)+b'\x08\x08\x08\x08'
        with self.assertRaises(ValueError):answer(data,q)
    def test_edns_padding_1232_and_block_alignment(self):
        wire=question('cloudcode-pa.googleapis.com',True)
        self.assertEqual(0,len(wire)%128);self.assertEqual(1,struct.unpack('!H',wire[10:12])[0]);self.assertIn(struct.pack('!HH',41,1232),wire)
    def test_scope_exact_and_dns_only_account_route(self):
        self.assertTrue(scoped('cloudcode-pa.googleapis.com'));self.assertFalse(scoped('evil.cloudcode-pa.googleapis.com'))
        self.assertTrue(scoped('accounts.google.com'));self.assertFalse(scoped('accounts.google.com',True))
        self.assertTrue(scoped('aicode.googleapis.com',True))
    def test_endpoint_validation(self):
        for value in ('https://dns.example/dns-query','tls://dns.example','udp://[::1]:5353','tcp://127.0.0.1:53'):
            self.assertTrue(Endpoint.parse(value).port)
        for value in ('file:///tmp/dns','http://dns.example','https://user:pass@dns.example','udp://dns.example/path','https://dns.example\nInjected: x'):
            with self.assertRaises(ValueError):Endpoint.parse(value)
    def test_mobileconfig_nested_import_does_not_install(self):
        data=plistlib.dumps({'PayloadContent':[{'DNSSettings':{'DNSProtocol':'HTTPS','ServerURL':'https://dns.example/dns-query'}}]})
        self.assertEqual(['https://dns.example/dns-query'],import_mobileconfig(data))
        with self.assertRaises(ValueError):import_mobileconfig(b'bad')
    def test_failover_and_cache_preserve_provider_order(self):
        calls=[]
        def exchange(ep,q,*args):
            calls.append(ep)
            if 'first' in ep:raise OSError('fixture unavailable')
            return q[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+q[12:]+b'\xc0\x0c'+struct.pack('!HHIH',1,1,120,4)+b'\x08\x08\x08\x08'
        with patch('devproxy_pkg.core.smart_dns.exchange',side_effect=exchange):
            r=Resolver(['udp://first.example','udp://second.example'])
            self.assertEqual('8.8.8.8',r.resolve('cloudcode-pa.googleapis.com'));self.assertEqual('8.8.8.8',r.resolve('cloudcode-pa.googleapis.com'))
        self.assertEqual(['udp://first.example','udp://second.example'],calls)


class FakeSocket:
    def __init__(self,data=b''):self.data=data;self.sent=bytearray()
    def recv(self,n):data=self.data[:n];self.data=self.data[n:];return data
    def sendall(self,data):self.sent.extend(data)
    def settimeout(self,*args):pass
    def setsockopt(self,*args):pass
    def close(self):pass


class RouteTests(unittest.TestCase):
    def setUp(self):
        peer=patch("devproxy_pkg.core.tunnel.is_current_user",return_value=True);peer.start();self.addCleanup(peer.stop)
    def call(self,profile,request,upstream=None):
        tunnel=LocalTunnel(profile);tunnel.is_running=True;client=FakeSocket(request);upstream=upstream or FakeSocket(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        with patch('devproxy_pkg.core.tunnel.socket.create_connection',return_value=upstream) as connect,patch('devproxy_pkg.core.tunnel.FastDuplexRelay.pipe'):
            tunnel._handle_client(client)
        return client,upstream,connect
    def test_direct_http_strips_proxy_credentials_and_uses_origin_form(self):
        profile=ProxyProfile.parse('direct://')
        client,upstream,connect=self.call(profile,b'GET http://example.com/path HTTP/1.1\r\nHost: example.com\r\nProxy-Authorization: Basic secret\r\n\r\n')
        self.assertEqual(('example.com',80),connect.call_args.args[0]);self.assertTrue(upstream.sent.startswith(b'GET /path '));self.assertNotIn(b'secret',upstream.sent)
    def test_disabled_upstream_preserves_credentials_but_routes_direct(self):
        profile=ProxyProfile.parse('http://user:secret@proxy.example:8080');profile.proxy_enabled=False
        _,_,connect=self.call(profile,b'CONNECT example.com:443 HTTP/1.1\r\n\r\n')
        self.assertEqual(('example.com',443),connect.call_args.args[0]);self.assertEqual('secret',profile.password)
    def test_metadata_local_404_and_update_block(self):
        profile=ProxyProfile.parse('direct://');profile.block_updates=True
        for host,code in [('metadata.google.internal',b'404'),('antigravity-auto-updater-974169037036.us-central1.run.app',b'403')]:
            client,_,connect=self.call(profile,('GET http://'+host+'/ HTTP/1.1\r\nHost: '+host+'\r\n\r\n').encode())
            self.assertIn(code,client.sent);connect.assert_not_called()
    def test_setup_manifest_hosts_are_not_blocked_as_optional_updates(self):
        profile=ProxyProfile.parse('http://proxy.example:8080');profile.block_updates=True
        for suffix in ('cli-auto-updater','ide-auto-updater'):
            host='antigravity-'+suffix+'-974169037036.us-central1.run.app'
            client,upstream,connect=self.call(profile,('CONNECT '+host+':443 HTTP/1.1\r\n\r\n').encode(),FakeSocket(b'HTTP/1.1 200 OK\r\n\r\n'))
            self.assertIn(b'200',client.sent);connect.assert_called_once()

    def test_failed_upstream_never_falls_back_direct(self):
        profile=ProxyProfile.parse('http://proxy.example:8080');t=LocalTunnel(profile);t.is_running=True;client=FakeSocket(b'CONNECT example.com:443 HTTP/1.1\r\n\r\n')
        with patch('devproxy_pkg.core.tunnel.socket.create_connection',side_effect=OSError('fixture')) as connect:t._handle_client(client)
        self.assertIn(b'502',client.sent);self.assertEqual(1,connect.call_count);self.assertEqual(('proxy.example',8080),connect.call_args.args[0])
    def test_smart_dns_failure_uses_upstream_before_tunnel_open(self):
        profile=ProxyProfile.parse('http://proxy.example:8080');profile.smart_dns=True;t=LocalTunnel(profile);t.is_running=True
        client=FakeSocket(b'CONNECT cloudcode-pa.googleapis.com:443 HTTP/1.1\r\n\r\n');upstream=FakeSocket(b'HTTP/1.1 200 OK\r\n\r\n')
        with patch.object(t.resolver,'resolve',side_effect=OSError('DNS down')),patch('devproxy_pkg.core.tunnel.socket.create_connection',return_value=upstream) as connect,patch('devproxy_pkg.core.tunnel.FastDuplexRelay.pipe'):t._handle_client(client)
        self.assertEqual(('proxy.example',8080),connect.call_args.args[0]);self.assertIn(b'200',client.sent)
    def test_smart_dns_target_preserves_connect_hostname(self):
        profile=ProxyProfile.parse('direct://');profile.smart_dns=True;t=LocalTunnel(profile);t.is_running=True
        client=FakeSocket(b'CONNECT cloudcode-pa.googleapis.com:443 HTTP/1.1\r\n\r\n');upstream=FakeSocket()
        with patch.object(t.resolver,'resolve',return_value='8.8.8.8'),patch('devproxy_pkg.core.tunnel.socket.create_connection',return_value=upstream) as connect,patch('devproxy_pkg.core.tunnel.FastDuplexRelay.pipe'):t._handle_client(client)
        self.assertEqual(('8.8.8.8',443),connect.call_args.args[0]);self.assertIn(b'200',client.sent)


class LoginTests(unittest.TestCase):
    def test_only_recent_antigravity_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'Library/Application Support/Antigravity IDE/logs/session/auth.log';path.parent.mkdir(parents=True)
            url='https://accounts.google.com/o/oauth2/auth?client_id=fixture&redirect_uri=http%3A%2F%2Flocalhost%3A9&state=nonce'
            path.write_text(url)
            self.assertEqual(url,macos_login.fresh_url(temp))
            os.utime(path,(time.time()-1000,time.time()-1000));self.assertEqual('',macos_login.fresh_url(temp))
    def test_account_choice_preserves_oauth_state_and_redirect(self):
        from urllib.parse import parse_qs,urlsplit
        url=macos_login.choose_account('https://accounts.google.com/o/oauth2/auth?state=a%2Bb&redirect_uri=http%3A%2F%2Flocalhost%3A9&prompt=consent')
        q=parse_qs(urlsplit(url).query);self.assertEqual(['a+b'],q['state']);self.assertEqual(['select_account'],q['prompt']);self.assertEqual(['http://localhost:9'],q['redirect_uri'])



class IntegrityTests(unittest.TestCase):
    def test_damaged_prepared_backend_does_not_announce_restore_success(self):
        from devproxy_pkg import macos_backend as backend
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}),patch('devproxy_pkg.portable_runtime.request',return_value=None):
            original=Path(temp)/'original';original.write_text('original')
            bundle=Path(temp)/'prepared-macos'/'fixture'/'Editor.app';exe=bundle/'Contents/MacOS/Editor';exe.parent.mkdir(parents=True);exe.write_text('damaged')
            record={'bundle':str(bundle),'executable':str(exe),'original':str(original),'backends':{'Contents/MacOS/Editor':'0'*64}}
            StateManager.save_state({'profiles':{},'applied':{},'prepared_macos':{'antigravity':record}})
            with self.assertRaisesRegex(RuntimeError,'SHA-256'):backend.restore('antigravity')
            self.assertEqual(record,backend.record('antigravity'));self.assertEqual('original',original.read_text());self.assertTrue(exe.exists())

    def test_tls_fragmentation_preserves_content(self):
        class Stream:
            def __init__(self,data=b''):self.data=[data,b''];self.writes=[]
            def recv(self,*args):return self.data.pop(0)
            def sendall(self,value):self.writes.append(value)
            def setsockopt(self,*args):pass
            def setblocking(self,*args):pass
            def shutdown(self,*args):pass
            def close(self):pass
        from devproxy_pkg.core.transport import FastDuplexRelay
        payload=b'\x16\x03\x03fixture-client-hello'
        client=Stream(payload);remote=Stream()
        FastDuplexRelay.pipe(client,remote,8)
        self.assertEqual(payload,b''.join(remote.writes));self.assertGreater(len(remote.writes),1)


if __name__=='__main__':unittest.main()
