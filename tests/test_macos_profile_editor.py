import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg import macos_profile_editor as editor,journal
from devproxy_pkg.core.recovery import StateManager
from devproxy_pkg.proxy_editor import save_connection

class ProfileManagementTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.env=patch.dict(os.environ,DEVPROXY_HOME=temp.name);self.env.start();self.addCleanup(self.env.stop)
        self.vault={}
        def store(name,user,password):self.vault[name]=password;return 'os_keychain'
        for name,side in [('get_password',lambda name:self.vault.get(name)),('store_password',store),('delete_password',lambda name:self.vault.pop(name,None) is not None)]:
            p=patch.object(editor.SecretStore,name,side_effect=side);p.start();self.addCleanup(p.stop)
        p=patch.object(editor,'active_sessions',return_value=[]);self.active=p.start();self.addCleanup(p.stop)
    def fixture(self):
        save_connection('fixture','https://user%40name:pass%2540%3Aword@proxy.example:8443')
        value=StateManager.get_profile('fixture');value.update(smart_dns=True,dns_endpoints=['https://dns.example/query'],dns_scope='google',dns_domains=['*.example.ai'],dns_padding=True,block_updates=True,notes='preserve')
        StateManager.save_profile(value)
    def test_editor_round_trip_preserves_credentials_and_hidden_options(self):
        self.fixture();before=StateManager.get_profile('fixture');data=editor.details('fixture')
        editor.save('fixture',data,replace=True)
        self.assertEqual(before,StateManager.get_profile('fixture'));self.assertEqual('pass%40:word',self.vault['fixture'])
    def test_disabled_proxy_keeps_saved_link_and_password(self):
        self.fixture();value=StateManager.get_profile('fixture');value['proxy_enabled']=False;StateManager.save_profile(value)
        data=editor.details('fixture');self.assertFalse(data['proxy']);self.assertIn('proxy.example',data['url'])
        editor.save('fixture',data,replace=True)
        self.assertEqual(value,StateManager.get_profile('fixture'));self.assertEqual('pass%40:word',self.vault['fixture'])
    def test_refused_keychain_deletion_keeps_profile(self):
        self.fixture();before=StateManager.get_profile('fixture')
        with patch.object(editor.SecretStore,'delete_password',return_value=False):
            with self.assertRaises(RuntimeError):editor.delete('fixture')
        self.assertEqual(before,StateManager.get_profile('fixture'));self.assertEqual('pass%40:word',self.vault['fixture'])
    def test_dns_only_save_never_accesses_keychain(self):
        with patch.object(editor.SecretStore,'get_password',side_effect=AssertionError('real vault access')):
            editor.save('dns',{'proxy':False,'dns':True,'url':'','endpoints':['udp://1.1.1.1'],'scope':'ai','domains':[]})
        self.assertTrue(StateManager.get_profile('dns')['smart_dns'])
    def test_validation_failure_keeps_state_and_secret(self):
        self.fixture();before=StateManager.get_profile('fixture');data=editor.details('fixture');data['endpoints']=['broken://endpoint']
        with self.assertRaises(ValueError):editor.save('fixture',data,replace=True)
        self.assertEqual(before,StateManager.get_profile('fixture'));self.assertEqual('pass%40:word',self.vault['fixture'])
    def test_active_profile_cannot_be_changed_or_deleted(self):
        self.fixture();self.active.return_value=[('cli_fixture','CLI')]
        with self.assertRaisesRegex(ValueError,'сессией'):editor.delete('fixture')
        with self.assertRaises(ValueError):editor.save('fixture',editor.details('fixture'),replace=True)
        self.assertIsNotNone(StateManager.get_profile('fixture'))
    def test_delete_removes_only_requested_profile_and_password(self):
        self.fixture();save_connection('other','direct://');editor.delete('fixture')
        self.assertIsNone(StateManager.get_profile('fixture'));self.assertNotIn('fixture',self.vault);self.assertIsNotNone(StateManager.get_profile('other'))
    def test_delete_disk_failure_restores_password(self):
        self.fixture();before=StateManager.get_profile('fixture')
        with patch.object(StateManager,'delete_profile',side_effect=OSError('fixture disk error')):
            with self.assertRaises(OSError):editor.delete('fixture')
        self.assertEqual(before,StateManager.get_profile('fixture'));self.assertEqual('pass%40:word',self.vault['fixture'])
    def test_details_are_never_written_to_journal(self):
        self.fixture();details=editor.details('fixture');journal.append('profileDetails',True,str(details));journal.append('profileSave',True,str(details))
        text=journal.read();self.assertNotIn('pass%2540',text);self.assertNotIn('proxy.example',text)
    def test_unavailable_password_blocks_edit_without_blank_overwrite(self):
        self.fixture();self.vault.clear()
        with self.assertRaisesRegex(RuntimeError,'прочитать'):editor.details('fixture')
        self.assertTrue(StateManager.get_profile('fixture')['requires_password'])
