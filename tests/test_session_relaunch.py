import os,signal,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from devproxy_pkg import portable_runtime as runtime
from devproxy_pkg.core.profile import ProxyProfile
from devproxy_pkg.core.recovery import StateManager

class SessionRelaunchTests(unittest.TestCase):
    def test_zombie_group_does_not_keep_application_alive(self):
        proc=Mock(pid=87654);proc.poll.return_value=0;retired=set()
        with patch.object(runtime.subprocess,'run',return_value=Mock(stdout='87654 Z\n87654 Z+\n')):
            self.assertFalse(runtime.process_alive(proc,retired))
        self.assertIn(proc.pid,retired)

    def test_live_child_keeps_application_group_alive(self):
        proc=Mock(pid=87654);proc.poll.return_value=0
        with patch.object(runtime.subprocess,'run',return_value=Mock(stdout='87654 S\n')):
            self.assertTrue(runtime.process_alive(proc,set()))

    def test_existing_macos_window_is_activated_without_new_environment(self):
        with patch.object(runtime.sys,'platform','darwin'),patch.object(runtime.subprocess,'run') as run:
            runtime.activate_macos_app('/Applications/Fixture.app/Contents/MacOS/Electron')
            self.assertEqual(['/usr/bin/open','-a','/Applications/Fixture.app'],run.call_args.args[0])

    def test_empty_group_permission_error_does_not_block_cleanup(self):
        with patch.object(runtime.os,'killpg',side_effect=PermissionError()),patch.object(runtime.subprocess,'run',return_value=Mock(stdout='87654 Z\n')):
            runtime.signal_group(87654,signal.SIGTERM)

    def test_live_group_permission_error_remains_failure(self):
        with patch.object(runtime.os,'killpg',side_effect=PermissionError()),patch.object(runtime.subprocess,'run',return_value=Mock(stdout='87654 S\n')):
            with self.assertRaises(PermissionError):runtime.signal_group(87654,signal.SIGTERM)

    @unittest.skipIf(os.name=='nt','POSIX fixture')
    def test_browser_only_session_relaunches_application_and_reports_early_exit(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}):
            root=Path(temp);app=root/'fixture-app';browser=root/'fixture-browser';output=root/'pids'
            app.write_text('#!'+sys.executable+'\nimport os,time\nfrom pathlib import Path\np=Path('+repr(str(output))+')\nwith p.open("a") as f:f.write(str(os.getpid())+"\\n")\ntime.sleep(60)\n');app.chmod(0o700)
            browser.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(60)\n');browser.chmod(0o700)
            StateManager.save_profile(ProxyProfile.parse('http://127.0.0.1:9',name='fixture').to_dict())
            runtime.register_executable('vscode',app)
            errors=[]
            def worker():
                try:runtime.serve_session('vscode','fixture')
                except Exception as exc:errors.append(exc)
            with patch.object(runtime,'_browser',return_value=str(browser)),patch('devproxy_pkg.auth_route.verify_route'):
                thread=threading.Thread(target=worker,daemon=True);thread.start()
                try:
                    for _ in range(100):
                        if runtime.descriptor('vscode').exists():break
                        time.sleep(.05)
                    self.assertTrue(runtime.start_session('vscode','fixture')['running'])
                    runtime.request('vscode','login',url='https://accounts.google.com/login')
                    os.kill(int(output.read_text().splitlines()[-1]),signal.SIGTERM)
                    for _ in range(100):
                        status=runtime.request('vscode')
                        if not status['running']:break
                        time.sleep(.05)
                    self.assertFalse(status['running']);self.assertTrue(status['browser_running'])
                    self.assertTrue(runtime.start_session('vscode','fixture')['running'])
                    self.assertEqual(2,len(output.read_text().splitlines()))
                    os.kill(int(output.read_text().splitlines()[-1]),signal.SIGTERM)
                    for _ in range(100):
                        if not runtime.request('vscode')['running']:break
                        time.sleep(.05)
                    app.write_text('#!'+sys.executable+'\nraise SystemExit(7)\n');app.chmod(0o700)
                    with self.assertRaisesRegex(RuntimeError,'код 7'):runtime.start_session('vscode','fixture')
                finally:
                    runtime.request('vscode','stop');thread.join(timeout=15)
                self.assertFalse(thread.is_alive());self.assertFalse(errors,errors)
