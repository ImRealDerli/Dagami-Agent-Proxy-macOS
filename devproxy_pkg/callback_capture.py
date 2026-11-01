import json,time
from urllib.parse import urlsplit


class CallbackCapture:
    world='DagamiOAuthCallback'
    def __init__(self,endpoint,target,port,callback):
        parsed=urlsplit(endpoint)
        if parsed.scheme!='ws' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.port!=port:raise ValueError('Invalid local browser debugger endpoint')
        import websocket
        self.socket=websocket.create_connection(endpoint,timeout=3,suppress_origin=True)
        self.sequence=0;self.target=target
        scheme,host,number,path=callback
        source='''(()=>{const u=new URL(location.href);const expected=EXPECTED;
if(u.protocol.slice(0,-1)!==expected[0]||u.hostname!==expected[1]||Number(u.port||(u.protocol==='https:'?443:80))!==expected[2]||u.pathname!==expected[3])return;
Object.defineProperty(globalThis,'dagamiProof',{value:Object.freeze({url:u.href}),writable:false,configurable:false});})();'''.replace('EXPECTED',json.dumps([scheme,host,number,path]))
        self.command('Page.enable')
        self.command('Page.addScriptToEvaluateOnNewDocument',{'source':source,'worldName':self.world})
    def command(self,method,params=None):
        self.sequence+=1;identifier=self.sequence
        self.socket.send(json.dumps({'id':identifier,'method':method,'params':params or {}}))
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            item=json.loads(self.socket.recv())
            if item.get('id')!=identifier:continue
            if 'error' in item:raise RuntimeError('Browser callback capture command failed: '+method)
            return item.get('result',{})
        raise TimeoutError('Browser callback capture timed out')
    def navigate(self,url):self.command('Page.navigate',{'url':url})
    def proof(self):
        try:
            tree=self.command('Page.getFrameTree');frame=tree['frameTree']['frame']['id']
            world=self.command('Page.createIsolatedWorld',{'frameId':frame,'worldName':self.world})
            result=self.command('Runtime.evaluate',{'contextId':world['executionContextId'],'expression':'globalThis.dagamiProof || null','returnByValue':True})
            return result.get('result',{}).get('value')
        except (OSError,ValueError,KeyError,RuntimeError):return None
    def close(self):
        try:self.socket.close()
        except OSError:pass
