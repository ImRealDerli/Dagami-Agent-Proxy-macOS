from pathlib import Path
import argparse, os, plistlib, shutil, subprocess

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT.parent

def run(*args):
    subprocess.run([str(x) for x in args],check=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime-app',type=Path,default=DEST.parent/'Dagami.app')
    args=parser.parse_args()
    if not args.runtime_app.is_dir():
        raise SystemExit('Укажите готовую universal-сборку Dagami через --runtime-app')
    app=DEST/'Dagami Test.app'
    build=DEST/'.Build'
    build.mkdir(exist_ok=True)
    sdk=subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
    sources=[ROOT/'native/macos/Dagami.swift',ROOT/'native/macos/OAuthClipboard.swift']
    for arch in ('x86_64','arm64'):
        run('xcrun','swiftc','-swift-version','5','-Osize','-target',arch+'-apple-macos13.0','-sdk',sdk,'-parse-as-library',*sources,'-o',build/arch)
    if app.exists():
        shutil.rmtree(app)
    run('/usr/bin/ditto',args.runtime_app,app)
    run('lipo','-create',build/'x86_64',build/'arm64','-output',app/'Contents/MacOS/Dagami')
    resources=app/'Contents/Resources'
    engine=resources/'Engine'
    for item in ('native','devproxy_pkg'):
        shutil.rmtree(engine/item)
        shutil.copytree(ROOT/item,engine/item,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    info_path=app/'Contents/Info.plist'
    info=plistlib.loads(info_path.read_bytes())
    info.update(CFBundleName='Dagami Test',CFBundleDisplayName='Dagami · Тест',CFBundleIdentifier='ru.dagami.agentproxy.designtest',DagamiDesignTest=True,CFBundleShortVersionString='0.4.1',CFBundleVersion='427')
    info_path.write_bytes(plistlib.dumps(info))
    run('codesign','--force','--deep','--sign','-',app)
    run('codesign','--verify','--deep','--strict',app)
    shutil.rmtree(build)
    print(app)

if __name__=='__main__':
    main()
