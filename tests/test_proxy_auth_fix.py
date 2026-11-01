
import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.core.validator import ProxyValidator
from devproxy_pkg.core.secrets import SecretStore,EphemeralStore,MacOSKeychainStore
from devproxy_pkg.core.recovery import StateManager
from devproxy_pkg.macos_credentials import update_credentials


class Socket:
    def __init__(self,scheme='Basic'):self.sent=b'';self.scheme=scheme
    def sendall(self,data):self.sent+=data
    def recv(self,*args):return ('HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: '+self.scheme+' realm="private"\r\n\r\n').encode()
    def close(self):pass


class AuthTests(unittest.TestCase):
    def test_basic_preserves_special_characters_and_unicode_without_url_parsing(self):
        sock=Socket();profile=ProxyProfile('fixture','http','proxy.example',8080,'fixture-user','p#@:%/пароль')
        with patch('devproxy_pkg.core.validator.socket.create_connection',return_value=sock):
            ok,auth,tls,error=ProxyValidator.test_http_proxy(profile)
        expected=base64.b64encode('fixture-user:p#@:%/пароль'.encode())
        self.assertIn(b'Proxy-Authorization: Basic '+expected+b'\r\n',sock.sent)
        self.assertFalse(ok);self.assertIn('пароль задан',error);self.assertNotIn(profile.password,error);self.assertNotIn(profile.username,error)

    def test_ntlm_is_reported_as_unsupported_authentication(self):
        with patch('devproxy_pkg.core.validator.socket.create_connection',return_value=Socket('NTLM')):
            *_,error=ProxyValidator.test_http_proxy(ProxyProfile.parse('http://proxy.example:8080'))
        self.assertIn('NTLM',error);self.assertIn('другую схему',error);self.assertIn('пароль не задан',error)

    def test_407_stops_before_repeating_identical_auth_error_for_each_provider(self):
        with patch.object(ProxyValidator,'test_tcp_connect',return_value=(True,1,None)),patch('devproxy_pkg.core.validator.socket.create_connection',return_value=Socket()) as connect:
            result=ProxyValidator.validate(ProxyProfile.parse('http://proxy.example:8080'))
        self.assertFalse(result.overall_success);self.assertTrue(result.auth_required);self.assertEqual(1,connect.call_count)

    def test_successful_keychain_write_clears_stale_failed_write_cache(self):
        with patch.dict(EphemeralStore._cache,{'fixture':'old-failed-password'},clear=True),patch.object(MacOSKeychainStore,'set_password',return_value=True),patch.object(MacOSKeychainStore,'get_password',return_value='new-password'):
            self.assertEqual('os_keychain',SecretStore.store_password('fixture','user','new-password'))
            self.assertIsNone(EphemeralStore.get('fixture'));self.assertEqual('new-password',SecretStore.get_password('fixture'))

    def test_failed_profile_save_restores_original_secret_and_profile(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            profile=ProxyProfile.parse('http://old-user@proxy.example:8080',name='fixture').to_dict();profile['requires_password']=True
            StateManager.save_profile(profile)
            with patch.object(SecretStore,'get_password',return_value='original'),patch.object(SecretStore,'store_password',return_value='os_keychain') as store,patch.object(StateManager,'save_profile',side_effect=OSError('fixture disk full')):
                with self.assertRaises(OSError):update_credentials('fixture','new-user','new-password')
            self.assertEqual(('fixture','old-user','original'),store.call_args.args)
            self.assertEqual(profile,StateManager.get_profile('fixture'))

    def test_separate_credentials_are_stored_without_plaintext_in_profile(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            StateManager.save_profile(ProxyProfile.parse('http://proxy.example:8080',name='fixture').to_dict())
            with patch.object(SecretStore,'get_password',return_value=None),patch.object(SecretStore,'store_password',return_value='os_keychain') as store:
                update_credentials('fixture','new-user','p#@:%')
            self.assertEqual(('fixture','new-user','p#@:%'),store.call_args.args)
            state=StateManager.get_profile('fixture');self.assertTrue(state['requires_password']);self.assertNotIn('password',state)
            self.assertNotIn('p#@:%',(Path(temp)/'state.json').read_text())

if __name__=='__main__':unittest.main()
