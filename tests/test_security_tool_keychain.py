import ctypes as c
import os
from pathlib import Path
import subprocess,sys,tempfile,unittest
from unittest.mock import patch
from devproxy_pkg.core.macos_security_tool import SecurityToolKeychain
from devproxy_pkg.core.macos_keychain import Keychain
from devproxy_pkg.core.secrets import MacOSKeychainStore


class SecurityToolParsingTests(unittest.TestCase):
    def test_missing_is_distinct_from_access_denial(self):
        store=SecurityToolKeychain(account='fixture')
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],44,b'',b'not found')):
            self.assertIsNone(store.get('fixture'))
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],51,b'',b'authentication failed')):
            with self.assertRaisesRegex(RuntimeError,'Код security: 51'):store.get('fixture')

    def test_ascii_hex_is_not_decoded_as_hex(self):
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,b'',b'password: "abcdef1234"\n')):
            self.assertEqual('abcdef1234',SecurityToolKeychain().get('fixture'))

    def test_terminal_without_gui_environment_uses_system_tool(self):
        with patch.dict(os.environ,{},clear=True),patch('sys.platform','darwin'):
            self.assertIsInstance(MacOSKeychainStore.keychain(),SecurityToolKeychain)

    def test_bundled_engine_uses_system_tool(self):
        with patch.dict(os.environ,{'DAGAMI_BUNDLED_ENGINE':'1'}):
            self.assertIsInstance(MacOSKeychainStore.keychain(),SecurityToolKeychain)


@unittest.skipUnless(sys.platform=='darwin','macOS Security.framework required')
class SecurityToolVaultTests(unittest.TestCase):
    def test_roundtrip_in_private_vault_without_secret_arguments(self):
        api=Keychain().api;cf=Keychain().cf;ptr=c.c_void_p()
        api.SecKeychainCreate.argtypes=[c.c_char_p,c.c_uint32,c.c_void_p,c.c_bool,c.c_void_p,c.POINTER(c.c_void_p)]
        api.SecKeychainDelete.argtypes=[c.c_void_p]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.keychain-db';password=b'fixture-vault-password'
            self.assertEqual(0,api.SecKeychainCreate(str(path).encode(),len(password),password,False,None,c.byref(ptr)))
            try:
                store=SecurityToolKeychain(account='fixture',path=path)
                with patch('subprocess.run',wraps=subprocess.run) as run:
                    self.assertIsNone(store.get('fixture-service'))
                    for secret in ('fixture-secret','abcdef1234','p#@:%/пароль \'" $()\\abc','line1\nline2',''):
                        store.set('fixture-service','fixture',secret)
                        self.assertEqual(secret,store.get('fixture-service'))
                    for call in run.call_args_list:
                        self.assertEqual('/usr/bin/security',call.args[0][0])
                        self.assertNotIn('-X',call.args[0])
                        self.assertNotIn('-w',call.args[0])
                        self.assertFalse(call.kwargs.get('shell',False))
                    self.assertTrue(store.delete('fixture-service'))
                    self.assertIsNone(store.get('fixture-service'))
            finally:api.SecKeychainDelete(ptr);cf.CFRelease(ptr)
