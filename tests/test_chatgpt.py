import os,plistlib,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg.adapters import get_adapter
from devproxy_pkg.adapters.chatgpt import ChatGPTAdapter
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.portable_shortcuts import PortableShortcuts
from devproxy_pkg import chatgpt_preparation as preparation


class ChatGPTTests(unittest.TestCase):
    def bundle(self,root,identifier='com.openai.codex',executable='ChatGPT',electron=True):
        bundle=Path(root)/'ChatGPT.app';contents=bundle/'Contents';binary=contents/'MacOS'/executable
        binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture executable');binary.chmod(0o700)
        (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':identifier,'CFBundleExecutable':executable}))
        if electron:
            (contents/'Resources').mkdir();(contents/'Resources/app.asar').write_bytes(b'fixture archive')
            (contents/'Frameworks/Codex Framework.framework').mkdir(parents=True)
        return bundle,binary

    def test_registry_and_renamed_codex_based_chatgpt_are_detected(self):
        self.assertIsInstance(get_adapter('chatgpt'),ChatGPTAdapter)
        with tempfile.TemporaryDirectory() as temp:
            bundle,binary=self.bundle(temp)
            self.assertEqual(str(binary),ChatGPTAdapter.bundle_executable(bundle))

    def test_codex_and_unrelated_bundles_are_not_reported_as_chatgpt(self):
        for identifier,name in (('com.openai.codex','Codex'),('other.vendor.chat','ChatGPT')):
            with tempfile.TemporaryDirectory() as temp:
                bundle,_=self.bundle(temp,identifier,name)
                self.assertIsNone(ChatGPTAdapter.bundle_executable(bundle))

    def test_spotlight_uses_plist_executable_and_validates_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle,binary=self.bundle(temp)
            original=ChatGPTAdapter.bundle_executable
            def candidate(path):return original(path) if str(path)==str(bundle) else None
            with patch.object(ChatGPTAdapter,'bundle_executable',side_effect=candidate),patch('devproxy_pkg.adapters.chatgpt.subprocess.run',return_value=subprocess.CompletedProcess([],0,str(bundle)+'\n','')):
                self.assertEqual(str(binary),ChatGPTAdapter().detect_executable())

    def test_electron_flags_route_browser_and_keep_callback_local(self):
        with tempfile.TemporaryDirectory() as temp:
            _,binary=self.bundle(temp)
            flags=ChatGPTAdapter().launch_flags(ProxyProfile.parse('http://127.0.0.1:8888'),str(binary))
            self.assertIn('--proxy-server={PROXY_URL}',flags)
            self.assertIn('--proxy-bypass-list=localhost;127.0.0.1;[::1]',flags)
            self.assertIn('--disable-quic',flags)

    def test_native_proxy_is_rejected_but_dns_only_can_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            _,binary=self.bundle(temp,identifier='com.openai.chat',electron=False)
            with self.assertRaisesRegex(RuntimeError,'нативную сеть'):
                ChatGPTAdapter().launch_flags(ProxyProfile.parse('http://127.0.0.1:8888'),str(binary))
            self.assertEqual([],ChatGPTAdapter().launch_flags(ProxyProfile.parse('direct://'),str(binary)))

    def test_patch_and_rollback_change_only_managed_launcher(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
            root=Path(temp);bundle,binary=self.bundle(root/'installed');original=binary.read_bytes()
            links=PortableShortcuts(root=root/'shortcuts',home=root/'home',platform='darwin');profile=ProxyProfile.parse('http://127.0.0.1:8888')
            with patch.object(preparation,'PortableShortcuts',return_value=links),patch.object(preparation,'executable',return_value=str(binary)),patch.object(preparation,'load_profile',return_value=profile),patch.object(preparation,'require_stopped'),patch.object(preparation,'request',return_value=None),patch('devproxy_pkg.portable_shortcuts.executable',return_value=str(binary)),patch('devproxy_pkg.portable_shortcuts.load_profile',return_value=profile):
                preparation.prepare('fixture');self.assertTrue(preparation.status())
                self.assertEqual('fixture',links.status('chatgpt')['profile'])
                preparation.restore();self.assertFalse(preparation.status())
            self.assertEqual(original,binary.read_bytes());self.assertTrue(bundle.is_dir())
