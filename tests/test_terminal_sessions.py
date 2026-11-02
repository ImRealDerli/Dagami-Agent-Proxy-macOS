import http.client,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg import terminal_sessions as terminal

class TerminalSessionsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=patch.dict(os.environ,DEVPROXY_HOME=temp.name);p.start();self.addCleanup(p.stop)
    def process(self,new_session=True):
        process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=new_session)
        def cleanup():
            if process.poll() is None:process.kill()
            process.wait(timeout=5)
        self.addCleanup(cleanup);return process
    def test_multiple_terminals_have_independent_ids_and_cleanup(self):
        process=self.process();one=terminal.TerminalSession('codex','DNS',process,'http://127.0.0.1:1234').start();two=terminal.TerminalSession('codex','DNS',process,'http://127.0.0.1:1234').start()
        try:
            rows=terminal.list_sessions();self.assertEqual(2,len(rows));self.assertNotEqual(one.id,two.id)
            self.assertTrue(rows[0]['terminal']);self.assertNotIn(one.token,json.dumps(rows))
            self.assertEqual(0o600,one.path.stat().st_mode&0o777)
        finally:one.close();two.close()
        self.assertEqual([],terminal.list_sessions())
    def test_unauthenticated_stop_is_rejected(self):
        process=self.process();session=terminal.TerminalSession('codex','DNS',process,'').start()
        try:
            client=http.client.HTTPConnection('127.0.0.1',session.server.server_port)
            client.request('POST','/',json.dumps({'command':'stop'}),{'Content-Type':'application/json'});reply=client.getresponse();reply.read();client.close()
            self.assertEqual(403,reply.status);self.assertIsNone(process.poll())
        finally:session.close()
    def test_stop_affects_only_selected_terminal(self):
        chosen=self.process();other=self.process();session=terminal.TerminalSession('codex','DNS',chosen,'').start()
        try:
            terminal.request(session.id,'stop');chosen.wait(timeout=6);self.assertIsNone(other.poll())
        finally:session.close()
    def test_cli_sharing_terminal_group_does_not_signal_our_group(self):
        process=self.process(new_session=False);terminal.stop_owned_process(process)
        self.assertIsNotNone(process.poll())
    def test_real_cli_launcher_registers_session_until_process_exits(self):
        from devproxy_pkg.core.launcher import Launcher
        from devproxy_pkg.core.profile import ProxyProfile
        def register(process,bridge):
            monitor=terminal.TerminalSession('codex','DNS',process,bridge).start()
            try:
                status=terminal.request(monitor.id)
                self.assertEqual([process.pid],status['application_pids'])
                self.assertEqual(bridge,status['bridge'])
            except BaseException:monitor.close();raise
            return monitor
        process,tunnel=Launcher.launch_with_tunnel(sys.executable,ProxyProfile.parse('direct://'),extra_args=['-c','import time;time.sleep(.3)'],enable_ipc=False,session_factory=register)
        self.assertEqual(0,process.returncode);self.assertEqual([],terminal.list_sessions())
    @unittest.skipUnless(sys.platform=='darwin','Native macOS argv fixture')
    def test_preupdate_cli_is_found_from_real_process_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/'devproxy_gui.py';script.write_text('import time;time.sleep(20)')
            process=subprocess.Popen([sys.executable,'-B',str(script),'run','codex','--profile','fixture spaced'])
            try:
                with patch.object(terminal.StateManager,'list_profiles',return_value={'fixture spaced':{}}):
                    rows=terminal.legacy_sessions()
                matches=[row for row in rows if row['pid']==process.pid]
                self.assertEqual(1,len(matches));self.assertEqual('fixture spaced',matches[0]['profile']);self.assertFalse(matches[0]['canStop'])
            finally:
                process.terminate();process.wait(timeout=5)
    def test_identifier_rejects_traversal(self):
        with self.assertRaises(ValueError):terminal.request('../fixture')
    def test_legacy_detection_uses_exact_arguments_and_is_read_only(self):
        listing=str(os.getpid())+' '+str(os.getuid())+' python /fixture/devproxy_gui.py run codex --profile named profile\n'
        with patch.object(terminal.sys,'platform','darwin'),patch.object(terminal.StateManager,'list_profiles',return_value={'named profile':{}}),patch.object(terminal.subprocess,'run',return_value=type('Result',(),{'stdout':listing})()),patch.object(terminal,'process_arguments',return_value=['python','/fixture/devproxy_gui.py','run','codex','--profile','named profile']):
            rows=terminal.legacy_sessions();self.assertEqual('named profile',rows[0]['profile']);self.assertFalse(rows[0]['canStop'])
            self.assertEqual([],terminal.legacy_sessions({os.getpid()}))
