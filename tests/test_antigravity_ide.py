import hashlib,json,os,plistlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg.adapters import get_adapter
from devproxy_pkg.adapters.antigravity_ide import AntigravityIDEAdapter
from devproxy_pkg.adapters.custom import add,CustomAdapter
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.core.recovery import StateManager
from devproxy_pkg.core.smart_dns import scoped,SETUP_HOSTS
from devproxy_pkg import ide_preparation as preparation


class IDETests(unittest.TestCase):
    def bundle(self,root,identifier='com.google.antigravity-ide'):
        bundle=Path(root)/'Renamed Editor.app';contents=bundle/'Contents';exe=contents/'MacOS/Electron';exe.parent.mkdir(parents=True);exe.write_bytes(b'fixture');exe.chmod(0o700)
        (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':identifier,'CFBundleExecutable':'Electron'}))
        (contents/'Resources/app').mkdir(parents=True);(contents/'Resources/app/product.json').write_text('{}')
        return bundle,exe

    def test_metadata_detects_renamed_bundle_and_add_uses_builtin_adapter(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
            bundle,exe=self.bundle(temp)
            self.assertEqual(str(exe),AntigravityIDEAdapter.identify(bundle))
            self.assertEqual('antigravity-ide',add(bundle))
            self.assertEqual(exe.resolve(),Path(StateManager.load_state()['executables']['antigravity-ide']).resolve())
            self.assertIsInstance(get_adapter('antigravity-ide'),AntigravityIDEAdapter)

    def test_existing_custom_record_exposes_builtin_ide_without_deleting_data(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
            _,exe=self.bundle(temp);record={'name':'IDE','path':str(exe),'cli':False}
            StateManager.save_state({'custom_apps':{'custom_fixture':record}})
            identify=AntigravityIDEAdapter.identify
            with patch.object(AntigravityIDEAdapter,'identify',side_effect=lambda path:identify(path) if Path(path)==exe else None):
                self.assertEqual(str(exe),AntigravityIDEAdapter().detect_executable())
            self.assertEqual(record,StateManager.load_state()['custom_apps']['custom_fixture'])
            self.assertIn('--proxy-server={PROXY_URL}',CustomAdapter('custom_fixture',record).get_cli_launch_flags(ProxyProfile.parse('direct://')))

    def test_other_electron_bundle_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle,_=self.bundle(temp,'other.editor');self.assertIsNone(AntigravityIDEAdapter.identify(bundle))

    def test_unknown_bootstrap_is_not_modified(self):
        content=b'unknown upstream extension';before=content
        with self.assertRaisesRegex(ValueError,'Неизвестная версия'):preparation.patch_bootstrap(content)
        self.assertEqual(before,content)

    def test_known_structure_only_routes_bootstrap_fetch_and_auth(self):
        content=preparation.FETCH_NEEDLE+b';}'+preparation.TIMEOUT_NEEDLE+b';'+preparation.OPEN_NEEDLE*3
        with patch.object(preparation,'SUPPORTED_SHA256',hashlib.sha256(content).hexdigest()):
            changed=preparation.patch_bootstrap(content)
        self.assertIn(b'.fetch(a,b)',changed);self.assertIn(b'30E3',changed);self.assertEqual(3,changed.count(b'.openExternal(n.env.openExternal.bind(n.env),'))
        with self.assertRaises(ValueError):preparation.patch_bootstrap(changed)

    def test_dns_only_covers_exact_setup_hosts(self):
        for host in SETUP_HOSTS:self.assertTrue(scoped(host,dns_only=True))
        self.assertFalse(scoped('unrelated.us-central1.run.app',dns_only=True))

    def test_ide_oauth_callback_is_strictly_validated(self):
        from devproxy_pkg.auth_manager import validate_clipboard_url
        prefix='https://accounts.google.com/o/oauth2/auth?client_id=fixture&state=fixture-state&redirect_uri='
        self.assertEqual(prefix+'https%3A%2F%2Fantigravity.google%2Foauth-callback',validate_clipboard_url(prefix+'https%3A%2F%2Fantigravity.google%2Foauth-callback','antigravity-ide'))
        with self.assertRaises(ValueError):validate_clipboard_url(prefix+'https%3A%2F%2Fevil.example%2Fcallback','antigravity-ide')
