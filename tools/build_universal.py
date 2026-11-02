
from pathlib import Path
import subprocess,shutil,os,plistlib,zipfile,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT.parent/'Release'
BUILD=ROOT.parent/'Build'
BASE=Path('/Library/Frameworks/Python.framework/Versions/3.12')
APP=OUTPUT/'Dagami.app'

def run(*args,**kwargs):return subprocess.run([str(x) for x in args],check=True,**kwargs)
def output(*args):return subprocess.check_output([str(x) for x in args],text=True)

def main():
 OUTPUT.mkdir(exist_ok=True);BUILD.mkdir(exist_ok=True)
 sdk=output('xcrun','--show-sdk-path').strip()
 sources=[ROOT/'native/macos/Dagami.swift',ROOT/'native/macos/OAuthClipboard.swift']
 binaries=[]
 for arch in ('x86_64','arm64'):
  binary=BUILD/f'Dagami-{arch}'
  if not binary.exists() or binary.stat().st_mtime<max(p.stat().st_mtime for p in sources):run('xcrun','swiftc','-swift-version','5','-Osize','-target',arch+'-apple-macos13.0','-sdk',sdk,'-parse-as-library',*sources,'-o',binary)
  binaries.append(binary)
 if APP.exists():shutil.rmtree(APP)
 contents=APP/'Contents';resources=contents/'Resources';macos=contents/'MacOS';macos.mkdir(parents=True);resources.mkdir()
 run('lipo','-create',*binaries,'-output',macos/'Dagami')
 run(sys.executable,ROOT/'tools/build_network.py','--output',BUILD/'DagamiNetwork')
 shutil.copy2(BUILD/'DagamiNetwork',macos/'DagamiNetwork')
 shutil.copy2(BUILD/'DagamiNetwork.licenses.txt',resources/'ThirdPartyRust.txt')
 engine=resources/'Engine';engine.mkdir()
 for item in ('devproxy_pkg','devproxy_gui.py','native'):
  source=ROOT/item
  if source.is_dir():shutil.copytree(source,engine/item,ignore=shutil.ignore_patterns('__pycache__','*.pyc','target'))
  else:shutil.copy2(source,engine/item)
                                                                                      
 for driver in (engine/'devproxy_pkg/assets/webdriver').glob('mac-*/chromedriver'):driver.chmod(0o755)
 runtime=resources/'Python.framework/Versions/3.12';(runtime/'bin').mkdir(parents=True)
 (runtime/'Resources').mkdir();shutil.copy2(BASE/'Resources/Info.plist',runtime/'Resources/Info.plist');shutil.copytree(BASE/'Resources/Python.app',runtime/'Resources/Python.app')
 (runtime.parent/'Current').symlink_to('3.12');framework=runtime.parents[1];(framework/'Python').symlink_to('Versions/Current/Python');(framework/'Resources').symlink_to('Versions/Current/Resources')
 shutil.copy2(BASE/'Python',runtime/'Python');shutil.copy2(BASE/'bin/python3.12',runtime/'bin/python3.12')
 shutil.copytree(BASE/'lib/python3.12',runtime/'lib/python3.12',ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip','config-*','*.a','_tkinter*','*.pyc'))
 copied=set()
 def dependencies(path):
  if path.name=='Python' or path.suffix=='.dylib':
   run('install_name_tool','-id','@rpath/'+path.name,path,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for line in output('otool','-L',path).splitlines()[1:]:
   dependency=line.strip().split(' (')[0]
   if not dependency.startswith(str(BASE)+'/'):continue
   relative=Path(dependency).relative_to(BASE);dest=runtime/relative
   if not dest.exists():
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dependency,dest)
   replacement='@loader_path/'+os.path.relpath(dest,path.parent)
   run('install_name_tool','-change',dependency,replacement,path,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   if dest not in copied:
    copied.add(dest);dependencies(dest)
 macho=[]
 for path in runtime.rglob('*'):
  if path.is_file() and path.read_bytes()[:4] in (b'\xca\xfe\xba\xbe',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xbe\xba\xfe\xca'):
   macho.append(path)
 for path in list(macho):dependencies(path)
                                                                                      
 for path in runtime.rglob('*'):
  if path.is_file() and path.read_bytes()[:4] in (b'\xca\xfe\xba\xbe',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xbe\xba\xfe\xca'):
   arches=output('lipo','-archs',path).split()
   if not {'x86_64','arm64'}<=set(arches):raise RuntimeError('Non-universal runtime: '+str(path))
   for line in output('otool','-L',path).splitlines()[1:]:
    dep=line.strip().split(' (')[0]
    if dep.startswith('/Library/') or dep.startswith('/usr/local/'):raise RuntimeError('External dependency: '+dep)
   run('codesign','--force','--sign','-',path,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 certificate=BASE/'lib/python3.12/site-packages/certifi/cacert.pem'
 if not certificate.exists():raise RuntimeError('Python.org certifi roots missing')
 shutil.copy2(certificate,resources/'cacert.pem')
 shutil.copy2(ROOT/'LICENSE',resources/'LICENSE')
 shutil.copy2(ROOT/'devproxy_pkg/assets/dagami-agent-proxy.icns',resources/'Dagami.icns')
 info={'CFBundleName':'Dagami','CFBundleDisplayName':'Dagami','CFBundleIdentifier':'ru.dagami.agentproxy.native','CFBundleExecutable':'Dagami','CFBundleIconFile':'Dagami.icns','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.4.1','CFBundleVersion':'428','LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication','NSHumanReadableCopyright':'Dagami Agent Proxy · MIT'}
 (contents/'Info.plist').write_bytes(plistlib.dumps(info))
 run('codesign','--force','--deep','--sign','-',APP,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 run('codesign','--verify','--deep','--strict',APP)
                                                                                     
 env=dict(os.environ,PYTHONHOME=str(runtime),SSL_CERT_FILE=str(resources/'cacert.pem'),PYTHONNOUSERSITE='1')
 run(runtime/'bin/python3.12','-B','-I','-c','import ssl,ctypes,sqlite3,socket,platform;print("BUNDLED RUNTIME",platform.machine(),ssl.OPENSSL_VERSION)',env=env)
 run('ditto','-c','-k','--sequesterRsrc','--keepParent',APP,OUTPUT/'Dagami-macOS-Universal.zip')
 sourcezip=OUTPUT/'Dagami-Full-Source.zip'
 with zipfile.ZipFile(sourcezip,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(ROOT.rglob('*')):
   rel=p.relative_to(ROOT)
   if any(part in ('.git','__pycache__','.venv','dist-portable','target') for part in rel.parts) or p.suffix in ('.pyc','.DS_Store'):continue
   if p.is_file():z.write(p,Path('Dagami-Source')/rel)
 manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUTPUT.glob('*.zip')}
 (OUTPUT/'SHA256SUMS.txt').write_text(''.join(v+'  '+k+'\n' for k,v in manifest.items()))
 print('APP:',APP,flush=True)

if __name__=='__main__':main()
