
import ctypes as c


class Keychain:
    def __init__(self, keychain=None, account=None):
        self.keychain = keychain
        self.account = account
        self.api = c.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.api.SecKeychainFindGenericPassword.argtypes = [c.c_void_p,c.c_uint32,c.c_char_p,c.c_uint32,c.c_char_p,c.POINTER(c.c_uint32),c.POINTER(c.c_void_p),c.POINTER(c.c_void_p)]
        self.api.SecKeychainAddGenericPassword.argtypes = [c.c_void_p,c.c_uint32,c.c_char_p,c.c_uint32,c.c_char_p,c.c_uint32,c.c_void_p,c.POINTER(c.c_void_p)]
        self.api.SecKeychainItemModifyAttributesAndData.argtypes = [c.c_void_p,c.c_void_p,c.c_uint32,c.c_void_p]
        self.api.SecKeychainItemFreeContent.argtypes = [c.c_void_p,c.c_void_p]
        self.api.SecKeychainItemDelete.argtypes = [c.c_void_p]
        self.cf = c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cf.CFRelease.argtypes = [c.c_void_p]

    def find(self, service):
        service = service.encode('utf-8'); length = c.c_uint32(); data = c.c_void_p(); item = c.c_void_p()
        account=self.account.encode('utf-8') if self.account is not None else None
        status = self.api.SecKeychainFindGenericPassword(self.keychain,len(service),service,len(account) if account is not None else 0,account,c.byref(length),c.byref(data),c.byref(item))
        if status == -25300:return None, None
        if status:raise RuntimeError('Keychain: код ошибки ' + str(status))
        try:return c.string_at(data,length.value).decode('utf-8'), item
        finally:self.api.SecKeychainItemFreeContent(None,data)

    def get(self, service):
        value, item = self.find(service)
        if item:self.cf.CFRelease(item)
        return value

    def set(self, service, account, value):
        _, item = self.find(service)
        data = value.encode('utf-8')
        try:
            if item:
                status = self.api.SecKeychainItemModifyAttributesAndData(item,None,len(data),data)
            else:
                service=service.encode('utf-8');account=(self.account if self.account is not None else account).encode('utf-8')
                status = self.api.SecKeychainAddGenericPassword(self.keychain,len(service),service,len(account),account,len(data),data,None)
            if status:raise RuntimeError('Keychain: код ошибки ' + str(status))
        finally:
            if item:self.cf.CFRelease(item)

    def delete(self, service):
        _, item = self.find(service)
        if not item:return True
        try:return self.api.SecKeychainItemDelete(item) == 0
        finally:self.cf.CFRelease(item)
