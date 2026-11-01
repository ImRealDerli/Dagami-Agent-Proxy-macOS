from pathlib import Path
import argparse,hashlib,json,os,plistlib,shutil,subprocess,sys,urllib.request,zipfile
ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'devproxy_pkg/assets/webdriver'

def fetch(url):
    if not url.startswith(('https://googlechromelabs.github.io/chrome-for-testing/','https://storage.googleapis.com/chrome-for-testing-public/')):raise ValueError('Untrusted WebDriver source')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url,timeout=90) as response:return response.read()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--version');args=parser.parse_args();ASSETS.mkdir(parents=True,exist_ok=True)
    manifest_path=ASSETS/'manifest.json';previous=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    version=args.version or previous.get('version')
    if not version:version=json.loads(fetch('https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json'))['channels']['Stable']['version']
    target=ROOT.parent/'SeleniumPackages';shutil.rmtree(target,ignore_errors=True)
    requirements=ROOT/'tools/requirements-webdriver.txt'
    install=['-r',str(requirements)] if requirements.exists() else ['selenium']
    subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-compile','--only-binary=:all:','--target',str(target),*install],check=True)
    frozen=subprocess.check_output([sys.executable,'-m','pip','freeze','--path',str(target)],text=True);requirements.write_text(frozen)
    vendor=ASSETS/'selenium-vendor.zip'
    with zipfile.ZipFile(vendor,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(target.rglob('*')):
            relative=path.relative_to(target)
            if any(part in ('__pycache__','bin') for part in relative.parts) or path.name.startswith('selenium-manager'):continue
            if path.is_file():archive.write(path,relative)
    manifest={'version':version,'vendor_sha256':hashlib.sha256(vendor.read_bytes()).hexdigest(),'drivers':{}}
    for platform in ('mac-x64','mac-arm64'):
        folder=ASSETS/platform;folder.mkdir(exist_ok=True);driver=folder/'chromedriver'
        url=f'https://storage.googleapis.com/chrome-for-testing-public/{version}/{platform}/chromedriver-{platform}.zip'
        payload=fetch(url);archive_path=ROOT.parent/(platform+'.zip');archive_path.write_bytes(payload)
        with zipfile.ZipFile(archive_path) as archive:
            prefix='chromedriver-'+platform+'/'
            for name in ('chromedriver','LICENSE.chromedriver','THIRD_PARTY_NOTICES.chromedriver'):
                if prefix+name in archive.namelist():
                    content=archive.read(prefix+name);destination=folder/name if name=='chromedriver' else ASSETS/name
                    if name!='chromedriver' and destination.exists() and destination.read_bytes()!=content:destination=ASSETS/(platform+'-'+name)
                    destination.write_bytes(content)
        driver.chmod(0o755);subprocess.run(['codesign','--force','--sign','-',str(driver)],check=True);subprocess.run(['codesign','--verify','--strict',str(driver)],check=True)
        manifest['drivers'][platform]={'url':url,'zip_sha256':hashlib.sha256(payload).hexdigest(),'sha256':hashlib.sha256(driver.read_bytes()).hexdigest()}
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n');print('Prepared Selenium and ChromeDriver',version)
if __name__=='__main__':main()
