import os,unittest
from unittest.mock import patch,Mock
from devproxy_pkg import desktop_processes as processes

class DesktopProcessTests(unittest.TestCase):
    def test_cli_is_not_inspected_or_closed(self):
        with patch('devproxy_pkg.portable_runtime.app_adapter',return_value=Mock(is_cli=True)),patch.object(processes,'inventory') as scan:
            self.assertEqual({'cli':True,'processes':[]},processes.inspect('agy'));scan.assert_not_called()
    def test_exact_app_paths_and_descendants_are_selected_not_same_named_apps(self):
        uid=os.getuid();data={91001:{'pid':91001,'parent':1,'uid':uid,'path':'/Applications/AI.app/Contents/MacOS/AI','name':'AI'},91002:{'pid':91002,'parent':91001,'uid':uid,'path':'/usr/bin/helper','name':'helper'},91003:{'pid':91003,'parent':1,'uid':uid,'path':'/other/AI.app/Contents/MacOS/AI','name':'AI'}}
        with patch('devproxy_pkg.portable_runtime.app_adapter',return_value=Mock(is_cli=False)),patch('devproxy_pkg.portable_runtime.executable',return_value='/Applications/AI.app/Contents/MacOS/AI'),patch('devproxy_pkg.portable_runtime.request',return_value=None),patch('devproxy_pkg.macos_backend.record',return_value=None),patch.object(processes,'inventory',return_value=data):
            self.assertEqual([91001,91002],[item['pid'] for item in processes.inspect('fixture')['processes']])
    def test_failure_to_exit_blocks_operation_without_force_killing(self):
        item={'pid':91001,'parent':1,'uid':os.getuid(),'path':'/fixture/AI','name':'AI'}
        with patch.object(processes,'inspect',return_value={'cli':False,'processes':[item]}),patch.object(processes,'inventory',return_value={91001:item}),patch('devproxy_pkg.portable_runtime.request',return_value=None),patch.object(processes.os,'kill') as kill:
            with self.assertRaisesRegex(RuntimeError,'не подтвердило выход'):processes.close('fixture',timeout=0)
            kill.assert_called_once_with(91001,processes.signal.SIGTERM)

@unittest.skipUnless(__import__('sys').platform=='darwin' and __import__('shutil').which('clang'),'Native process fixture')
class DesktopCloseIntegrationTests(unittest.TestCase):
    def test_close_only_selected_app_and_its_child(self):
        import subprocess,tempfile,time,signal
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'main.c';source.write_text('#include <unistd.h>\nint main(){if(fork()==0){execl("/bin/sleep","sleep","60",(char*)0);return 2;}for(;;)pause();}')
            executable=root/'Selected AI.app/Contents/MacOS/AI';other=root/'Other AI.app/Contents/MacOS/AI';executable.parent.mkdir(parents=True);other.parent.mkdir(parents=True)
            subprocess.run(['clang',str(source),'-o',str(executable)],check=True,capture_output=True);__import__('shutil').copy2(executable,other)
            selected=subprocess.Popen([str(executable)],start_new_session=True);unrelated=subprocess.Popen([str(other)],start_new_session=True)
            try:
                with patch('devproxy_pkg.portable_runtime.app_adapter',return_value=Mock(is_cli=False)),patch('devproxy_pkg.portable_runtime.executable',return_value=str(executable)),patch('devproxy_pkg.portable_runtime.request',return_value=None),patch('devproxy_pkg.macos_backend.record',return_value=None):
                    deadline=time.monotonic()+3
                    while len(processes.inspect('fixture')['processes'])<2 and time.monotonic()<deadline:time.sleep(.05)
                    self.assertGreaterEqual(len(processes.inspect('fixture')['processes']),2)
                    processes.close('fixture',timeout=3);self.assertEqual([],processes.inspect('fixture')['processes']);self.assertIsNone(unrelated.poll())
            finally:
                for proc in (selected,unrelated):
                    from devproxy_pkg.portable_runtime import signal_group
                    signal_group(proc.pid,signal.SIGTERM)
                    proc.wait(timeout=5)
