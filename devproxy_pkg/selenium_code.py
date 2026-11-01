import hashlib,hmac,http.client,json,os,platform,plistlib,re,socket,subprocess,sys,threading,time,warnings
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from .core.launcher import Launcher
from .core.process_env import external_environment

CALLBACK=('https','antigravity.google',443,'/oauth-callback')


def callback_state_matches(url,state,callback=CALLBACK):
    try:
        parsed=urlsplit(url);query=parse_qs(parsed.query)
        return bool(state) and not parsed.username and not parsed.password and (parsed.scheme,parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),parsed.path)==callback and len(query.get('state',[]))==1 and hmac.compare_digest(query['state'][0],state) and 'error' not in query
    except ValueError:return False


def valid_code(value):return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9._~+/=-]{10,8192}',value) is not None


def callback_code(url,state,values=(),callback=CALLBACK):
    if not callback_state_matches(url,state,callback):return None
    query=parse_qs(urlsplit(url).query)
    if len(query.get('code',[]))==1 and valid_code(query['code'][0]):return query['code'][0]
    for value in values:
        if valid_code(value):return value
    return None


def webdriver_assets():
    root=Path(__file__).resolve().parent/'assets/webdriver';manifest=json.loads((root/'manifest.json').read_text())
    vendor=root/'selenium-vendor.zip';arch='mac-arm64' if platform.machine()=='arm64' else 'mac-x64';driver=root/arch/'chromedriver'
    if hashlib.sha256(vendor.read_bytes()).hexdigest()!=manifest['vendor_sha256'] or hashlib.sha256(driver.read_bytes()).hexdigest()!=manifest['drivers'][arch]['sha256']:raise RuntimeError('Повреждены зависимости Selenium. Переустановите текущую сборку Dagami.')
    if str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
    return driver,manifest


class SeleniumCodeBrowser:
    def __init__(self,browser,args,env,url,on_code,on_error=None,callback=CALLBACK):
        self.driver_path,self.manifest=webdriver_assets();self.browser=browser;self.on_code=on_code;self.on_error=on_error or (lambda message:None);self.callback=callback
        self.lock=threading.RLock();self.state='';self.pending_url=None;self.delivered=set();self.stop_event=threading.Event();self.driver=None;self.service=None;self.extra_processes=[];self.environment=dict(env)
        self.state=self._url_state(url)
        reserve=socket.socket();reserve.bind(('127.0.0.1',0));self.port=reserve.getsockname()[1];reserve.close()
        launch_args=[*args[:-1],'--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(self.port),'--no-first-run','--no-default-browser-check',url]
        self.launch_args=launch_args
        self.process=Launcher.launch(browser,launch_args,env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.thread=threading.Thread(target=self._run,daemon=True,name='DagamiSeleniumCode');self.thread.start()
    def _url_state(self,url):
        query=parse_qs(urlsplit(url).query);states=query.get('state',[])
        if len(states)!=1 or not states[0]:raise ValueError('Для Selenium нужна исходная OAuth-ссылка с state.')
        return states[0]
    def navigate(self,url):
        state=self._url_state(url)
        with self.lock:self.state=state;self.pending_url=url
    def _open_pending(self):
        with self.lock:url=self.pending_url;self.pending_url=None
        if not url:return
        if self.service:
            self.service.stop();self.service=None;self.driver=None
        proc=Launcher.launch(self.browser,[*self.launch_args[:-1],url],self.environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.extra_processes.append(proc)
    def _emit(self,url,values=()):
        with self.lock:
            state=self.state
            if state in self.delivered:return False
            code=callback_code(url,state,values,self.callback)
            if not code:return False
            self.delivered.add(state)
        from .journal import register_secret
        register_secret(code)
        self.on_code(code,state);return True
    def _ready(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=.3)
        try:
            connection.request('GET','/json/version');reply=connection.getresponse();reply.read(65536);return reply.status==200
        except OSError:return False
        finally:connection.close()
    def _callback_available(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=.4)
        try:
            connection.request('GET','/json/list');reply=connection.getresponse();targets=json.loads(reply.read(1048576))
            with self.lock:state=self.state
            return any(item.get('type')=='page' and callback_state_matches(item.get('url',''),state,self.callback) for item in targets)
        except (OSError,ValueError,TypeError):return False
        finally:connection.close()
    def _attach(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        options=webdriver.ChromeOptions();options.debugger_address='127.0.0.1:'+str(self.port);options.page_load_strategy='none'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',DeprecationWarning);options.ignore_local_proxy_environment_variables()
        environment=external_environment()
        for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):environment.pop(key,None)
        environment['NO_PROXY']='localhost,127.0.0.1,::1'
        self.service=Service(executable_path=str(self.driver_path),log_output=subprocess.DEVNULL,service_args=['--allowed-ips=127.0.0.1','--log-level=OFF'],env=environment)
        self.driver=webdriver.Chrome(service=self.service,options=options)
        if getattr(self.driver.command_executor,'_client_config',None):self.driver.command_executor._client_config.timeout=3
    def _poll(self):
        for handle in self.driver.window_handles[:10]:
            if self.stop_event.is_set():return
            try:
                self.driver.switch_to.window(handle);url=self.driver.current_url
                if self._emit(url):continue
                with self.lock:state=self.state
                if callback_state_matches(url,state,self.callback):
                    values=[]
                    for element in self.driver.find_elements('css selector','#auth-code,#code-value,code,pre,input[readonly],textarea[readonly]')[:10]:
                        value=element.get_attribute('value') or element.text
                        if isinstance(value,str):values.append(value.strip())
                    self._emit(url,values)
            except Exception:continue
    def _run(self):
        try:
            deadline=time.monotonic()+20
            while not self.stop_event.is_set() and self.process.poll() is None:
                if self._ready():break
                if time.monotonic()>deadline:raise RuntimeError('Browser startup timeout')
                self.stop_event.wait(.2)
            if self.stop_event.is_set() or self.process.poll() is not None:return
            while not self.stop_event.is_set() and self.process.poll() is None:
                self._open_pending()
                if self.driver is None:
                    if not self._callback_available():self.stop_event.wait(.2);continue
                    self._attach()
                self._poll();self.stop_event.wait(.35)
        except Exception as exc:
            try:
                from .journal import record_error
                record_error('seleniumAuth',exc)
            except Exception:pass
            self.on_error('Selenium не смог получить код. Подробности доступны в журнале; код можно вставить в CLI вручную.')
        finally:
            if self.service:
                try:self.service.stop()
                except Exception:pass
            for process in self.extra_processes:
                if process.poll() is None:
                    try:process.terminate();process.wait(timeout=2)
                    except Exception:pass
    def close(self):
        self.stop_event.set()
        if self.thread is not threading.current_thread():self.thread.join(timeout=5)
        if self.thread.is_alive() and self.service and self.service.process:
            try:self.service.process.terminate()
            except OSError:pass
