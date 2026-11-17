"""Validated public configuration, private atomic state and safe diagnostics."""
import fcntl,ipaddress,json,os,pathlib,re,secrets,stat,tempfile,time,urllib.parse
from importlib import resources

class PolarisError(RuntimeError):
    """An operator-safe error; never includes captured command/API bodies."""

PINS=json.loads(resources.files('polaris_node').joinpath('pins.json').read_text())
PROTECTED={'panel.followyourpolaris.space','sub.followyourpolaris.space','backup.followyourpolaris.space'}
DEFAULTS={'country':'XX','panel_url':'https://panel.followyourpolaris.space','public_ipv4':None,'public_ipv6':None,'management_address':None,'panel_ipv4':[],'panel_ipv6':[],'api_port':2222,'vpn_port':443,'http_port':80,'xray_port':8082,'tls_mode':'acme','email':None,'cert_path':None,'key_path':None,'acme_directory':PINS['acme_directory']}

def require(condition,message):
    if not condition:raise PolarisError(message)

def normalize_config(value):
    require(isinstance(value,dict),'Ожидался JSON-объект параметров')
    require(not set(value)-set(DEFAULTS)-{'name','domain'},'Неизвестные поля конфигурации; секреты в JSON запрещены')
    c={**DEFAULTS,**value}
    require(isinstance(c.get('name'),str)and re.fullmatch(r'[a-z][a-z0-9-]{2,15}',c['name'])is not None,'Имя:3–16 строчных букв, цифр, дефисов; первая буква')
    require(isinstance(c.get('domain'),str),'Домен должен быть строкой')
    domain=c['domain'].strip().lower().rstrip('.')
    require(len(domain)<=253 and '.'in domain and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label)for label in domain.split('.')),'Недопустимый домен')
    require(domain not in PROTECTED,'Существующие маршруты panel/sub/backup защищены')
    c['domain']=domain
    country=str(c['country']).upper();country={'FINLAND':'FI','GERMANY':'DE','NETHERLANDS':'NL','ФИНЛЯНДИЯ':'FI','ГЕРМАНИЯ':'DE','НИДЕРЛАНДЫ':'NL'}.get(country,country)
    require(re.fullmatch('[A-Z]{2}',country)is not None,'Страна:двухбуквенный ISO код (FI,DE,NL)');c['country']=country
    for k in ('panel_url','acme_directory'):
        u=urllib.parse.urlsplit(c[k]);require(u.scheme=='https'and bool(u.hostname)and not u.username and not u.password and not u.query and not u.fragment,'Разрешён только HTTPS без credentials/query/fragment')
        require(k!='panel_url'or u.path in ('','/'),'Panel URL должен содержать только origin')
        try:u.port
        except ValueError:raise PolarisError('Неверный HTTPS порт')from None
        c[k]=c[k].rstrip('/')
    ports=[]
    for k in ('api_port','vpn_port','http_port','xray_port'):
        p=c[k];require(isinstance(p,int)and not isinstance(p,bool)and 1<=p<=65535,'Неверный сетевой порт');require(p!=22,'SSH22 защищён');ports.append(p)
    require(len(set(ports))==4,'Порты API/VPN/HTTP/Xray должны различаться')
    for k,family in [('public_ipv4',4),('public_ipv6',6)]:
        if c[k]:
            try:a=ipaddress.ip_address(c[k])
            except ValueError:raise PolarisError('Неверный IP-адрес')from None
            require(a.version==family and not a.is_loopback and not a.is_multicast and not a.is_unspecified,'Неверный адрес сервера');c[k]=str(a)
    for k,family in [('panel_ipv4',4),('panel_ipv6',6)]:
        require(isinstance(c[k],list)and len(c[k])<=8,'Allowlist Panel должен быть коротким списком IP')
        normalized=[]
        for text in c[k]:
            try:a=ipaddress.ip_address(text)
            except ValueError:raise PolarisError('Allowlist принимает точный IP, не сеть')from None
            require(a.version==family and not a.is_loopback and not a.is_multicast and not a.is_unspecified,'Неверный IP Panel');normalized.append(str(a))
        c[k]=sorted(set(normalized))
    if c['management_address']:
        try:a=ipaddress.ip_address(c['management_address'])
        except ValueError:raise PolarisError('Management address должен быть IP')from None
        require(not a.is_loopback and not a.is_multicast and not a.is_unspecified,'Неверный management IP');c['management_address']=str(a)
    else:c['management_address']=c['public_ipv4']
    require(c['tls_mode']in ('acme','provided'),'TLS mode:acme или provided')
    if c['tls_mode']=='provided':require(all(isinstance(c[k],str)and pathlib.Path(c[k]).is_absolute()for k in ('cert_path','key_path')),'Нужны абсолютные пути нового сертификата и ключа')
    if c['email'] is not None:require(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',c['email'])is not None,'Неверный email ACME')
    return c

def retry_config(existing,candidate):
    changed={k for k in set(existing)|set(candidate)if existing.get(k)!=candidate.get(k)}
    require(changed<={'panel_ipv4','panel_ipv6'},'При retry можно исправить только sourceIP allowlist Panel; имя/домен/порты/management IP неизменяемы')
    return candidate

def redact(text,known=()):
    for secret in sorted((x for x in known if x),key=len,reverse=True):text=text.replace(secret,'[REDACTED]')
    text=re.sub(r'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)','[PRIVATE KEY REDACTED]',text,flags=re.S)
    text=re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+','[JWT REDACTED]',text)
    text=re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+',r'\1[REDACTED]',text)
    return text

def assert_public_state(x):
    if isinstance(x,dict):
        for k,v in x.items():
            require(str(k).lower()not in ('token','api_token','password','admin_password','authorization','secret_key','node_secret','nodekeypem','private_key'),'API credentials/private keys нельзя сохранять в state')
            assert_public_state(v)
    elif isinstance(x,list):
        for v in x:assert_public_state(v)
    elif isinstance(x,str):require('PRIVATE KEY-----'not in x and re.search(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',x)is None,'Secret value в state запрещён')

def managed_path(path):
    p=pathlib.Path(path).absolute()
    require('..'not in p.parts,'Переход к родительскому каталогу запрещён')
    for parent in reversed(p.parents):
        require(not parent.is_symlink(),'Ссылка в родительском каталоге управляемого пути')
        if parent.exists():
            mode=parent.stat().st_mode
            require(stat.S_ISDIR(mode)and (not mode&0o022 or (parent==pathlib.Path('/tmp')and mode&stat.S_ISVTX)),'Небезопасный родительский каталог')
    return p

def owned_file(path,private=True):
    managed_path(path)
    p=pathlib.Path(path);require(not p.is_symlink(),'Символьная ссылка вместо собственного файла')
    if p.exists():
        s=p.stat();require(stat.S_ISREG(s.st_mode)and s.st_uid==os.geteuid()and not s.st_mode&0o022,'Чужой или небезопасный файл')
        if private:require(not s.st_mode&0o077,'Приватный файл должен иметь 0600')
    return p

def atomic_write(path,data,mode=0o600):
    p=owned_file(path,private=False);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix='.'+p.name+'-',dir=p.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb')as f:f.write(data if isinstance(data,bytes)else data.encode());f.flush();os.fsync(f.fileno())
        os.replace(name,p)
        directory=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)

class StateStore:
    def __init__(self,path='/var/lib/polaris-node'):
        managed_path(path)
        self.path=pathlib.Path(path);self.fd=None;self.data={}
        require(not self.path.is_symlink(),'Ссылка вместо state-каталога')
        if self.path.exists():
            s=self.path.stat();require(s.st_uid==os.geteuid()and stat.S_ISDIR(s.st_mode)and not s.st_mode&0o077,'State-каталог должен быть собственным 0700')
        else:self.path.mkdir(mode=0o700,parents=True)
        lock=self.path/'lock';require(not lock.is_symlink(),'Небезопасный lock')
        self.fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:self.close();raise PolarisError('Уже выполняется другая операция Polaris')from None
        state=owned_file(self.path/'state.json')
        if state.exists():
            try:self.data=json.loads(state.read_text())
            except ValueError:self.close();raise PolarisError('Повреждён state; восстановите собственную резервную копию')from None
            require(self.data.get('schema')==1 and re.fullmatch('[a-f0-9]{32}',self.data.get('install_id',''))is not None,'Чужой или неподдерживаемый state')
            if self.data.get('config',{}).get('domain'):require(normalize_config(self.data['config'])==self.data['config'],'Повреждены параметры сохранённого state')
    def create(self,config):
        require(not self.data,'Установка уже существует')
        self.data={'schema':1,'install_id':secrets.token_hex(16),'installer_version':PINS['installer'],'config':config,'resources':{},'stages':{},'published':False,'created_at':int(time.time())}
        self.save()
    def save(self):
        assert_public_state(self.data);atomic_write(self.path/'state.json',json.dumps(self.data,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    def checkpoint(self,stage,value=True):self.data['stages'][stage]=value;self.save()
    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
