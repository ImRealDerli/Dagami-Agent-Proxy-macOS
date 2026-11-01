import hmac,re
from urllib.parse import urlsplit,parse_qs
from .selenium_code import valid_code


class CliCodeGate:
    def __init__(self):self.state='';self.waiting=False;self.manual=False;self.pending=None;self.sent=set();self.terminal_pending=b''
    def begin(self,url):
        states=parse_qs(urlsplit(url).query).get('state',[])
        if len(states)!=1:return
        if states[0]!=self.state:self.state=states[0];self.waiting=False;self.manual=False;self.pending=None
    def observe(self,text):
        text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text[-8192:])
        text=re.sub('[│┃║┆┊┇┋╎╏]',' ',text)
        if self.state not in self.sent and re.search(r'(?im)(?:enter|paste)\s+(?:the\s+)?(?:authorization|authentication|auth)\s+code',text):self.waiting=True
    def user_input(self,data=b'x'):
        data=self.terminal_pending+data;self.terminal_pending=b''
        while data:
            match=re.match(rb'\x1b\[(?:[IO]|[0-9;?=>]*[Rc]|[0-9;]*t)|\x1b\](?:10|11|12);[^\x07\x1b]*(?:\x07|\x1b\\)',data)
            if match:data=data[match.end():];continue
            if len(data)<256 and (re.fullmatch(rb'\x1b\[[0-9;?=>]*',data) or re.match(rb'^\x1b\](?:10|11|12);',data) and not re.search(rb'\x07|\x1b\\',data)):
                self.terminal_pending=data;return False
            if self.waiting:self.manual=True
            return True
        return False
    def offer(self,code,state):
        if not self.state or not hmac.compare_digest(self.state,state) or state in self.sent or not valid_code(code):return False
        self.pending=code;return True
    def take(self):
        if not self.waiting or self.manual or not self.pending or self.state in self.sent:return None
        code=self.pending;self.pending=None;self.sent.add(self.state);self.waiting=False;return code
