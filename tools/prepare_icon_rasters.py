from pathlib import Path
import hashlib,json
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]/'native/macos/BrandIcons'
SIZES=sorted({point*scale for point in (15,18,20,26) for scale in (1,2,3)})

def main():
    manifest=[]
    for source in sorted(ROOT.glob('*.png')):
        folder=ROOT/'raster'/source.stem;folder.mkdir(parents=True,exist_ok=True)
        with Image.open(source) as original:
            image=original.convert('RGBA').convert('RGBa')
            for size in SIZES:
                output=folder/(str(size)+'.png')
                image.resize((size,size),Image.Resampling.LANCZOS).convert('RGBA').save(output,optimize=True)
                manifest.append({'file':str(output.relative_to(ROOT)),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()})
    (ROOT/'raster-manifest.json').write_text(json.dumps({'method':'Premultiplied-alpha Lanczos; exact 1x/2x/3x display sizes','sizes':SIZES,'files':manifest},indent=2))
    print('Prepared',len(manifest),'antialiased icon rasters')

if __name__=='__main__':main()
