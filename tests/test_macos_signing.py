import os,plistlib,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg import macos_backend as backend

class SigningTests(unittest.TestCase):
    def test_nested_backends_signed_before_container_and_all_verified(self):
        with patch.object(backend,'codesign') as sign:
            backend.sign_bundle(Path('/fixture/Editor.app'),[Path('/fixture/Editor.app/Contents/Resources/bin/language_server')])
        calls=sign.call_args_list
        self.assertEqual('language_server',calls[0].args[0].name)
        self.assertIn('--verify',calls[1].args)
        self.assertEqual('Editor.app',calls[2].args[0].name)
        self.assertEqual(('--verify','--deep','--strict'),calls[3].args[1:])
        self.assertNotIn('requirements',str(calls))

    def test_failure_reports_codesign_reason_and_stops_container_signing(self):
        error=subprocess.CalledProcessError(1,['codesign'],stderr=b'nested code is modified or invalid')
        with patch.object(backend.subprocess,'run',side_effect=error):
            with self.assertRaisesRegex(RuntimeError,'nested code is modified or invalid'):backend.codesign('/fixture/Editor.app','--verify')
        with patch.object(backend,'codesign',side_effect=RuntimeError('denied')) as sign:
            with self.assertRaises(RuntimeError):backend.sign_bundle(Path('/fixture/Editor.app'),[Path('/fixture/backend')])
            self.assertEqual(1,sign.call_count)

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('clang'),'macOS signing fixture')
    def test_real_macho_backend_in_resources_passes_strict_bundle_verification(self):
        from devproxy_pkg.core.recovery import StateManager
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
            root=Path(temp);bundle=root/'Fixture.app';main=bundle/'Contents/MacOS/Fixture';helper=bundle/'Contents/Resources/bin/language_server'
            main.parent.mkdir(parents=True);helper.parent.mkdir(parents=True)
            (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'Fixture','CFBundleIdentifier':'local.dagami.signingfixture','CFBundlePackageType':'APPL','CFBundleVersion':'1'}))
            source=root/'fixture.c';payload=b'https_proxy|'+b'|'.join(backend.PATTERNS)
            source.write_text('__attribute__((used)) static const unsigned char payload[]={'+','.join(str(n) for n in payload)+'};int main(void){return 0;}')
            subprocess.run(['clang',str(source),'-o',str(helper)],check=True,capture_output=True)
            shutil.copy2(helper,main)
            backend.sign_bundle(bundle,[helper]);original=backend.digest(helper)
            with patch('devproxy_pkg.portable_runtime.executable',return_value=str(main)),patch('devproxy_pkg.portable_runtime.require_stopped'),patch('devproxy_pkg.portable_runtime.request',return_value=None):
                backend.prepare('antigravity')
            record=backend.record('antigravity');prepared=Path(record['bundle'])
            subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(prepared)],check=True,capture_output=True)
            self.assertEqual(original,backend.digest(helper))
            self.assertNotEqual(original,backend.digest(prepared/helper.relative_to(bundle)))
            self.assertTrue(Path(backend.checked_executable('antigravity')).is_file())
            self.assertTrue(StateManager.load_state()['prepared_macos']['antigravity'])
            with patch('devproxy_pkg.portable_runtime.require_stopped'),patch('devproxy_pkg.portable_runtime.request',return_value=None):
                backend.restore('antigravity')
                with patch('devproxy_pkg.portable_runtime.executable',return_value=str(main)),patch.object(backend,'sign_bundle',side_effect=RuntimeError('fixture signing failure')):
                    with self.assertRaisesRegex(RuntimeError,'fixture signing failure'):backend.prepare('antigravity')
            self.assertIsNone(backend.record('antigravity'))
            self.assertFalse(list(backend.managed_root().iterdir()))
            self.assertEqual(original,backend.digest(helper))
