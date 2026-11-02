from pathlib import Path
import urllib.request,concurrent.futures,json,re,subprocess,hashlib
import resvg_py
root=Path(__file__).resolve().parents[1]/'native/macos/BrandIcons'
svgdir=root/'svg';svgdir.mkdir(exist_ok=True)
base='https://raw.githubusercontent.com/lobehub/lobe-icons/master/packages/static-svg/icons/'
simple='https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/'
names=['antigravity','openai','claude','gemini','github','deepseek','qwen','grok','perplexity','mistral','openrouter','copilot','ollama','opencode','cursor','windsurf','vscode','vscodium','git']
colors={'git':'#F05032','vscode':'#007ACC','vscodium':'#2F80ED'}
def download(name):
 urls=([simple+'git.svg'] if name=='git' else [base+name+'-color.svg',base+name+'.svg',simple+('visualstudiocode' if name=='vscode' else name)+'.svg'])
 if name=='vscodium':urls.insert(0,'https://raw.githubusercontent.com/VSCodium/vscodium/master/icons/stable/codium_cnl.svg')
 for url in urls:
  try:
   with urllib.request.urlopen(url,timeout=18) as r:data=r.read()
   text=data.decode();assert '<svg' in text
   (svgdir/(name+'.svg')).write_bytes(data)
   return name,url,text
  except Exception:pass
 return name,'',''
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:downloaded=list(pool.map(download,names))
manifest=[]
for name,url,svg in downloaded:
 if not svg:
  print('MISSING',name,flush=True);continue
 for theme in ['light','dark']:
  color=colors.get(name,'#FFFFFF' if theme=='dark' else '#171717')
  text=svg.replace('currentColor',color)
  match=re.search(r'<svg\b[^>]*>',text);header=match.group()
  header=re.sub(r'\s(?:width|height)=["\'][^"\']*["\']','',header)
  header=header[:-1]+' width="1024" height="1024">'
  text=text[:match.start()]+header+text[match.end():]
  temp=Path('/tmp')/('dagami-brand-'+name+'-'+theme+'.svg');temp.write_text(text)
  out=root/(name+'-'+theme+'.png')
  out.write_bytes(resvg_py.svg_to_bytes(svg_string=text,width=1024,height=1024))
  temp.unlink()
  manifest.append({'file':out.name,'url':url,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'svg':str(Path('svg')/(name+'.svg')),'svg_sha256':hashlib.sha256(svg.encode()).hexdigest(),'size':1024})
 print('READY',name,flush=True)
with urllib.request.urlopen('https://raw.githubusercontent.com/simple-icons/simple-icons/develop/LICENSE.md',timeout=20) as r:(root/'LICENSE-simple-icons.txt').write_bytes(r.read())
(root/'sources.json').write_text(json.dumps({'sources':['https://github.com/lobehub/lobe-icons','https://github.com/simple-icons/simple-icons','https://github.com/VSCodium/vscodium'],'conversion':'SVG rendered by resvg-py to antialiased 1024px PNG','icons':manifest},ensure_ascii=False,indent=2))

if not any(x['file']=='vscode-light.png' for x in manifest):
 url='https://raw.githubusercontent.com/microsoft/vscode/main/resources/linux/code.png'
 with urllib.request.urlopen(url,timeout=20) as response:data=response.read()
 if not data.startswith(b'\x89PNG'):raise ValueError('Invalid VS Code image')
 (svgdir/'vscode-original.png').write_bytes(data)
 for theme in ['light','dark']:
  name='vscode-'+theme+'.png';(root/name).write_bytes(data)
  manifest.append({'file':name,'url':url,'sha256':hashlib.sha256(data).hexdigest(),'original':'svg/vscode-original.png'})
for name,url in [('LICENSE-vscode.txt','https://raw.githubusercontent.com/microsoft/vscode/main/LICENSE.txt'),('LICENSE-vscodium.txt','https://raw.githubusercontent.com/VSCodium/vscodium/master/LICENSE'),('LICENSE-lobe-icons.txt','https://raw.githubusercontent.com/lobehub/lobe-icons/master/LICENSE')]:
 with urllib.request.urlopen(url,timeout=20) as response:(root/name).write_bytes(response.read())
(root/'sources.json').write_text(json.dumps({'sources':['https://github.com/lobehub/lobe-icons','https://github.com/simple-icons/simple-icons','https://github.com/microsoft/vscode','https://github.com/VSCodium/vscodium'],'conversion':'SVG rendered by resvg-py to antialiased 1024px PNG; official VS Code PNG unchanged','icons':manifest},ensure_ascii=False,indent=2))

subprocess.run([__import__("sys").executable,str(Path(__file__).with_name("prepare_icon_rasters.py"))],check=True)
