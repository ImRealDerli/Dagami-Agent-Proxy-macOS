import os,re,subprocess


class SecurityToolKeychain:
    def __init__(self,account=None,path=None):
        self.account=account
        self.path=str(path) if path is not None else None

    def command(self,args,script=None):
        env=os.environ.copy();env['LC_ALL']='C'
        try:
            result=subprocess.run(['/usr/bin/security',*args],input=script,capture_output=True,timeout=120,env=env)
        except subprocess.TimeoutExpired:
            raise RuntimeError('Keychain: истекло время ожидания системного окна. Повторите действие и разрешите доступ.') from None
        except OSError:
            raise RuntimeError('Keychain: не удалось запустить системную утилиту security.') from None
        if result.returncode not in (0,44):
            reason=result.stderr.lower()
            if b'cancel' in reason:message='Запрос доступа отменён.'
            elif b'interaction' in reason:message='macOS не разрешила показать окно доступа. Откройте приложение в текущем сеансе пользователя.'
            elif b'authorization' in reason or b'authentication' in reason:message='macOS отклонила доступ. Разрешите его в системном окне или проверьте Связку ключей.'
            elif b'no such keychain' in reason or b'default keychain' in reason:message='Не найдена доступная Связка ключей пользователя.'
            else:message='Системное хранилище отклонило операцию.'
            raise RuntimeError('Keychain: '+message+' Код security: '+str(result.returncode)+'.')
        return result

    def arguments(self,action,service):
        args=[action,'-s',service]
        if self.account is not None:args+=['-a',self.account]
        return args

    def get(self,service):
        args=self.arguments('find-generic-password',service)+['-g']
        if self.path is not None:args.append(self.path)
        result=self.command(args)
        if result.returncode==44:return None
        field=result.stderr
        prefix=b'password: '
        if not field.startswith(prefix):raise RuntimeError('Keychain: системная утилита вернула неизвестный формат данных.')
        raw=field[len(prefix):]
        if raw.endswith(b'\n'):raw=raw[:-1]
        if not raw:return ''
        if raw.startswith(b'0x'):
            match=re.match(rb'0x([0-9A-Fa-f]+)(?:\s|$)',raw)
            if match is None:raise RuntimeError('Keychain: неверный формат сохранённых данных.')
            return self.decode(bytes.fromhex(match[1].decode('ascii')))
        if raw.startswith(b'"') and raw.endswith(b'"'):return self.decode(raw[1:-1])
        raise RuntimeError('Keychain: системная утилита вернула неизвестный формат пароля.')

    @staticmethod
    def decode(raw):
        try:return raw.decode('utf-8')
        except UnicodeError:raise RuntimeError('Keychain: сохранённые данные не являются текстовым ключом или паролем.') from None

    def set(self,service,account,value):
        args=['add-generic-password','-U','-s',service,'-a',self.account if self.account is not None else account,'-X',value.encode('utf-8').hex()]
        if self.path is not None:args.append(self.path)
        def quote(value):
            if '\n' in value or '\r' in value or '\0' in value:raise ValueError('Имя записи Keychain содержит недопустимые символы.')
            return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
        result=self.command(['-i'],(' '.join(map(quote,args))+'\n').encode('utf-8'))
        if result.returncode!=0:raise RuntimeError('Keychain: запись не сохранена.')
        if self.get(service)!=value:raise RuntimeError('Keychain: записанное значение не прошло проверку. Повторите сохранение.')

    def delete(self,service):
        args=self.arguments('delete-generic-password',service)
        if self.path is not None:args.append(self.path)
        return self.command(args).returncode in (0,44)
