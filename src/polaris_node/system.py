"""Only explicitly owned host resources are changed. No global firewall restore."""
import base64,datetime,hashlib,ipaddress,json,os,pathlib,platform,re,shlex,shutil,ssl,stat,subprocess,tarfile,tempfile,time,urllib.request
from .core import PINS,PolarisError,require,atomic_write,owned_file,redact,managed_path
from . import render
ROOT=pathlib.Path('/opt/polaris-node')
CLI=pathlib.Path('/usr/local/bin/polaris-node')
UNIT_DIR=pathlib.Path('/etc/systemd/system')
D=['docker','--host','unix:///var/run/docker.sock']

def failure_category(text):
    text=text.lower()
    for category,words in [('DNS',('temporary failure resolving','name or service not known')),('TLS_VERIFY',('certificate verify','certificate verification','certificate is not trusted')),('PORT_CONFLICT',('address already in use','port is already allocated')),('DISK_FULL',('no space left','not enough free space')),('APT_BUSY',('could not get lock','unable to acquire')),('APT_SIGNATURE',('no_pubkey','signatures couldn')),('VERSION_UNAVAILABLE',('version','was not found','no installation candidate')),('REGISTRY_RATE_LIMIT',('toomanyrequests','rate limit')),('DOCKER_UNAVAILABLE',('cannot connect to the docker','is the docker daemon running')),('NETWORK',('connection refused','network is unreachable','could not resolve'))]:
        if any(word in text for word in words):return category
    return 'COMMAND_FAILED'

class Runner:
    def call(self,args,data=None,timeout=180):
        if pathlib.Path(args[0]).name=='apt-get':args=[args[0],'-o','Acquire::Languages=none','-o','Acquire::Retries=2','-o','Acquire::http::Timeout=20','-o','Acquire::https::Timeout=20',*args[1:]]
        env=dict(os.environ,LC_ALL='C',DEBIAN_FRONTEND='noninteractive',NEEDRESTART_MODE='l')
        try:return subprocess.run(args,input=data.encode()if isinstance(data,str)else data,capture_output=True,timeout=timeout,env=env)
        except (OSError,subprocess.TimeoutExpired):raise PolarisError('Не выполнена команда '+pathlib.Path(args[0]).name+' (недоступна/timeout); секретный вывод скрыт')from None
    def run(self,args,data=None,timeout=180):
        r=self.call(args,data,timeout)
        require(r.returncode==0,'Ошибка '+pathlib.Path(args[0]).name+' ['+failure_category((r.stdout+r.stderr).decode(errors='replace'))+'], код '+str(r.returncode)+'; исходный вывод скрыт для защиты секретов')
        return r.stdout.decode(errors='replace').strip()

def validate_os(data,arch):
    require(data.get('ID')=='ubuntu'and data.get('VERSION_ID')in PINS['ubuntu'],'Поддерживается Ubuntu22.04/24.04 LTS')
    require(arch in PINS['architectures'],'Этот релиз проверен только на amd64/x86_64')
    return data['VERSION_ID']
def check_resources(memory_mib,cpus,free_bytes):
    require(memory_mib>=900,'Нужно не менее 1 ГБ RAM (MemTotal>=900MiB)');require(cpus>=1,'Нужен CPU');require(free_bytes>=4*1024**3,'Нужно 4 ГБ свободного места')
def parse_listeners(text):
    result=[]
    for line in text.splitlines():
        f=line.split()
        if len(f)<5:continue
        local=f[4]if f[0]=='tcp'else f[3]if f[0]=='LISTEN'else''
        port=local.rpartition(':')[2]
        if port.isdigit():result.append((int(port),{int(x)for x in re.findall(r'pid=(\d+)',line)}))
    return result

def firewall_commands(c,identity):
    ports=','.join(str(c[k])for k in ('api_port','xray_port','http_port','vpn_port'))
    suffix=['-p','tcp','-m','multiport','--dports',ports,'-m','comment','--comment','pni:'+identity,'-j',render.chain_name(identity)]
    return [[binary,'-w','10','-C','INPUT',*suffix]for binary in ('iptables','ip6tables')]

def rules_match(expected,actual):
    def canonical(text):
        result=[]
        for line in text.splitlines():
            if not line.startswith('-A '):continue
            tokens=shlex.split(line);normalized=[];i=0
            while i<len(tokens):
                if tokens[i:i+2]==['-m','tcp']:i+=2;continue
                if tokens[i]=='--dports'and i+1<len(tokens):normalized.extend(['--dports',','.join(sorted(tokens[i+1].split(','),key=int))]);i+=2;continue
                normalized.append(tokens[i]);i+=1
            result.append(normalized)
        return result
    return canonical(expected)==canonical(actual)

def first_hook_matches(text,command):
    rules=[line for line in text.splitlines()if line.startswith('-A INPUT ')]
    return bool(rules)and rules_match('-A INPUT '+shlex.join(command[5:]),rules[0])

def validate_compose_plan(text):
    changes=[line.split()[1].split(':')[0]for line in text.splitlines()if line.startswith('Inst ')]
    require(not any(line.startswith('Remv ')for line in text.splitlines())and all(name=='docker-compose-plugin'for name in changes),'APT план затрагивает engine/runtime или другие пакеты; остановка')

def supported_compose(value):
    try:
        parts=value.strip().lstrip('v').split('.')
        return parts[0]=='2'and tuple(map(int,parts[:2]))>=(2,40)
    except (ValueError,IndexError):return False

def validate_docker_key(details):
    lines=details.splitlines();fingerprints=[line.split(':')[9]for line in lines if line.startswith('fpr:')]
    require(sum(line.startswith('pub:')for line in lines)==1 and fingerprints and fingerprints[0]==PINS['docker_gpg_fingerprint'],'Неверный GPG ключ или лишний primary key Docker')

class System:
    def __init__(self,store,runner=None):self.store=store;self.state=store.data;self.c=self.state.get('config',{});self.identity=self.state.get('install_id','');self.r=runner or Runner()
    @staticmethod
    def basic(strict=True):
        require(os.geteuid()==0,'Запустите через sudo или root nativeconsole')
        data={}
        for line in pathlib.Path('/etc/os-release').read_text().splitlines():
            if '='in line:k,v=line.split('=',1);data[k]=v.strip('"')
        version=validate_os(data,platform.machine());memory=next(int(x.split()[1])for x in pathlib.Path('/proc/meminfo').read_text().splitlines()if x.startswith('MemTotal:'))//1024
        if strict:
            check_resources(memory,os.cpu_count()or 0,shutil.disk_usage('/').free)
            available=next(int(x.split()[1])for x in pathlib.Path('/proc/meminfo').read_text().splitlines()if x.startswith('MemAvailable:'))//1024
            require(available>=400,'Нужно не менее 400MiB доступной памяти; чужие процессы не останавливаются')
        require(pathlib.Path('/run/systemd/system').exists(),'Нужна UbuntuServer с systemd; контейнер без init не поддерживается')
        return {'ubuntu':version,'architecture':platform.machine(),'memory_mib':memory,'cpus':os.cpu_count()}
    def own_dir(self,path,mode=0o700):
        managed_path(path)
        p=pathlib.Path(path);require(not p.is_symlink(),'Ссылка вместо собственного каталога')
        if p.exists():require(p.is_dir()and p.stat().st_uid==os.geteuid()and not p.stat().st_mode&0o022,'Чужой или небезопасный каталог')
        else:p.mkdir(parents=True,mode=mode)
        p.chmod(mode);return p
    def prepare_dirs(self):
        if ROOT.exists()and not (ROOT/'installation-id').exists():require(not list(ROOT.iterdir()),'Каталог/opt/polaris-node занят чужими данными')
        self.own_dir(ROOT)
        marker=ROOT/'installation-id'
        if marker.exists():require(owned_file(marker).read_text().strip()==self.identity,'Чужая установка в/opt/polaris-node')
        else:atomic_write(marker,self.identity+'\n')
        for name in ('nginx','tls/live','tls/archive','certbot/conf','certbot/work','certbot/logs'):self.own_dir(ROOT/name)
        self.own_dir(self.store.path/'acme',0o755);self.own_dir(self.store.path/'backups')
    def owned_pids(self):
        if not shutil.which('docker'):return set()
        r=self.r.call(D+['ps','-q','--filter','label=io.polaris.install='+self.identity],timeout=30)
        if r.returncode:return set()
        result=set()
        for cid in r.stdout.decode().splitlines():
            out=self.r.run(D+['top',cid,'-eo','pid'],timeout=20)
            result|={int(x.strip())for x in out.splitlines()if x.strip().isdigit()}
        return result
    def check_ports(self):
        targets={self.c[k]for k in ('api_port','xray_port','vpn_port','http_port')};owned=self.owned_pids()
        for port,pids in parse_listeners(self.r.run(['ss','-H','-lntp'],timeout=20)):
            if port in targets:require(bool(pids)and pids<=owned,'Конфликт TCP порта '+str(port)+'; чужой процесс не изменён')
        ssh=self.r.run(['ss','-H','-lntp'],timeout=20)
        for line in ssh.splitlines():
            if '"sshd"'in line:
                for port,_ in parse_listeners(line):require(port not in targets,'Выбранныйпорт используется SSH')
    def dependencies(self):
        need=[package for command,package in [('curl','curl'),('openssl','openssl'),('gpg','gnupg'),('ss','iproute2'),('iptables','iptables'),('ip6tables','iptables'),('dig','dnsutils')]if not shutil.which(command)]
        if need:
            self.r.run(['apt-get','update'],timeout=300);self.r.run(['apt-get','install','-y','--no-install-recommends',*sorted(set(need))],timeout=420)
    def docker(self):
        if 'docker_preexisting'not in self.state:
            self.state['docker_preexisting']=bool(shutil.which('docker'));self.store.save()
        owned_partial=not self.state['docker_preexisting']and self.state['stages'].get('docker_install_intent')
        if shutil.which('docker'):
            if owned_partial:self.r.run(['systemctl','enable','--now','docker'],timeout=90)
            require(self.r.call(['systemctl','is-active','--quiet','docker']).returncode==0,'Существующий Docker не запущен; автоматический старт чужихконтейнеров запрещён')
        else:
            for service in ('containerd','cri-o','kubelet'):
                require((service=='containerd'and owned_partial)or self.r.call(['systemctl','is-active','--quiet',service]).returncode!=0,'Обнаружен другойконтейнерный runtime; остановка')
            require(self.r.call(['dpkg-query','-W','-f=${Status}','containerd']).returncode!=0,'Ubuntucontainerd ужеустановлен; нельзя заменять чужой runtime')
            if not owned_partial:
                forwarding=self.r.run(['sysctl','-n','net.ipv4.ip_forward'],timeout=20)
                nat=self.r.run(['iptables','-w','10','-t','nat','-S'],timeout=20)
                require(forwarding=='0'and not any(x.startswith('-A ')for x in nat.splitlines()),'До Docker обнаружен действующий routing/NAT; автоматическаяустановка может затронутьдругой VPN, остановка')
            self.r.run(['apt-get','update'],timeout=300)
            key=self.r.run(['curl','--fail','--silent','--show-error','--location','--proto','=https','--tlsv1.2','https://download.docker.com/linux/ubuntu/gpg'],timeout=60)
            with tempfile.TemporaryDirectory(prefix='pni-gpg-')as temp:
                p=pathlib.Path(temp)/'docker.asc';p.write_text(key)
                details=self.r.run(['gpg','--batch','--homedir',temp,'--with-colons','--show-keys',str(p)],timeout=30)
                validate_docker_key(details)
            keypath=pathlib.Path('/usr/share/keyrings/polaris-docker.asc');source=pathlib.Path('/etc/apt/sources.list.d/polaris-docker.sources')
            version=self.basic()['ubuntu'];suite={'22.04':'jammy','24.04':'noble'}[version]
            text=f'# Owned by Polaris Node Installer {self.identity}\nTypes: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: {suite}\nComponents: stable\nArchitectures: amd64\nSigned-By: {keypath}\n'
            if keypath.exists()or source.exists():
                require(keypath.exists()and source.exists()and owned_file(keypath,False).read_text()==key and owned_file(source,False).read_text()==text,'Неизвестные APT файлы Polaris; не перезаписываем')
            else:atomic_write(keypath,key,0o644);atomic_write(source,text,0o644)
            self.store.checkpoint('docker_repository')
            self.r.run(['apt-get','update'],timeout=300)
            suffix='-1~ubuntu.'+version+'~'+suite
            packages=['docker-ce=5:'+PINS['docker_version']+suffix,'docker-ce-cli=5:'+PINS['docker_version']+suffix,'containerd.io=2.2.6'+suffix,'docker-compose-plugin='+PINS['compose_version']+suffix]
            self.store.checkpoint('docker_install_intent')
            self.r.run(['apt-get','install','-y','--no-install-recommends',*packages],timeout=600)
            self.r.run(['systemctl','enable','--now','docker'],timeout=90)
        info=json.loads(self.r.run(D+['info','--format','{{json .}}'],timeout=30));require(int(info['ServerVersion'].split('.')[0])in PINS['docker_major'],'Непроверенная major версия Docker; не обновляемавтоматически')
        require(not any('rootless'in x for x in info.get('SecurityOptions',[])),'Нужен rootfulDocker в UbuntuVPS; rootlesshostnetwork непредоставляет INPUT изоляцию')
        probe=self.r.call(D+['compose','version','--short'],timeout=20)
        if probe.returncode or not supported_compose(probe.stdout.decode()):self.install_compose_plugin()
        compose=self.r.run(D+['compose','version','--short'],timeout=20).lstrip('v');require(supported_compose(compose),'Нужен Docker Compose plugin>=2.40; engine не обновляется')
        self.state['docker_version']=info['ServerVersion'];self.state['compose_version']=compose;self.store.checkpoint('docker')
    def install_compose_plugin(self):
        """A separate official APT transaction cannot upgrade any foreign package."""
        version=self.basic()['ubuntu'];suite={'22.04':'jammy','24.04':'noble'}[version]
        key=self.r.run(['curl','--fail','--silent','--show-error','--location','--proto','=https','--tlsv1.2','https://download.docker.com/linux/ubuntu/gpg'],timeout=60)
        with tempfile.TemporaryDirectory(prefix='pni-compose-')as temp:
            folder=pathlib.Path(temp);folder.chmod(0o755)
            keypath=folder/'docker.asc';atomic_write(keypath,key,0o644)
            details=self.r.run(['gpg','--batch','--homedir',temp,'--with-colons','--show-keys',str(keypath)],timeout=30)
            validate_docker_key(details)
            source=folder/'official.sources';atomic_write(source,f'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: {suite}\nComponents: stable\nArchitectures: amd64\nSigned-By: {keypath}\n',0o644)
            package=PINS['compose_version']+'-1~ubuntu.'+version+'~'+suite
            prefs=folder/'preferences';atomic_write(prefs,'Package: docker-compose-plugin\nPin: version '+package+'\nPin-Priority: 1001\n\nPackage: *\nPin: version *\nPin-Priority: -1\n',0o644)
            options=['-o','Dir::Etc::sourcelist='+str(source),'-o','Dir::Etc::sourceparts=-','-o','Dir::Etc::preferences='+str(prefs),'-o','Dir::Etc::preferencesparts=-']
            self.r.run(['apt-get',*options,'update'],timeout=300)
            install=['apt-get',*options,'install','--no-remove','--no-install-recommends','docker-compose-plugin='+package]
            validate_compose_plan(self.r.run([*install[:1],'-s',*install[1:]],timeout=60))
            self.r.run([*install[:1],'-y',*install[1:]],timeout=300)
        self.store.checkpoint('compose_plugin')
    def compose(self,*args,timeout=180):return self.r.run(D+['compose','--project-name','polaris-'+self.identity[:12],'-f',str(ROOT/'compose.json'),*args],timeout=timeout)
    def pull(self):
        for name,image in PINS['images'].items():
            if name=='certbot'and self.c['tls_mode']!='acme':continue
            require('@sha256:'in image,'Незакреплённыйобраз');self.r.run(D+['pull',image],timeout=600)
        self.store.checkpoint('images')
    def firewall(self):
        for binary,family in [('iptables',4),('ip6tables',6)]:
            self.r.run([binary,'-w','10','-S','INPUT'],timeout=20)
            data=render.firewall_rules(self.c,self.identity,family)
            for test in (True,False):self.r.run([binary+'-restore','-w','10',*(['--test']if test else[]),'--noflush'],data,30)
        for command in firewall_commands(self.c,self.identity):
            rules=self.r.run([command[0],'-w','10','-S','INPUT'],timeout=20)
            lines=[line for line in rules.splitlines()if line.startswith('-A INPUT ')]
            count=sum(rules_match('-A INPUT '+shlex.join(command[5:]),line)for line in lines)
            require(count<=32,'Слишком много собственных firewall hooks; остановка')
            if not first_hook_matches(rules,command)or count!=1:
                # Exact-rule deletions and insertion commit together under the
                # xtables lock. Never delete by a mutable foreign rule index.
                suffix=shlex.join(command[5:]);transaction='*filter\n'+('-D INPUT '+suffix+'\n')*count+'-I INPUT 1 '+suffix+'\nCOMMIT\n'
                self.r.run([command[0]+'-restore','-w','10','--noflush'],transaction,30)
        self.store.checkpoint('firewall')
    def remove_firewall(self):
        for command in firewall_commands(self.c,self.identity):
            if not shutil.which(command[0]):
                require(not self.state['stages'].get('firewall'),'Firewall utility отсутствует; правила нельзя безопасно снять');continue
            if self.r.call([command[0],'-w','10','-S',render.chain_name(self.identity)],timeout=20).returncode:continue
            for _ in range(4):
                if self.r.call(command,timeout=20).returncode:break
                self.r.run([*command[:3],'-D','INPUT',*command[5:]],timeout=20)
            else:raise PolarisError('Лишниекопии собственногоправила; остановка')
            self.r.run([command[0],'-w','10','-F',render.chain_name(self.identity)],timeout=20)
            self.r.run([command[0],'-w','10','-X',render.chain_name(self.identity)],timeout=20)
    def node_identity(self,api):
        p=ROOT/'node.env'
        if p.exists():
            text=owned_file(p).read_text();require('NODE_PORT='+str(self.c['api_port'])+'\n'in text and 'SNI_VERIFICATION=true\n'in text,'Node identity не соответствует state');return
        self.state['stages']['node_identity_intent']=True;self.store.save()
        response=api.request('GET','/keygen');secret=response.get('secretKey','')
        try:
            require(isinstance(secret,str)and len(secret)<65536,'Некорректный nativeNodepayload');decoded=json.loads(base64.b64decode(secret,validate=True));require(set(decoded)=={'nodeCertPem','nodeKeyPem','caCertPem','jwtPublicKey'},'Неверный состав nativeNodepayload')
        except (ValueError,TypeError):raise PolarisError('Некорректный nativeNodepayload')from None
        atomic_write(p,'NODE_PORT='+str(self.c['api_port'])+'\nSNI_VERIFICATION=true\nSECRET_KEY='+secret+'\n');self.store.checkpoint('node_identity')
    def write_configs(self,tls):
        atomic_write(ROOT/'nginx/nginx.conf',render.nginx_config(self.c,self.identity,tls))
        atomic_write(ROOT/'compose.json',json.dumps(render.compose_config(self.c,self.identity,tls),indent=2)+'\n')
        self.compose('config','-q',timeout=30)
    def install_cli(self,source):
        p=pathlib.Path(source);require(p.is_file()and not p.is_symlink(),'Нетпроверенногоисходного installer')
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if CLI.exists():require(hashlib.sha256(owned_file(CLI,False).read_bytes()).hexdigest()in (digest,self.state.get('cli_sha256'),self.state.get('cli_pending_sha256')),'Файл polaris-node изменён или занятдругойпрограммой')
        self.state['cli_pending_sha256']=digest;self.store.save()
        atomic_write(CLI,p.read_bytes(),0o755);self.state['cli_sha256']=digest;self.state.pop('cli_pending_sha256',None);self.store.checkpoint('cli')
    def install_units(self):
        for name,text in render.units(self.c,self.identity).items():
            p=UNIT_DIR/name
            if p.exists():require('# Owned by Polaris Node Installer '+self.identity in p.read_text(),'Существующаячужая systemd служба')
            atomic_write(p,text,0o644)
        self.r.run(['systemctl','daemon-reload'],timeout=30)
        self.r.run(['systemd-analyze','verify','polaris-node-firewall.service','polaris-node.service','polaris-node-renew.service','polaris-node-renew.timer'],timeout=30)
        self.r.run(['systemctl','enable','polaris-node-firewall.service','polaris-node.service'],timeout=30)
        # Renewal timer is enabled only after successful TLS provisioning.
        self.store.checkpoint('units')
    def dns(self,interactive=False):
        def matches():
            import socket
            try:addresses={x[4][0]for x in socket.getaddrinfo(self.c['domain'],self.c['vpn_port'],type=socket.SOCK_STREAM)}
            except OSError:return False
            expected={x for x in (self.c['public_ipv4'],self.c['public_ipv6'])if x}
            return bool(addresses)and addresses<=expected and expected<=addresses
        if not matches()and interactive:
            print('Создайтезапись A: '+self.c['domain']+' → '+str(self.c['public_ipv4']))
            if self.c['public_ipv6']:print('AAAA: '+self.c['domain']+' → '+self.c['public_ipv6'])
            input('Нажмите Enter после создания DNS: ')
        require(matches(),'DNS A/AAAA не совпадаетсадресом VPS; существующиезаписи не изменены')
        ns=[];labels=self.c['domain'].split('.')
        for i in range(min(len(labels)-1,8)):
            out=self.r.call(['dig','+short','NS','.'.join(labels[i:])],timeout=15)
            if out.returncode==0 and out.stdout.strip():ns=out.stdout.decode().splitlines();break
        self.state['dns_nameservers']=ns;self.store.checkpoint('dns')
    def provided_tls(self):
        cert=owned_file(self.c['cert_path'],private=False);key=owned_file(self.c['key_path']);require(cert.exists()and key.exists(),'Сертификат/ключ не найдены')
        self.r.run(['openssl','x509','-in',str(cert),'-noout','-checkend','86400','-checkhost',self.c['domain']],timeout=20)
        self.r.run(['openssl','verify','-purpose','sslserver','-verify_hostname',self.c['domain'],'-untrusted',str(cert),str(cert)],timeout=20)
        public=self.r.run(['openssl','x509','-in',str(cert),'-pubkey','-noout'],timeout=20)
        a=self.r.call(['openssl','pkey','-pubin','-outform','DER'],public,20)
        b=self.r.call(['openssl','pkey','-in',str(key),'-pubout','-outform','DER'],timeout=20)
        require(a.returncode==b.returncode==0 and a.stdout==b.stdout,'Ключнесоответствуетсертификату')
        self.deploy_tls(cert.read_bytes(),key.read_bytes())
    def validate_tls_pair(self,cert,key):
        self.r.run(['openssl','x509','-in',str(cert),'-noout','-checkend','86400','-checkhost',self.c['domain']],timeout=20)
        self.r.run(['openssl','verify','-purpose','sslserver','-verify_hostname',self.c['domain'],'-untrusted',str(cert),str(cert)],timeout=20)
        public=self.r.run(['openssl','x509','-in',str(cert),'-pubkey','-noout'],timeout=20)
        a=self.r.call(['openssl','pkey','-pubin','-outform','DER'],public,20);b=self.r.call(['openssl','pkey','-in',str(key),'-pubout','-outform','DER'],timeout=20)
        require(a.returncode==b.returncode==0 and a.stdout==b.stdout,'TLS ключ не соответствует сертификату')
    def reload_gateway(self):
        name='polaris-gateway-'+self.identity[:12]
        running=self.r.call(D+['inspect','-f','{{.State.Running}}',name],timeout=20)
        if running.returncode==0 and running.stdout.strip()==b'true':
            self.r.run(D+['exec',name,'nginx','-c','/etc/polaris/nginx.conf','-t'],timeout=20)
            self.r.run(D+['exec',name,'nginx','-c','/etc/polaris/nginx.conf','-s','reload'],timeout=20)
    def deploy_tls(self,cert,key):
        """Stage both files, exchange directories atomically, retain the old pair."""
        import ctypes
        live=self.own_dir(ROOT/'tls/live');archive=self.own_dir(ROOT/'tls/archive')
        current_cert=owned_file(live/'fullchain.pem');current_key=owned_file(live/'privkey.pem')
        if current_cert.exists()and current_key.exists()and current_cert.read_bytes()==cert and current_key.read_bytes()==key:
            self.store.checkpoint('tls');return
        stage=pathlib.Path(tempfile.mkdtemp(prefix='generation-',dir=archive));stage.chmod(0o700)
        atomic_write(stage/'fullchain.pem',cert);atomic_write(stage/'privkey.pem',key);self.validate_tls_pair(stage/'fullchain.pem',stage/'privkey.pem')
        libc=ctypes.CDLL(None,use_errno=True)
        require(hasattr(libc,'renameat2'),'Нужен Linux renameat2 для атомарного TLS')
        libc.renameat2.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];libc.renameat2.restype=ctypes.c_int
        def exchange():
            result=libc.renameat2(-100,os.fsencode(live),-100,os.fsencode(stage),2)
            require(result==0,'Не выполнено атомарное переключение TLS; прежняя пара сохранена')
            for folder in (live.parent,archive):
                fd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(fd)
                finally:os.close(fd)
        exchange()
        try:self.reload_gateway()
        except (PolarisError,OSError):
            exchange()
            try:self.reload_gateway()
            except (PolarisError,OSError):pass
            raise
        self.store.checkpoint('tls')
    def acme(self,renew=False):
        cmd=D+['run','--rm','--network','host','--read-only','--tmpfs','/tmp:rw,nosuid,size=64m','--cap-drop','ALL','--security-opt','no-new-privileges:true']
        for src,dst in [(ROOT/'certbot/conf','/etc/letsencrypt'),(ROOT/'certbot/work','/var/lib/letsencrypt'),(ROOT/'certbot/logs','/var/log/letsencrypt'),(self.store.path/'acme','/var/www/acme')]:cmd+=['--mount','type=bind,src='+str(src)+',dst='+dst]
        cmd+=['--mount','type=bind,src=/etc/ssl/certs/ca-certificates.crt,dst=/run/host-ca.pem,readonly','-e','REQUESTS_CA_BUNDLE=/run/host-ca.pem',PINS['images']['certbot']]
        if renew:cmd+=['renew','--cert-name','polaris-node','--non-interactive','--no-random-sleep-on-renew']
        else:
            cmd+=['certonly','--webroot','-w','/var/www/acme','--server',self.c['acme_directory'],'--cert-name','polaris-node','-d',self.c['domain'],'--agree-tos','--non-interactive','--keep-until-expiring']
            cmd+=['--email',self.c['email']]if self.c['email']else['--register-unsafely-without-email']
        self.r.run(cmd,timeout=300)
        live=ROOT/'certbot/conf/live/polaris-node'
        require((live/'fullchain.pem').is_file()and(live/'privkey.pem').is_file(),'ACME невыдалсертификат')
        self.r.run(['openssl','x509','-in',str(live/'fullchain.pem'),'-noout','-checkend','86400','-checkhost',self.c['domain']],timeout=20)
        self.r.run(['openssl','verify','-purpose','sslserver','-verify_hostname',self.c['domain'],'-untrusted',str(live/'fullchain.pem'),str(live/'fullchain.pem')],timeout=20)
        self.deploy_tls((live/'fullchain.pem').read_bytes(),(live/'privkey.pem').read_bytes())
    def start(self):
        self.firewall();self.compose('up','-d','--wait',timeout=180);self.store.checkpoint('containers')
    def stop(self):
        if not shutil.which('docker'):
            require(not self.state['stages'].get('containers'),'Docker отсутствует; нельзя подтвердить остановку контейнеров');return
        if(ROOT/'compose.json').exists():self.compose('stop',timeout=60)
        require(not self.r.run(D+['ps','-q','--filter','label=io.polaris.install='+self.identity],timeout=20),'Собственныеконтейнеры еще работают; firewall сохранён')
    def check_xray(self):
        node='polaris-node-'+self.identity[:12]
        version=self.r.run(D+['exec',node,'xray','version'],timeout=20)
        require(PINS['xray_version']in version,'Фактический Xray не совместимсзакреплённойверсией')
        self.r.run(D+['exec','-i',node,'xray','run','-test','-config','stdin:'],json.dumps(render.xray_config(self.c,self.identity)),30)
        # Native Node's Xray process receives dynamically computed users/profile.
        pids=self.r.run(D+['top',node,'-eo','pid,comm'],timeout=20)
        require(any(x.split()and x.split()[-1]in ('xray','rw-core')for x in pids.splitlines()),'Xray не запущен; факт runningNode недостаточен')
        self.store.checkpoint('xray')
    def doctor(self):
        result={'node':self.c.get('name'),'resources':{k:self.state.get('resources',{}).get(k)for k in ('node_id','profile_id','inbound_id','host_id')},'domain':self.c.get('domain'),'panel_live':'UNKNOWN:use --online with a fresh scoped token','api_external_isolation':'UNKNOWN:independent source probe required','local_firewall':{},'containers':{},'tls':'UNKNOWN','dns':'UNKNOWN'}
        for command,family in zip(firewall_commands(self.c,self.identity),(4,6)):
            if not shutil.which(command[0]):result['local_firewall'][command[0]]=False;continue
            contents=self.r.call([command[0],'-w','10','-S',render.chain_name(self.identity)],timeout=20)
            input_rules=self.r.call([command[0],'-w','10','-S','INPUT'],timeout=20)
            result['local_firewall'][command[0]]=contents.returncode==0 and input_rules.returncode==0 and first_hook_matches(input_rules.stdout.decode(),command)and self.r.call(command,timeout=20).returncode==0 and rules_match(render.firewall_rules(self.c,self.identity,family),contents.stdout.decode())
        raw=self.r.call(D+['ps','-a','--filter','label=io.polaris.install='+self.identity,'--format','{{.Names}}\t{{.State}}'],timeout=20)if shutil.which('docker')else subprocess.CompletedProcess(D,1,b'',b'')
        if raw.returncode==0:
            for line in raw.stdout.decode().splitlines():name,_,status=line.partition('\t');result['containers'][name]=status
        cert=ROOT/'tls/live/fullchain.pem'
        if cert.exists():result['tls']='PASS'if self.r.call(['openssl','x509','-in',str(cert),'-noout','-checkend','86400','-checkhost',self.c['domain']],timeout=20).returncode==0 else'FAIL'
        try:self.dns();result['dns']='PASS'
        except PolarisError:result['dns']='FAIL'
        if cert.exists():
            chain=self.r.call(['openssl','verify','-purpose','sslserver','-verify_hostname',self.c['domain'],'-untrusted',str(cert),str(cert)],timeout=20)
            if chain.returncode:result['tls']='FAIL'
        result['https_local']='FAIL'
        try:
            context=ssl.create_default_context()
            import socket
            with socket.create_connection(('127.0.0.1',self.c['vpn_port']),timeout=5)as raw:
                with context.wrap_socket(raw,server_hostname=self.c['domain'])as connection:
                    connection.sendall(('GET / HTTP/1.1\r\nHost: '+self.c['domain']+'\r\nConnection: close\r\n\r\n').encode())
                    if connection.recv(256).split(b' ')[1:2]==[b'404']:result['https_local']='PASS'
        except (OSError,ssl.SSLError):pass
        result['status']='LOCAL_CHECKS_PASS'if all(result['local_firewall'].values())and len(result['containers'])==2 and all(x=='running'for x in result['containers'].values())and result['tls']=='PASS'and result['dns']=='PASS'and result['https_local']=='PASS'else'INCOMPLETE'
        return result
    def snapshot(self):
        folder=self.own_dir(self.store.path/'backups');name=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns())[-6:]+'.tar.gz';path=folder/name
        with tarfile.open(path,'w:gz')as tar:
            for f in ['compose.json','node.env','nginx/nginx.conf','tls/live/fullchain.pem','tls/live/privkey.pem']:
                p=ROOT/f
                if p.exists():require(not p.is_symlink(),'Неожиданнаяссылка snapshot');tar.add(p,arcname='config/'+f,recursive=False)
            tar.add(self.store.path/'state.json',arcname='state.json',recursive=False)
            if CLI.exists():tar.add(CLI,arcname='polaris-node',recursive=False)
        path.chmod(0o600);return name
    def remove(self,confirmed=False):
        require(confirmed,'Откат требует явного подтверждения');require(not self.state.get('published')and not self.state.get('publication_intent')and not self.state.get('unpublication_intent'),'Сначала завершите unpublish в Panel; опубликованную или спорную ноду не останавливаем')
        snapshot=self.snapshot();self.state['rollback_pending']=True;self.store.save()
        owned=[]
        for name in render.units(self.c,self.identity):
            p=UNIT_DIR/name
            if p.is_file()and not p.is_symlink()and p.stat().st_uid==0 and '# Owned by Polaris Node Installer '+self.identity in p.read_text():owned.append(name)
        if 'polaris-node-renew.timer'in owned:self.r.call(['systemctl','disable','--now','polaris-node-renew.timer'],timeout=30)
        if 'polaris-node.service'in owned:self.r.call(['systemctl','stop','polaris-node.service'],timeout=60)
        self.stop()
        if owned:self.r.run(['systemctl','disable',*owned],timeout=30)
        self.remove_firewall()
        if 'polaris-node-firewall.service'in owned:self.r.call(['systemctl','stop','polaris-node-firewall.service'],timeout=30)
        self.state['rolled_back']=True;self.state['rollback_snapshot']=snapshot;self.store.save()
        return {'status':'OWN_RUNTIME_STOPPED','snapshot':snapshot,'docker_dependencies':'retained','remote_records':'retained hidden; no foreignresources deleted','ssh_firewall_policies':'unchanged'}
