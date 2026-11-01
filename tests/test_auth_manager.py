import os,sys,tempfile,time,json,http.client,subprocess
from pathlib import Path
import unittest
from unittest.mock import patch,MagicMock
from devproxy_pkg.auth_manager import validate_url,auth_urls,find_link,AuthSession,AuthManager
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.macos_activation import License,ACCOUNT
from devproxy_pkg import journal

URL='https://auth.openai.com/oauth/authorize?client_id=fixture&state=a%2Bb&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback'

class LinkTests(unittest.TestCase):
    def test_preserves_original_oauth_query_and_callback(self):
        self.assertEqual(URL,validate_url(URL,'codex'));self.assertEqual([URL],auth_urls('Open browser:\n'+URL+'\n','codex'))
    def test_rejects_untrusted_hosts_local_links_and_shell_characters(self):
        for value in ('https://auth.openai.com.evil.example/oauth','http://auth.openai.com/oauth','https://user:pass@auth.openai.com/oauth','https://auth.openai.com:8443/oauth','https://auth.openai.com/oauth\nInjected','https://evil.example/oauth'):
            with self.assertRaises(ValueError):validate_url(value,'codex')
        for value in ('https://127.0.0.1/login','https://localhost/login','https://192.168.0.1/login'):
            with self.assertRaises(ValueError):validate_url(value,'custom',manual=True)
    def test_only_fresh_bounded_client_logs_are_used(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'.codex/log/codex-login.log';path.parent.mkdir(parents=True);path.write_text(URL)
            self.assertEqual(URL,find_link('codex',root));self.assertEqual('',find_link('claude',root))
            os.utime(path,(time.time()-1000,time.time()-1000));self.assertEqual('',find_link('codex',root))
    def test_auth_urls_and_codes_are_never_written_to_journal(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            journal.append('authStart',True,URL+' CODE ABCD-EFGH');journal.append('authStatus',True,URL)
            data=journal.read();self.assertNotIn(URL,data);self.assertNotIn('ABCD-EFGH',data)

class LicenseResetTests(unittest.TestCase):
    def test_reset_only_targets_dagami_activation(self):
        with patch('devproxy_pkg.macos_activation.MacOSKeychainStore.delete_password',return_value=True) as delete,patch('devproxy_pkg.macos_activation.MacOSKeychainStore.get_password',return_value=None):
            License.deactivate();delete.assert_called_once_with(ACCOUNT)
    def test_reset_reports_keychain_refusal(self):
        with patch('devproxy_pkg.macos_activation.MacOSKeychainStore.delete_password',return_value=False):
            with self.assertRaises(RuntimeError):License.deactivate()

class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        route=patch('devproxy_pkg.auth_manager.verify_route');route.start();self.addCleanup(route.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'DEVPROXY_HOME':self.temp.name});env.start();self.addCleanup(env.stop)
        profile=patch('devproxy_pkg.auth_manager.load_profile',return_value=ProxyProfile.parse('direct://'));profile.start();self.addCleanup(profile.stop)
    def session(self):
        session=AuthSession('codex','fixture',mode='cli');self.addCleanup(session.close);return session
    def test_browser_uses_same_bridge_keeps_callback_local_and_deduplicates_url(self):
        s=self.session()
        with patch('devproxy_pkg.auth_manager._browser',return_value='/fixture/browser'),patch('devproxy_pkg.auth_manager.Launcher.launch') as launch:
            launch.return_value.pid=99999999;launch.return_value.poll.return_value=None;launch.return_value.wait.side_effect=subprocess.TimeoutExpired('fixture',.3)
            s.open_url(URL);s.open_url(URL)
        self.assertEqual(1,launch.call_count);args=launch.call_args.args[1]
        self.assertIn('--proxy-server='+s.local,args);self.assertIn('--proxy-bypass-list=localhost;127.0.0.1;[::1]',args);self.assertEqual(URL,args[-1])
        s.browser_processes=[]
    def test_capture_endpoint_requires_token_and_preserves_url(self):
        s=self.session();s.start_capture_server()
        with patch.object(s,'open_url') as open_url:
            for token,status in (('invalid',403),(s.token,200)):
                c=http.client.HTTPConnection('127.0.0.1',s.capture.server_port,timeout=5)
                c.request('POST','/capture',json.dumps({'url':URL}),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                r=c.getresponse();r.read();self.assertEqual(status,r.status);c.close()
            open_url.assert_called_once_with(URL)
    def test_native_cli_open_hook_intercepts_without_default_browser(self):
        s=self.session();exe=Path(self.temp.name)/'fixture-cli'
        exe.write_text('#!'+sys.executable+'\nimport subprocess\nsubprocess.run(["open",'+repr(URL)+'],check=True)\n')
        exe.chmod(0o700)
        with patch('devproxy_pkg.auth_manager.executable',return_value=str(exe)),patch.object(s,'open_url') as opened:
            s.start();deadline=time.monotonic()+8
            while s.process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            self.assertEqual(0,s.process.poll());opened.assert_called_once_with(URL)
    def test_manager_closes_previous_session_without_logging_out_accounts(self):
        manager=AuthManager();old=MagicMock();manager.session=old
        with patch('devproxy_pkg.auth_manager.AuthSession') as cls:
            cls.return_value.start.return_value={'running':True}
            manager.start('codex','fixture','cli')
            old.close.assert_called_once();cls.return_value.start.assert_called_once()
