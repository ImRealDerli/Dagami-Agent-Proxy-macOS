from pathlib import Path
import os,sys,subprocess,plistlib,shutil,hashlib
from ds_store import DSStore
from mac_alias import Alias
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT.parent/'Build';OUT=ROOT.parent/'Release';APP=OUT/'Dagami.app'
def run(*args,**kwargs):return subprocess.run([str(v) for v in args],check=True,**kwargs)
def main():
 BUILD.mkdir(exist_ok=True);mount=BUILD/'Volume';image=BUILD/'Dagami-install.dmg';target=OUT/'Dagami-macOS-Universal.dmg'
 painter=BUILD/'DmgArtwork';art=BUILD/'background.png'
 run('xcrun','swiftc',ROOT/'native/macos/DmgArtwork.swift','-o',painter)
 run(painter,art)
 if image.exists():image.unlink()
 run('hdiutil','create','-size','300m','-fs','HFS+','-volname','Dagami',image,stdout=subprocess.DEVNULL)
 run('hdiutil','attach','-nobrowse','-mountpoint',mount,image,stdout=subprocess.DEVNULL)
 try:
  run('ditto',APP,mount/'Dagami.app')
  (mount/'Applications').symlink_to('/Applications')
  (mount/'.background').mkdir();shutil.copy2(art,mount/'.background/background.png')
  options={'viewOptionsVersion':1,'backgroundType':2,'backgroundImageAlias':Alias.for_file(str(mount/'.background/background.png')).to_bytes(),'iconSize':128.0,'gridSpacing':100.0,'gridOffsetX':0.0,'gridOffsetY':0.0,'arrangeBy':'none','showIconPreview':True,'showItemInfo':False,'labelOnBottom':True,'textSize':14.0}
  window={'ShowStatusBar':False,'ShowToolbar':False,'ShowTabView':False,'ShowSidebar':False,'ShowPathbar':False,'WindowBounds':'{{100, 80}, {960, 620}}','SidebarWidth':0}
  with DSStore.open(str(mount/'.DS_Store'),'w+') as ds:
   ds['.']['bwsp']=window;ds['.']['icvp']=options;ds['.']['vSrn']=('long',1)
   ds['Dagami.app']['Iloc']=(255,350);ds['Applications']['Iloc']=(705,350)
  os.chmod(mount,0o755)
 finally:run('hdiutil','detach',mount,stdout=subprocess.DEVNULL)
 if target.exists():target.unlink()
 run('hdiutil','convert',image,'-format','UDZO','-imagekey','zlib-level=9','-o',target,stdout=subprocess.DEVNULL)
 run('hdiutil','verify',target,stdout=subprocess.DEVNULL)
 print(target)
if __name__=='__main__':main()
