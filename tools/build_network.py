from pathlib import Path
import argparse,json,os,subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT.parent/'Build'/'DagamiNetwork');args=parser.parse_args()
    output=args.output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
    target=output.parent/'rust-target';manifest=ROOT/'native/network/Cargo.toml'
    env=dict(os.environ,CARGO_TARGET_DIR=str(target),MACOSX_DEPLOYMENT_TARGET='13.0')
    binaries=[]
    for arch in ('x86_64-apple-darwin','aarch64-apple-darwin'):
        subprocess.run(['cargo','build','--locked','--release','--manifest-path',str(manifest),'--target',arch],env=env,check=True)
        binaries.append(target/arch/'release/dagami-network')
    subprocess.run(['/usr/bin/lipo','-create',*map(str,binaries),'-output',str(output)],check=True)
    arches=subprocess.check_output(['/usr/bin/lipo','-archs',str(output)],text=True).split()
    if not {'x86_64','arm64'}<=set(arches):raise RuntimeError('Rust-транспорт собран не для всех архитектур.')
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(output)],check=True)
    metadata=json.loads(subprocess.check_output(['cargo','metadata','--locked','--format-version','1','--manifest-path',str(manifest)],env=env))
    notices=['Dagami network transport — third-party licenses\n']
    for package in sorted(metadata['packages'],key=lambda package:package['name']):
        if not package.get('source'):continue
        notices.append('\n'+package['name']+' '+package['version']+' · '+str(package.get('license') or 'See license files')+'\n'+str(package.get('repository') or '')+'\n')
        directory=Path(package['manifest_path']).parent;files=set()
        for pattern in ('LICENSE*','LICENCE*','COPYING*','NOTICE*','COPYRIGHT*'):
            files.update(path for path in directory.glob(pattern) if path.is_file())
        for path in sorted(files):notices.append('\n'+path.name+'\n'+path.read_text(errors='replace')+'\n')
    output.with_suffix('.licenses.txt').write_text(''.join(notices))
    print(output)

if __name__=='__main__':main()
