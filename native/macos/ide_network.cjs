'use strict';
const http=require('node:http');
const https=require('node:https');
const tls=require('node:tls');
const {Readable}=require('node:stream');
function proxyURL(){
    const proxy=new URL(process.env.DAGAMI_IDE_PROXY||'');
    if(proxy.protocol!=='http:'||proxy.hostname!=='127.0.0.1'||!proxy.port||proxy.username||proxy.password)throw new Error('Dagami IDE requires its local proxy bridge.');
    return proxy;
}
class TunnelAgent extends https.Agent{
    createConnection(options,done){
        const proxy=proxyURL();let settled=false;
        const finish=(error,socket)=>{if(settled){if(socket)socket.destroy();return;}settled=true;done(error,socket);};
        const hostname=options.servername||options.host;
        const request=http.request({hostname:proxy.hostname,port:proxy.port,method:'CONNECT',path:hostname+':'+(options.port||443),headers:{Host:hostname+':'+(options.port||443)},timeout:30000});
        request.on('connect',(response,socket,head)=>{
            if(response.statusCode!==200){socket.destroy();finish(new Error('Dagami bridge returned HTTP '+response.statusCode));return;}
            request.setTimeout(0);
            if(head.length)socket.unshift(head);
            const secure=tls.connect({...options,socket,servername:hostname,rejectUnauthorized:true});
            secure.once('secureConnect',()=>finish(null,secure));secure.once('error',finish);
        });
        request.once('timeout',()=>request.destroy(new Error('Dagami CONNECT timeout')));
        request.once('error',finish);request.end();
    }
}
async function fetchThroughBridge(address,options={},depth=0){
    proxyURL();const url=new URL(String(address));
    if(url.protocol!=='https:'||url.username||url.password)throw new Error('Dagami IDE setup requires an HTTPS endpoint.');
    if(options.body!=null||!['GET','HEAD'].includes(options.method||'GET'))throw new Error('Unsupported Dagami IDE setup request.');
    const agent=new TunnelAgent({keepAlive:false});
    return new Promise((resolve,reject)=>{
        const requestHeaders=new Headers(options.headers);requestHeaders.set('accept-encoding','identity');
        const request=https.request(url,{method:options.method||'GET',headers:Object.fromEntries(requestHeaders),agent,signal:options.signal},response=>{
            if([301,302,303,307,308].includes(response.statusCode)&&response.headers.location){
                response.resume();if(depth>=5){reject(new Error('Too many setup redirects'));return;}
                resolve(fetchThroughBridge(new URL(response.headers.location,url),options,depth+1));return;
            }
            const headers=new Headers();
            for(const [key,value] of Object.entries(response.headers))if(value!=null)headers.set(key,Array.isArray(value)?value.join(', '):value);
            const empty=options.method==='HEAD'||[204,205,304].includes(response.statusCode);
            if(empty)response.resume();
            const result=new Response(empty?null:Readable.toWeb(response),{status:response.statusCode,statusText:response.statusMessage,headers});
            Object.defineProperty(result,'url',{value:url.href});resolve(result);
        });
        request.once('error',error=>{agent.destroy();reject(error);});request.end();
    });
}
async function openExternal(original,...args){
    let url;try{url=new URL(String(args[0]));}catch{return original(...args);}
    if(url.protocol!=='https:'||url.hostname!=='accounts.google.com'||!url.searchParams.has('client_id')||!url.searchParams.has('state'))return original(...args);
    const port=Number(process.env.DAGAMI_AUTH_PORT),token=process.env.DAGAMI_AUTH_TOKEN;
    if(!token||!Number.isInteger(port)||port<1||port>65535)throw new Error('Dagami authentication bridge is unavailable. Launch IDE through Dagami.');
    const body=JSON.stringify({command:'login',url:url.href});
    await new Promise((resolve,reject)=>{
        const request=http.request({hostname:'127.0.0.1',port,path:'/',method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)},timeout:30000},response=>{
            response.resume();response.once('end',()=>response.statusCode===200?resolve():reject(new Error('Dagami could not open the authentication route. See its journal.')));
        });
        request.once('timeout',()=>request.destroy(new Error('Dagami authentication timeout')));request.once('error',reject);request.end(body);
    });
    return true;
}
module.exports={fetch:fetchThroughBridge,openExternal};
