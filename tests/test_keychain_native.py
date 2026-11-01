
import ctypes as c
from pathlib import Path
import sys
import tempfile
import unittest
from devproxy_pkg.core.macos_keychain import Keychain

@unittest.skipUnless(sys.platform=='darwin','macOS Security.framework required')
class NativeKeychainTests(unittest.TestCase):
    def test_duplicate_legacy_accounts_cannot_shadow_canonical_password(self):
        with tempfile.TemporaryDirectory() as temp:
            k=Keychain();api=k.api;ptr=c.c_void_p();password=b'isolated-fixture-vault'
            api.SecKeychainCreate.argtypes=[c.c_char_p,c.c_uint32,c.c_void_p,c.c_bool,c.c_void_p,c.POINTER(c.c_void_p)]
            status=api.SecKeychainCreate(str(Path(temp)/'fixture.keychain-db').encode(),len(password),password,False,None,c.byref(ptr))
            self.assertEqual(0,status)
            try:
                service=b'devproxy-auth:fixture'
                for account in (b'old-account-one',b'old-account-two'):
                    self.assertEqual(0,api.SecKeychainAddGenericPassword(ptr,len(service),service,len(account),account,3,b'old',None))
                canonical=Keychain(ptr,account='dagami-profile-v2')
                for value in ('first-password','second-password','p#@:%/пароль'):
                    canonical.set(service.decode(),'ignored-user',value)
                    self.assertEqual(value,canonical.get(service.decode()))
                self.assertTrue(canonical.delete(service.decode()))
                self.assertIsNone(canonical.get(service.decode()))
                self.assertEqual('old',Keychain(ptr).get(service.decode()))
            finally:
                api.SecKeychainDelete.argtypes=[c.c_void_p]
                api.SecKeychainDelete(ptr);k.cf.CFRelease(ptr)
