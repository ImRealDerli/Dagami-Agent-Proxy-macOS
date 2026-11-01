import hmac,re
from urllib.parse import urlsplit,parse_qs
from .selenium_code import valid_code


class CliCodeGate:
    def __init__(self):self.state='';self.waiting=False;self.manual=False;self.pending=None;self.sent=set()
    def begin(self,url):
        states=parse_qs(urlsplit(url).query).get('state',[])
        if len(states)!=1:return
        if states[0]!=self.state:self.state=states[0];self.waiting=False;self.manual=False;self.pending=None
    def observe(self,text):
        text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text[-2048:])
        if re.search(r'(?im)(?:enter|paste)\s+(?:the\s+)?(?:authorization|authentication|auth)\s+code',text):self.waiting=True
    def user_input(self):
        if self.waiting:self.manual=True
    def offer(self,code,state):
        if not self.state or not hmac.compare_digest(self.state,state) or state in self.sent or not valid_code(code):return False
        self.pending=code;return True
    def take(self):
        if not self.waiting or self.manual or not self.pending or self.state in self.sent:return None
        code=self.pending;self.pending=None;self.sent.add(self.state);self.waiting=False;return code
