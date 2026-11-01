
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from devproxy_pkg.proxy_editor import parse_connection,save_connection,ProfileEditor
from devproxy_pkg.core.recovery import StateManager

URL='https://agw_fixture:fixture_password@test-proxy.example:50128'


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'DEVPROXY_HOME':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
        self.vault={}
        def store(name,user,pw):self.vault[name]=pw;return 'os_keychain'
        for name,action in [('get_password',lambda name:self.vault.get(name)),('store_password',store),('delete_password',lambda name:self.vault.pop(name,None) is not None)]:
            item=patch('devproxy_pkg.proxy_editor.SecretStore.'+name,side_effect=action);item.start();self.addCleanup(item.stop)

    def test_full_https_url_extracts_all_fields(self):
        p=parse_connection(URL,'fixture')
        self.assertEqual(('https','test-proxy.example',50128,'agw_fixture','fixture_password'),(p.protocol,p.host,p.port,p.username,p.password))

    def test_new_profile_round_trip_uses_vault_without_plaintext(self):
        save_connection('fixture',URL)
        data=StateManager.get_profile('fixture')
        self.assertEqual('agw_fixture',data['username']);self.assertTrue(data['requires_password'])
        self.assertEqual('fixture_password',self.vault['fixture']);self.assertNotIn('password',data)
        self.assertNotIn('fixture_password',(Path(self.temp.name)/'state.json').read_text())

    def test_existing_profile_replaces_all_connection_fields_and_preserves_routes(self):
        save_connection('fixture','http://old:oldpass@old.example:8080')
        old=StateManager.get_profile('fixture');old.update(smart_dns=True,dns_padding=True,dns_endpoints=['udp://8.8.8.8'],proxy_enabled=False)
        StateManager.save_profile(old);save_connection('fixture',URL,replace=True)
        current=StateManager.get_profile('fixture')
        self.assertEqual(('https','test-proxy.example',50128,'agw_fixture'),tuple(current[k] for k in ('protocol','host','port','username')))
        self.assertEqual('fixture_password',self.vault['fixture']);self.assertTrue(current['smart_dns']);self.assertTrue(current['dns_padding']);self.assertFalse(current['proxy_enabled'])

    def test_plain_proxy_removes_old_auth_and_password(self):
        save_connection('fixture',URL);save_connection('fixture','http://plain.example:3128',replace=True)
        data=StateManager.get_profile('fixture');self.assertIsNone(data['username']);self.assertFalse(data['requires_password']);self.assertNotIn('fixture',self.vault)

    def test_keychain_readback_mismatch_restores_old_connection(self):
        save_connection('fixture','http://old:oldpass@old.example:8080');old=StateManager.get_profile('fixture')
        with patch('devproxy_pkg.proxy_editor.SecretStore.get_password',side_effect=['oldpass','wrong']):
            with self.assertRaisesRegex(RuntimeError,'не подтвердил'):save_connection('fixture',URL,replace=True)
        self.assertEqual(old,StateManager.get_profile('fixture'));self.assertEqual('oldpass',self.vault['fixture'])

    def test_disk_failure_restores_previous_keychain_password(self):
        save_connection('fixture','http://old:oldpass@old.example:8080');old=StateManager.get_profile('fixture')
        with patch.object(StateManager,'save_profile',side_effect=OSError('fixture disk full')):
            with self.assertRaises(OSError):save_connection('fixture',URL,replace=True)
        self.assertEqual(old,StateManager.get_profile('fixture'));self.assertEqual('oldpass',self.vault['fixture'])

    def test_duplicate_requires_explicit_replacement(self):
        save_connection('fixture',URL)
        with self.assertRaisesRegex(ValueError,'существует'):save_connection('fixture','http://other.example:8080')
        self.assertEqual('fixture_password',self.vault['fixture'])

    def test_percent_decoding_once(self):
        p=parse_connection('https://user%40example:p%2540%3A%23@proxy.example:443','fixture')
        self.assertEqual('user@example',p.username);self.assertEqual('p%40:#',p.password)

    def test_invalid_input_does_not_expose_pasted_secrets(self):
        with self.assertRaises(ValueError) as error:parse_connection('https://user:private-secret@host:invalid','fixture')
        self.assertNotIn('private-secret',str(error.exception))


class EditorGuiTests(unittest.TestCase):
    def test_new_and_existing_dialogs_fill_all_fields_on_paste(self):
        import tkinter as tk
        try:root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        root.withdraw();root.busy=False
        try:
            for existing in (None,'fixture'):
                editor=ProfileEditor(root,existing);editor.raw.set(URL);root.update()
                self.assertEqual('https',editor.fields['protocol'].get());self.assertEqual('test-proxy.example',editor.fields['host'].get());self.assertEqual('50128',editor.fields['port'].get())
                self.assertEqual('agw_fixture',editor.fields['username'].get());self.assertEqual('fixture_password',editor.fields['password'].get())
                self.assertEqual('•',editor.url_entry.cget('show'));editor.window.destroy()
        finally:root.destroy()


if __name__=='__main__':unittest.main()
