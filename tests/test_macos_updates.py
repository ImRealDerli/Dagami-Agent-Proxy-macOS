import hashlib,json,os,plistlib,stat,subprocess,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from devproxy_pkg import macos_updates as updates


class UpdateTests(unittest.TestCase):
    def release(self,tag):return {'tag_name':tag,'draft':False,'assets':[{'name':updates.ZIP_NAME},{'name':'SHA256SUMS.txt'}]}
    def test_beta_sorting_and_downgrade_protection(self):
        releases=[self.release('v0.4.0-mac.25-beta'),self.release('v0.4.0-mac.27-beta'),self.release('v0.4.0-mac.26-beta')]
        self.assertEqual('v0.4.0-mac.27-beta',updates.select_release(releases,'0.4.0b0+mac.25')['tag_name'])
        self.assertIsNone(updates.select_release(releases,'0.4.0b0+mac.27'))
        releases[1]['draft']=True;self.assertEqual('v0.4.0-mac.26-beta',updates.select_release(releases,'0.4.0b0+mac.25')['tag_name'])
    def test_severity_is_declared_not_guessed(self):
        unknown=updates.release_details({'body':'critical words in prose'})
        self.assertEqual('unspecified',unknown['severity'])
        self.assertEqual('',updates.release_details({'body':None})['notes'])
        declared=updates.release_details({'body':'<!-- dagami-update: {"severity":"critical","recommendation":"required"} -->\nFix details'})
        self.assertEqual('critical',declared['severity']);self.assertEqual('required',declared['recommendation']);self.assertEqual('Fix details',declared['notes'])
    def test_selected_bridge_cannot_be_bypassed_by_environment(self):
        import urllib.request
        request=urllib.request.Request('https://api.github.com/repos/fixture')
        with patch('urllib.request.proxy_bypass',return_value=True):updates.BridgeProxy('127.0.0.1:12345').https_open(request)
        self.assertEqual('127.0.0.1:12345',request.host);self.assertEqual('api.github.com',request._tunnel_host)
    def test_hash_is_unique_and_scoped_to_app_zip(self):
        value='a'*64;self.assertEqual(value,updates.checksum((value+'  '+updates.ZIP_NAME+'\n').encode()))
        for text in (value+' other.zip',value+'  '+updates.ZIP_NAME+'\n'+value+'  '+updates.ZIP_NAME):
            with self.assertRaises(ValueError):updates.checksum(text.encode())
    def test_host_and_archive_traversal_are_rejected(self):
        for url in ('http://github.com/file','https://github.com.evil.test/file','https://user:pass@github.com/file'):
            with self.assertRaises(ValueError):updates.validate_url(url)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fixture.zip'
            for name in ('../outside','Dagami.app/../../outside','other.app/binary'):
                with zipfile.ZipFile(path,'w') as z:z.writestr(name,b'fixture')
                with self.assertRaises(ValueError):updates.validate_archive(path)
    def test_framework_symlink_allowed_but_parent_links_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fixture.zip'
            for target,valid in (('Versions/Current/Resources',True),('../../outside',False)):
                with zipfile.ZipFile(path,'w') as z:
                    info=zipfile.ZipInfo('Dagami.app/Contents/Resources/Framework/Resources');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,target)
                if valid:updates.validate_archive(path)
                else:
                    with self.assertRaises(ValueError):updates.validate_archive(path)
    def test_receipt_ack_is_bound_to_destination_and_running_version(self):
        from devproxy_pkg import __version__
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
            app=Path(temp)/'Dagami.app';(app/'Contents').mkdir(parents=True)
            build=400+updates.version(__version__)[3];(app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':updates.BUNDLE_ID,'CFBundleVersion':str(build)}))
            ack=updates.root()/'work/ack';ack.parent.mkdir();data={'destination':str(app),'version':build,'ack':str(ack),'backup':str(app.parent/('.Dagami-previous-'+'a'*32+'.app'))}
            (updates.root()/'pending.json').write_text(json.dumps(data))
            with patch.dict(os.environ,{'DAGAMI_NATIVE_APP':str(app/'Contents/MacOS/Dagami')}):self.assertTrue(updates.acknowledge())
            self.assertTrue(ack.exists())
    def test_real_zip_from_previous_build_is_valid(self):
        path=Path.home()/'Desktop/Dagami Universal/Dagami-macOS-Universal.zip'
        if not path.exists():self.skipTest('local release ZIP absent')
        updates.validate_archive(path)


class InstallHelperTests(unittest.TestCase):
    def test_failed_new_launch_rolls_back_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);dest=root/'Dagami.app';candidate=root/'candidate.app';backup=root/'backup.app'
            for directory,text in ((dest,'old'),(candidate,'new')):directory.mkdir();(directory/'version').write_text(text)
            source=Path(__file__).resolve().parents[1]/'native/macos/update_install.sh'
            helper=root/'helper.sh';helper.write_text(source.read_text().replace('limit=30','limit=2').replace('/bin/sleep 1','/bin/sleep 0.02').replace('/usr/bin/open -n','/usr/bin/false'))
            old=subprocess.Popen(['/bin/sleep','0.05']);old.wait()
            result=subprocess.run(['/bin/sh',str(helper),str(candidate),str(dest),str(backup),str(root/'ack'),str(old.pid),str(root/'pending'),str(root/'result')],timeout=5)
            self.assertEqual(1,result.returncode);self.assertEqual('old',(dest/'version').read_text());self.assertIn('восстановлена',(root/'result').read_text())
    def test_ready_new_app_keeps_original_as_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);dest=root/'Dagami.app';candidate=root/'candidate.app';backup=root/'backup.app'
            for directory,text in ((dest,'old'),(candidate,'new')):directory.mkdir();(directory/'version').write_text(text)
            ack=root/'ack';source=Path(__file__).resolve().parents[1]/'native/macos/update_install.sh'
            launcher=root/'launch.sh';launcher.write_text('#!/bin/sh\nprintf ready > "$UPDATE_FIXTURE_ACK"\n');launcher.chmod(0o700)
            helper=root/'helper.sh';helper.write_text(source.read_text().replace('/usr/bin/open',str(launcher)))
            old=subprocess.Popen(['/bin/sleep','0.01']);old.wait()
            result=subprocess.run(['/bin/sh',str(helper),str(candidate),str(dest),str(backup),str(ack),str(old.pid),str(root/'pending'),str(root/'result')],env=dict(os.environ,UPDATE_FIXTURE_ACK=str(ack)),timeout=5)
            self.assertEqual(0,result.returncode);self.assertEqual('new',(dest/'version').read_text());self.assertEqual('old',(backup/'version').read_text())

class RejectionTests(unittest.TestCase):
    def test_failed_hash_or_signature_never_changes_installed_app(self):
        import contextlib
        for failure in ('hash','signature'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp+'/state'}):
                root=Path(temp);app=root/'Dagami.app';exe=app/'Contents/MacOS/Dagami';exe.parent.mkdir(parents=True);exe.write_bytes(b'original')
                (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':updates.BUNDLE_ID}))
                archive=root/'source.zip'
                with zipfile.ZipFile(archive,'w') as z:z.writestr('Dagami.app/Contents/Info.plist',b'fixture')
                content=archive.read_bytes();digest=hashlib.sha256(content).hexdigest()
                tag='v0.4.0-mac.999-beta';release={'tag_name':tag,'draft':False,'assets':[{'name':updates.ZIP_NAME,'browser_download_url':'https://github.com/fixture.zip','size':len(content)},{'name':'SHA256SUMS.txt','browser_download_url':'https://github.com/sums'}]}
                def fetch(opener,url,limit,path=None):
                    if path:path.write_bytes(content);return digest
                    if url.endswith('/sums'):return ((('a'*64 if failure=='hash' else digest)+'  '+updates.ZIP_NAME)).encode()
                    return json.dumps(release).encode()
                @contextlib.contextmanager
                def connection(profile):yield object()
                with patch.dict(os.environ,{'DAGAMI_NATIVE_APP':str(exe)}),patch.object(updates,'connection',connection),patch.object(updates,'fetch',side_effect=fetch),patch.object(updates,'verify_bundle',side_effect=RuntimeError('bad signature')):
                    with self.assertRaises((ValueError,RuntimeError)):updates.install(tag)
                self.assertEqual(b'original',exe.read_bytes());self.assertFalse((updates.root()/'pending.json').exists())
