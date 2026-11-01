import contextlib,hashlib,json,os,plistlib,re,shutil,stat,subprocess,tempfile,time,urllib.parse,urllib.request,uuid,zipfile
from pathlib import Path,PurePosixPath
from .core.recovery import get_devproxy_state_path
from .core.process_env import independent_environment

REPOSITORY='ImRealDerli/Dagami-Agent-Proxy-macOS'
BUNDLE_ID='ru.dagami.agentproxy.native'
HOSTS=frozenset(('api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com'))
ZIP_NAME='Dagami-macOS-Universal.zip'


def version(tag):
    match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:b\d+\+mac\.|-mac\.)(\d+)(?:-beta)?',tag)
    if not match:raise ValueError('Неподдерживаемый номер версии Dagami.')
    return tuple(map(int,match.groups()))


def root():
    path=Path(get_devproxy_state_path()).parent/'updates'
    if path.is_symlink():raise ValueError('Недопустимый каталог обновлений.')
    path.mkdir(parents=True,exist_ok=True,mode=0o700);path.chmod(0o700);return path


def validate_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None,443):raise ValueError('Недопустимый адрес обновления.')
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,message,headers,url):
        validate_url(url);return super().redirect_request(request,fp,code,message,headers,url)


class BridgeProxy(urllib.request.BaseHandler):
    handler_order=100
    def __init__(self,address):self.address=address
    def https_open(self,request):request.set_proxy(self.address,'http')


@contextlib.contextmanager
def connection(profile=''):
    tunnel=None
    try:
        if profile:
            from .portable_runtime import load_profile
            from .core.tunnel import LocalTunnel
            tunnel=LocalTunnel(load_profile(profile));proxy='127.0.0.1:'+str(tunnel.start())
            handler=BridgeProxy(proxy)
        else:handler=urllib.request.ProxyHandler({})
        yield urllib.request.build_opener(urllib.request.ProxyHandler({}),handler,Redirects())
    finally:
        if tunnel:tunnel.stop()


def fetch(opener,url,limit,path=None):
    validate_url(url);request=urllib.request.Request(url,headers={'User-Agent':'Dagami-macOS-Updater','Accept':'application/vnd.github+json' if urllib.parse.urlsplit(url).hostname=='api.github.com' else '*/*'})
    digest=hashlib.sha256();count=0;parts=[]
    with opener.open(request,timeout=30) as response:
        validate_url(response.geturl())
        with path.open('wb') if path else contextlib.nullcontext() as stream:
            while True:
                chunk=response.read(65536)
                if not chunk:break
                count+=len(chunk)
                if count>limit:raise ValueError('Файл обновления превышает допустимый размер.')
                digest.update(chunk)
                if stream:stream.write(chunk)
                else:parts.append(chunk)
    return digest.hexdigest() if path else b''.join(parts)


def select_release(releases,current):
    current_version=version(current);candidates=[]
    for release in releases:
        if release.get('draft'):continue
        try:value=version(release.get('tag_name',''))
        except ValueError:continue
        if value<=current_version:continue
        assets=release.get('assets',[])
        if not all(sum(a.get('name')==name for a in assets)==1 for name in (ZIP_NAME,'SHA256SUMS.txt')):continue
        candidates.append((value,release))
    return max(candidates,key=lambda item:item[0])[1] if candidates else None


def release_details(release):
    body=release.get('body') or '';metadata={}
    match=re.search(r'<!--\s*dagami-update:\s*(\{[^\n]*\})\s*-->',body)
    if match:
        try:metadata=json.loads(match[1])
        except ValueError:pass
        body=body[:match.start()]+body[match.end():]
    severity=metadata.get('severity','unspecified')
    recommendation=metadata.get('recommendation','recommended' if severity=='critical' else 'optional')
    if severity not in ('normal','important','critical'):severity='unspecified'
    if recommendation not in ('optional','recommended','required'):recommendation='optional'
    return {'notes':body.strip()[:16000],'severity':severity,'recommendation':recommendation}


def check(profile=''):
    from . import __version__
    with connection(profile) as opener:data=json.loads(fetch(opener,'https://api.github.com/repos/'+REPOSITORY+'/releases?per_page=50',2*1024*1024))
    if not isinstance(data,list):raise ValueError('GitHub вернул некорректный список выпусков.')
    release=select_release(data,__version__)
    result={'available':bool(release),'current':__version__,'currentBuild':400+version(__version__)[3],'tag':release['tag_name'] if release else '', 'url':release['html_url'] if release else 'https://github.com/'+REPOSITORY+'/releases','notes':'','severity':'unspecified','recommendation':'optional'}
    if release:result.update(release_details(release))
    last=root()/'last-result.txt';result['lastResult']=last.read_text()[:2000] if last.is_file() else ''
    return result



def checksum(data):
    matches=[]
    for line in data.decode('utf-8').splitlines():
        match=re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?'+re.escape(ZIP_NAME),line)
        if match:matches.append(match[1].lower())
    if len(matches)!=1:raise ValueError('В SHA256SUMS.txt нет единственной суммы ZIP приложения.')
    return matches[0]


def validate_archive(path):
    total=0;names=set()
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            name=PurePosixPath(item.filename)
            if not name.parts or name.is_absolute() or '..' in name.parts or '\\' in item.filename or '\x00' in item.filename:raise ValueError('Небезопасный путь в ZIP.')
            if name.parts[0] not in ('Dagami.app','__MACOSX'):raise ValueError('В архиве найден посторонний файл.')
            if item.filename in names:raise ValueError('Повторяющийся путь в ZIP.')
            names.add(item.filename);total+=item.file_size
            if total>1024*1024*1024 or len(names)>20000:raise ValueError('Слишком большой распакованный архив.')
            if stat.S_ISLNK(item.external_attr>>16):
                if item.file_size>4096:raise ValueError('Некорректная ссылка в ZIP.')
                target=archive.read(item).decode('utf-8');parts=list(name.parent.parts)
                if target.startswith('/') or '\\' in target or '..' in PurePosixPath(target).parts:raise ValueError('Внешняя ссылка в ZIP.')
                for part in PurePosixPath(target).parts:
                    if part=='..':
                        if len(parts)<=1:raise ValueError('Ссылка выходит за пределы приложения.')
                        parts.pop()
                    elif part!='.':parts.append(part)
        for item in archive.infolist():
            for parent in PurePosixPath(item.filename).parents:
                if str(parent) in names:
                    candidate=archive.getinfo(str(parent))
                    if stat.S_ISLNK(candidate.external_attr>>16):raise ValueError('Файл под символической ссылкой в ZIP.')


def verify_bundle(bundle,expected):
    info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier')!=BUNDLE_ID or info.get('CFBundleExecutable')!='Dagami':raise ValueError('ZIP содержит другое приложение.')
    if str(info.get('CFBundleVersion'))!=str(400+version(expected)[3]) or info.get('CFBundleShortVersionString')!='.'.join(map(str,version(expected)[:3])):raise ValueError('Версия приложения не совпадает с выпуском.')
    import platform
    if tuple(map(int,platform.mac_ver()[0].split('.'))) < tuple(map(int,info.get('LSMinimumSystemVersion','13.0').split('.'))):raise ValueError('Обновление требует более новой macOS.')
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(bundle)],check=True,capture_output=True)
    arches=subprocess.check_output(['/usr/bin/lipo','-archs',str(bundle/'Contents/MacOS/Dagami')],text=True).split()
    if not {'x86_64','arm64'}<=set(arches):raise ValueError('Обновление не является Universal-сборкой.')


def destination():
    executable=Path(os.environ.get('DAGAMI_NATIVE_APP',''))
    if not executable.is_absolute() or executable.name!='Dagami' or executable.parent.name!='MacOS':raise ValueError('Обновление доступно из приложения Dagami.')
    bundle=executable.parents[2]
    if bundle.is_symlink() or bundle.suffix!='.app' or '/AppTranslocation/' in str(bundle) or str(bundle).startswith('/Volumes/'):raise ValueError('Сначала перенесите Dagami в «Программы» или другую доступную для записи папку.')
    if not os.access(bundle.parent,os.W_OK):raise PermissionError('Нет права записи в папку Dagami. Перенесите приложение в ~/Applications или обновите его вручную через DMG.')
    info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier')!=BUNDLE_ID:raise ValueError('Нельзя обновлять другое приложение.')
    return bundle


def helper_active(data):
    pid=data.get('helperPid',0)
    if not isinstance(pid,int) or pid<1:return False
    try:
        result=subprocess.run(['/bin/ps','-p',str(pid),'-o','args='],capture_output=True,text=True,timeout=3)
        return result.returncode==0 and str(Path(data['ack']).parent/'install.sh') in result.stdout
    except (OSError,subprocess.SubprocessError):return True


def install(tag,profile=''):
    from . import __version__
    from .portable_runtime import session_lock
    gui_pid=os.getppid()
    with session_lock('app-update'):
        pending=root()/'pending.json'
        if pending.exists():
            data=json.loads(pending.read_text())
            if helper_active(data) or time.time()-pending.stat().st_mtime<10:raise RuntimeError('Другая установка обновления ещё выполняется.')
            pending.unlink()
        dest=destination()
        with connection(profile) as opener:
            release=json.loads(fetch(opener,'https://api.github.com/repos/'+REPOSITORY+'/releases/tags/'+urllib.parse.quote(tag,safe=''),2*1024*1024))
            if release.get('tag_name')!=tag or not select_release([release],__version__):raise ValueError('Выпуск уже установлен или недоступен.')
            assets={a['name']:a for a in release['assets']};sums=checksum(fetch(opener,assets['SHA256SUMS.txt']['browser_download_url'],65536))
            asset=assets[ZIP_NAME]
            if asset.get('size',0)>256*1024*1024:raise ValueError('Обновление превышает допустимый размер.')
            work=Path(tempfile.mkdtemp(prefix='install-',dir=root()));candidate=None
            try:
                archive=work/'update.zip';actual=fetch(opener,asset['browser_download_url'],256*1024*1024,archive)
                if actual!=sums or asset.get('digest') and asset['digest']!='sha256:'+actual:raise ValueError('SHA-256 обновления не совпал. Установка отменена.')
                validate_archive(archive);unpacked=work/'unpacked';unpacked.mkdir()
                subprocess.run(['/usr/bin/ditto','-x','-k',str(archive),str(unpacked)],check=True,capture_output=True)
                bundle=unpacked/'Dagami.app';verify_bundle(bundle,tag)
                if os.getppid()!=gui_pid:raise RuntimeError('Установка отменена: окно Dagami закрыто.')
                nonce=uuid.uuid4().hex;candidate=dest.parent/('.Dagami-update-'+nonce+'.app');backup=dest.parent/('.Dagami-previous-'+nonce+'.app')
                candidate.mkdir(mode=0o700)
                subprocess.run(['/usr/bin/ditto',str(bundle),str(candidate)],check=True,capture_output=True);verify_bundle(candidate,tag)
                ack=work/'ack';receipt={'destination':str(dest),'version':400+version(tag)[3],'ack':str(ack),'backup':str(backup)}
                pending=root()/'pending.json';pending.write_text(json.dumps(receipt));pending.chmod(0o600)
                helper=work/'install.sh';shutil.copy2(Path(__file__).resolve().parent.parent/'native/macos/update_install.sh',helper);helper.chmod(0o700)
                process=subprocess.Popen(['/bin/sh',str(helper),str(candidate),str(dest),str(backup),str(ack),str(gui_pid),str(pending),str(root()/'last-result.txt')],env=independent_environment(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                receipt['helperPid']=process.pid;pending.write_text(json.dumps(receipt));pending.chmod(0o600)
            except BaseException:
                if candidate:shutil.rmtree(candidate,ignore_errors=True)
                (root()/'pending.json').unlink(missing_ok=True);shutil.rmtree(work,ignore_errors=True);raise
    return 'Обновление проверено. Dagami перезапускается; профили и аккаунты сохранены.'


def acknowledge():
    pending=root()/'pending.json'
    if not pending.is_file() or pending.is_symlink():return False
    data=json.loads(pending.read_text());dest=Path(data['destination']);ack=Path(data['ack'])
    if os.environ.get('DAGAMI_NATIVE_APP')!=str(dest/'Contents/MacOS/Dagami') or not ack.resolve().is_relative_to(root().resolve()):return False
    from . import __version__
    if 400+version(__version__)[3]!=data['version']:return False
    info=plistlib.loads((dest/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier')!=BUNDLE_ID or str(info.get('CFBundleVersion'))!=str(data['version']):return False
    ack.write_text('ready');ack.chmod(0o600)
    history=root()/'backups.json'
    try:backups=json.loads(history.read_text()) if history.exists() else []
    except ValueError:backups=[]
    keep=Path(data['backup']);remaining=[]
    processes=subprocess.check_output(['/bin/ps','-axo','comm='],text=True).splitlines()
    for raw in list(dict.fromkeys(backups+[str(keep)])):
        path=Path(raw)
        if path.parent!=dest.parent or not re.fullmatch(r'\.Dagami-previous-[a-f0-9]{32}\.app',path.name) or path.is_symlink():continue
        if path==keep or any(line.strip().startswith(str(path)+'/') for line in processes):remaining.append(raw);continue
        try:
            info=plistlib.loads((path/'Contents/Info.plist').read_bytes())
            if info.get('CFBundleIdentifier')==BUNDLE_ID:shutil.rmtree(path)
        except (OSError,ValueError):remaining.append(raw)
    history.write_text(json.dumps(remaining));history.chmod(0o600)
    if not helper_active(data):pending.unlink(missing_ok=True)
    return True
