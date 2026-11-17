"""Console interface. API credentials exist only during the invoking process."""
import argparse,base64,getpass,hashlib,ipaddress,json,os,pathlib,re,shutil,socket,ssl,sys,tempfile,time,urllib.request
from . import __version__
from .core import PINS,PolarisError,StateStore,normalize_config,require,redact,owned_file,atomic_write,retry_config
from .api import API
from .registrar import Registrar
from .system import System,Runner,ROOT,CLI,D

class SafeParser(argparse.ArgumentParser):
    def error(self,message):self.exit(2,'Ошибка параметров. См.--help. API токен передаётся скрытым вводом или --token-fd, никогда аргументом.\n')

def parser():
    p=SafeParser(description='FOLLOW YOUR POLARIS — Node Installer. Статус после install: READY FOR TESTING, Host скрыт.')
    p.add_argument('command',nargs='?',default='install',choices=['install','status','doctor','logs','update','rollback','publish','unpublish','access','scopes','_firewall','_start','_stop','_renew'])
    p.add_argument('--version',action='version',version=__version__)
    p.add_argument('--config',help='JSON только публичных параметров; API токены запрещены')
    p.add_argument('--token-fd',type=int,help='Номер FD секретного ввода; не самтокен')
    p.add_argument('--non-interactive',action='store_true');p.add_argument('--online',action='store_true');p.add_argument('--confirm')
    p.add_argument('--remove',action='store_true',help='rollback только собственных локальных служб, с подтверждением')
    p.add_argument('--snapshot',help='Имя собственного snapshot для rollback обновления')
    p.add_argument('--test-config',help='doctor:root0600JSON конфигурация выделенного тестового пользователя')
    p.add_argument('--panel-ip',action='append',help='access:точный IPv4 Panel (не CIDR)');p.add_argument('--panel-ip6',action='append',help='access:точный IPv6 Panel')
    p.add_argument('--test-url',default='https://api.ipify.org',help='doctor:контрольный URL, возвращающий IPv4 egress')
    p.add_argument('--purpose',choices=['install','publish','rollback'],default='install',help='scopes:назначение временного токена')
    return p

def read_token(fd=None):
    if fd is not None:
        require(fd>=0,'Неверный FD');data=os.read(fd,16385);require(len(data)<=16384,'Слишкомдлинныйтокен');return data.decode().strip()
    require(sys.stdin.isatty(),'Нуженинтерактивный TTY или --token-fd для скрытого токена')
    return getpass.getpass('Временный 1-дневный API токен Panel (ввод скрыт, не сохраняется): ').strip()

def ask(label,default=None):
    value=input(label+(' ['+str(default)+']'if default else'')+': ').strip();return value or default

def collect_config(args,existing):
    if args.config:
        try:raw=json.loads(pathlib.Path(args.config).read_text())
        except (OSError,ValueError):raise PolarisError('Не удалось прочитать JSON параметров')from None
    elif existing:return existing
    else:
        require(not args.non_interactive,'Длянеинтерактивной установки нужен --config')
        print('========================================\n       FOLLOW YOUR POLARIS\n         NODE INSTALLER\n========================================')
        name=ask('Название ноды','finland-01');raw={'name':name,'country':ask('Страна (Finland/FI, Germany/DE, Netherlands/NL)','FI'),'domain':ask('Домен',name+'.followyourpolaris.space'),'panel_url':ask('Panel','https://panel.followyourpolaris.space')}
    c=normalize_config(raw)
    if not c['public_ipv4']:
        try:
            with urllib.request.urlopen('https://api.ipify.org',timeout=12)as r:value=r.read(64).decode().strip()
            require(ipaddress.ip_address(value).version==4,'Нет IPv4');c['public_ipv4']=value
        except Exception:require(not args.non_interactive,'Не определён IPv4: задайте public_ipv4 в JSON');c['public_ipv4']=ask('Публичный IPv4 VPS')
        if not args.non_interactive:c['public_ipv4']=ask('IPv4 этой VPS',c['public_ipv4'])
    if not c['management_address']:c['management_address']=c['public_ipv4']
    if not c['panel_ipv4']:
        host=urllib.parse.urlsplit(c['panel_url']).hostname
        try:addresses=sorted({x[4][0]for x in socket.getaddrinfo(host,443,family=socket.AF_INET,type=socket.SOCK_STREAM)})
        except OSError:addresses=[]
        require(addresses,'Не разрешается Panel DNS')
        require(not args.non_interactive,'Укажите panel_ipv4: фактические исходящие IP Panel, а не CDN')
        text=ask('Исходящий IPv4 Panel (если CDN—задайте IP VPS)',','.join(addresses));c['panel_ipv4']=text.split(',')
    if c['tls_mode']=='acme'and not c['email']and not args.non_interactive:c['email']=ask('Email для восстановления ACME (можно Enter)')or None
    c=normalize_config(c);require(c['public_ipv4']and c['management_address']and c['panel_ipv4'],'Не заданы адрес VPS/management/Panel allowlist')
    if existing:retry_config(existing,c)
    return c

class ReadStore:
    """systemd helpers read an atomic state and never write it or take caller's lock."""
    def __init__(self):
        self.path=pathlib.Path('/var/lib/polaris-node');require(not self.path.is_symlink()and self.path.stat().st_uid==0 and not self.path.stat().st_mode&0o077,'Небезопасный state-каталог');self.data=json.loads(owned_file(self.path/'state.json').read_text())
        require(self.data.get('schema')==1 and re.fullmatch('[a-f0-9]{32}',self.data.get('install_id',''))is not None,'Чужой state')
        require(normalize_config(self.data['config'])==self.data['config'],'Повреждены параметры state')
    def checkpoint(self,*args):pass
    def save(self):raise PolarisError('Системный helper не изменяет state')

def internal(command):
    require(os.geteuid()==0,'Нужен root')
    if command=='_renew':
        with StateStore()as store:
            system=System(store);require(not store.data.get('rolled_back')and not store.data.get('rollback_pending'),'Runtime отключён');system.acme(renew=True);system.r.run(D+['exec','polaris-gateway-'+store.data['install_id'][:12],'nginx','-c','/etc/polaris/nginx.conf','-t'],timeout=20);system.r.run(D+['exec','polaris-gateway-'+store.data['install_id'][:12],'nginx','-c','/etc/polaris/nginx.conf','-s','reload'],timeout=20)
        return
    store=ReadStore();system=System(store)
    if command!='_stop':require(not store.data.get('rolled_back')and not store.data.get('rollback_pending'),'Runtime отключён')
    if command=='_firewall':system.firewall()
    elif command=='_start':system.start()
    elif command=='_stop':system.stop()

def wait_online(registrar,timeout=120):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        node=registrar.online()
        if node.get('isConnected')is True and not node.get('isDisabled'):
            versions=node.get('versions')or{}
            require(versions.get('node')==PINS['node_version']and versions.get('xray')==PINS['xray_version'],'Фактические Node/Xray не совпадают с compatibility matrix')
            return node
        time.sleep(2)
    raise PolarisError('Panel не видит Node ONLINE: проверьте allowlist, sourceIP Panel, nativepayload и внешнююсеть; NodeAPI не открываетсядлявсех')

def activate_runtime(config,restart=False,runner=None):
    runner=runner or Runner()
    runner.run(['systemctl','restart'if restart else'start','polaris-node-firewall.service','polaris-node.service'],timeout=240)
    runner.run(['systemctl','is-active','--quiet','polaris-node-firewall.service','polaris-node.service'],timeout=30)
    if config['tls_mode']=='acme':
        runner.run(['systemctl','enable','--now','polaris-node-renew.timer'],timeout=30)
        runner.run(['systemctl','is-active','--quiet','polaris-node-renew.timer'],timeout=30)

def runtime_restore(system,name):
    require(name and pathlib.Path(name).name==name,'Нужно имя собственного snapshot')
    path=owned_file(system.store.path/'backups'/name);require(path.is_file(),'Snapshot не найден')
    import tarfile
    allowed={'state.json','polaris-node','config/compose.json','config/node.env','config/nginx/nginx.conf','config/tls/live/fullchain.pem','config/tls/live/privkey.pem'}
    try:
        with tarfile.open(path)as tar:
            members=tar.getmembers();names=[x.name for x in members]
            required={'state.json','polaris-node','config/compose.json','config/node.env','config/nginx/nginx.conf'}
            require(len(names)==len(set(names))and required<=set(names)and sum(x.size for x in members)<32*1024**2 and all(x.isfile()and x.name in allowed and 0<=x.size<16*1024**2 for x in members),'Небезопасный или неполный snapshot')
            # Read and validate the complete archive before touching any live file.
            staged={x.name:tar.extractfile(x).read()for x in members}
        restored=json.loads(staged['state.json'])
        require(restored.get('schema')==1 and restored.get('install_id')==system.identity and restored.get('resources')==system.store.data.get('resources'),'Чужой snapshot или другие удалённые ресурсы')
        require(normalize_config(restored['config'])==restored['config'],'Повреждены параметры snapshot');retry_config(system.c,restored['config'])
        tls_members={'config/tls/live/fullchain.pem','config/tls/live/privkey.pem'}
        require(not (tls_members&set(staged))or tls_members<=set(staged),'Неполная TLS пара snapshot')
        require(not restored.get('stages',{}).get('tls')or tls_members<=set(staged),'Snapshot не содержит готовую TLS пару')
        current_key=ROOT/'node.env'
        if current_key.exists():require(owned_file(current_key).read_bytes()==staged['config/node.env'],'Snapshot не должен заменять существующую native Node identity')
        # A local rollback must never rewind the record of an external publication.
        for key in set(restored)|set(system.store.data):
            if key=='published'or key.startswith(('publication','unpublication')):
                if key in system.store.data:restored[key]=system.store.data[key]
                else:restored.pop(key,None)
        from .core import assert_public_state
        assert_public_state(restored)
        for member in staged:
            if member.startswith('config/'):owned_file(ROOT/member[7:],private=False)
        owned_file(CLI,private=False)
        for member,data in staged.items():
            if member.startswith('config/')and member not in tls_members:atomic_write(ROOT/member[7:],data)
        if tls_members<=set(staged):system.deploy_tls(staged['config/tls/live/fullchain.pem'],staged['config/tls/live/privkey.pem'])
        atomic_write(CLI,staged['polaris-node'],0o755)
    except (tarfile.TarError,KeyError,ValueError,OSError):raise PolarisError('Повреждённый snapshot; восстановление остановлено')from None
    system.store.data=restored;system.state=restored;system.c=restored['config'];system.store.save();system.firewall();system.install_units()
    # No state writes may follow this point; timer helpers can now take the lock.
    system.store.close();activate_runtime(system.c,restart=True,runner=system.r)
    return {'status':'OWN_SNAPSHOT_RESTORED','snapshot':name}

def test_traffic(system,config_file,probe_url="https://api.ipify.org"):
    """Optional isolated user's Xray JSON; no routing/sysctl or persistent client."""
    import copy
    url=urllib.parse.urlsplit(probe_url);require(url.scheme=='https'and bool(url.hostname)and not url.username and not url.password and not url.fragment,'Контрольный URL должен использовать HTTPS без credentials')
    p=owned_file(config_file);data=json.loads(p.read_text());data=data[0]if isinstance(data,list)and len(data)==1 else data
    config=copy.deepcopy(data);vless=[x for x in config.get('outbounds',[])if x.get('protocol')=='vless'];require(len(vless)==1,'Нуженодин VLESSoutbound')
    stream=vless[0].get('streamSettings',{});endpoint=vless[0].get('settings',{}).get('vnext',[{}])[0]
    require(endpoint.get('address')==system.c['domain']and endpoint.get('port')==system.c['vpn_port']and stream.get('security')=='tls'and stream.get('network')=='xhttp'and stream.get('tlsSettings',{}).get('serverName')==system.c['domain']and stream.get('tlsSettings',{}).get('alpn')==['h2']and not stream.get('tlsSettings',{}).get('allowInsecure'),'Тестоваяконфигурация должна относитьсятолько кэтойнодеи использовать verifiedTLS/h2/XHTTP')
    with socket.socket()as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    require(not vless[0].get('proxySettings')and not vless[0].get('sendThrough')and not stream.get('sockopt',{}).get('dialerProxy'),'Тестовый VLESS outbound не должен обходить эту ноду')
    config={'outbounds':[vless[0]]};stream['tlsSettings']['useSystemCA']=True;vless[0]['tag']='pni-test-proxy';config['inbounds']=[{'tag':'pni-test','listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth','udp':False}}];config['routing']={'rules':[{'type':'field','inboundTag':['pni-test'],'outboundTag':'pni-test-proxy'}]};config['log']={'loglevel':'none'}
    name='pni-test-'+system.identity[:12]
    with tempfile.TemporaryDirectory(prefix='traffic-',dir=system.store.path)as tmp:
        file=pathlib.Path(tmp)/'client.json';atomic_write(file,json.dumps(config));created=False
        try:
            system.r.run(D+['run','-d','--name',name,'--network','host','--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','192m','--mount','type=bind,src='+str(file)+',dst=/run/client.json,readonly','--mount','type=bind,src=/etc/ssl/certs/ca-certificates.crt,dst=/etc/ssl/certs/ca-certificates.crt,readonly','--entrypoint','xray',PINS['images']['node'],'run','-config','/run/client.json'],timeout=30);created=True
            for _ in range(50):
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2):break
                except OSError:time.sleep(.1)
            output=system.r.run(['curl','--fail','--silent','--show-error','--max-time','25','--noproxy','','--proxy','socks5h://127.0.0.1:'+str(port),probe_url],timeout=30)
            require(output.strip()==system.c['public_ipv4'],'VPNegressIP не совпал сожидаемым VPS')
        finally:
            if created:system.r.run(D+['rm','-f',name],timeout=30)
    return {'actual_vpn_traffic':'PASS','egress_matches_node':True,'temporary_client_removed':True}

def main(argv=None):
    args=parser().parse_args(argv)
    if args.command=='scopes':print('\n'.join(API.scope_list(args.purpose)));return 0
    if args.command.startswith('_'):internal(args.command);return 0
    System.basic(strict=args.command in ('install','update'));activate=False
    with StateStore()as store:
        if args.command=='install':
            c=collect_config(args,store.data.get('config'));token=read_token(args.token_fd);api=API(c['panel_url'],token);metadata=api.metadata()
            if not store.data:store.create(c)
            else:store.data['config']=c
            store.data['panel_version_verified']=metadata['version'];store.data['rolled_back']=False;store.data['rollback_pending']=False;store.save()
            system=System(store);system.prepare_dirs();system.dependencies();system.check_ports()
            print('[1/8] Проверка системы — OK\n[2/8] Docker и Compose')
            system.docker();system.pull()
            print('[3/8] Подготовка собственной ноды и скрытого Host')
            registrar=Registrar(api,store.data,store.save);registrar.ensure();system.node_identity(api)
            print('[4/8] Настройка изоляции Node API')
            system.firewall();system.write_configs(bool(store.data['stages'].get('tls')))
            source=os.environ.get('POLARIS_RELEASE_SOURCE');require(source,'Запустите проверенныйполный polaris-install.sh');system.install_cli(source);system.install_units();system.start()
            print('[5/8] Подключение к Panel');wait_online(registrar);store.data['last_panel_check']=int(time.time());store.save();system.check_xray()
            print('[6/8] HTTPS/HTTP2/XHTTP transport')
            print('[7/8] DNS и TLS');system.dns(not args.non_interactive)
            if c['tls_mode']=='provided':system.provided_tls()
            else:system.acme()
            system.write_configs(True);system.start();wait_online(registrar);system.check_xray()
            print('[8/8] Проверка результата');report=system.doctor();require(report['status']=='LOCAL_CHECKS_PASS','Не все локальныепроверкиуспешны')
            store.data['last_panel_check']=int(time.time());store.data['status']='READY_FOR_TESTING';store.save();activate=True
            visibility=registrar.host_visibility
            print('INSTALLATION COMPLETE\nSTATUS: READY FOR TESTING\nNode: ONLINE\nHost: VERIFIED\nVisibility: '+('HIDDEN (disabled AND hidden)'if all(visibility.values())else'PUBLISHED/REVIEW: '+json.dumps(visibility))+'\nЛокальные DNS/TLS/firewall: OK\nВнешняя доступность VPN и изоляция API: требуют независимого теста\nVPN traffic: NOT TESTED — нужен изолированный тестовый пользователь\nAPI token: не сохранён. Удалите его в Panel для немедленного отзыва; иначе он истечёт в свой 1-дневный срок.')
            api._token='';token=''
        else:
            require(bool(store.data),'Polaris Node не установлен');system=System(store)
            if args.command in ('status','doctor'):
                report=system.doctor()
                if args.online:
                    api=API(store.data['config']['panel_url'],read_token(args.token_fd));reg=Registrar(api,store.data,store.save);node=wait_online(reg,timeout=20);report['panel_live']='ONLINE';report['host_visibility']=reg.visibility();report['node_versions']=node.get('versions');store.data['last_panel_check']=int(time.time());store.save();api._token=''
                if args.test_config:report.update(test_traffic(system,args.test_config,args.test_url))
                print(json.dumps(report,ensure_ascii=False,indent=2))
            elif args.command=='access':
                require(args.panel_ip or args.panel_ip6,'Укажите --panel-ip и/или --panel-ip6')
                updated=dict(system.c)
                if args.panel_ip:updated['panel_ipv4']=args.panel_ip
                if args.panel_ip6:updated['panel_ipv6']=args.panel_ip6
                updated=normalize_config(updated);retry_config(system.c,updated);snapshot=system.snapshot();store.data['config']=updated;store.save();system.c=updated;system.firewall();print(json.dumps({'allowlist_updated':True,'snapshot':snapshot,'api_port_public':False,'ssh_unchanged':True}))
            elif args.command=='logs':
                key=owned_file(ROOT/'node.env').read_text().split('SECRET_KEY=',1)[1].strip();out=system.compose('logs','--no-color','--tail','100',timeout=30);print(redact(out,[key]))
            elif args.command=='publish':
                report=system.doctor();require(report['status']=='LOCAL_CHECKS_PASS','Сначалаустраните doctor ошибки')
                text='PUBLISH '+store.data['config']['name'];answer=args.confirm or(''if args.non_interactive else input('Публикация измениттолько Host этой Node и добавитего Inbound в Polaris personal. Не редактируйте Squad параллельно. Введите '+text+': '))
                require(answer==text,'Публикациянеподтверждена');api=API(system.c['panel_url'],read_token(args.token_fd),purpose='publish');registrar=Registrar(api,store.data,store.save);wait_online(registrar);registrar.publish(confirmed=True);api._token='';print('Host PUBLISHED; прежние ссылки подписок и права Squad сохранены')
            elif args.command=='unpublish':
                text='UNPUBLISH '+system.c['name'];answer=args.confirm or(''if args.non_interactive else input('Скрыть только свой Host и убрать только доказанно добавленное этим установщиком право Squad. Введите '+text+': '))
                require(answer==text,'Скрытие не подтверждено');api=API(system.c['panel_url'],read_token(args.token_fd),purpose='publish');Registrar(api,store.data,store.save).unpublish(confirmed=True);api._token='';print('Host HIDDEN; остальные разрешения Squad сохранены')
            elif args.command=='update':
                api=API(system.c['panel_url'],read_token(args.token_fd));api.metadata();api._token=''
                old=json.loads((ROOT/'compose.json').read_text());wanted={PINS['images']['node'],PINS['images']['nginx']};actual={x['image']for x in old['services'].values()}
                source=pathlib.Path(os.environ['POLARIS_RELEASE_SOURCE']);same_program=hashlib.sha256(source.read_bytes()).hexdigest()==hashlib.sha256(CLI.read_bytes()).hexdigest()
                if wanted==actual and same_program:print('Уже установленызакреплённыесовместимыеверсии; latest не используется')
                else:
                    snapshot=system.snapshot();store.data['update_snapshot']=snapshot;store.save()
                    try:system.pull();system.write_configs(True);system.start();system.check_xray();system.install_cli(os.environ['POLARIS_RELEASE_SOURCE']);store.data['installer_version']=PINS['installer'];store.save()
                    except PolarisError:runtime_restore(system,snapshot);raise
                    print('UPDATE COMPLETE; rollback snapshot: '+snapshot)
            elif args.command=='rollback':
                text='ROLLBACK '+system.c['name'];answer=args.confirm or(''if args.non_interactive else input('Откаттолько собственныхресурсов. Введите '+text+': '));require(answer==text,'Откатнеподтверждён')
                print(json.dumps(system.remove(True)if args.remove else runtime_restore(system,args.snapshot or store.data.get('update_snapshot')),ensure_ascii=False))
    if activate:activate_runtime(c)
    return 0

def entry():
    try:return main()
    except (PolarisError,KeyboardInterrupt)as error:
        message='Операция прервана; повторный запуск продолжитс сохранённого состояния'if isinstance(error,KeyboardInterrupt)else str(error)
        print('ERROR: '+redact(message),file=sys.stderr);return 2
    except Exception:
        print('ERROR: непредвиденнаяошибка; секретный traceback скрыт. Состояние сохранено, проверьте doctor и повторите запуск.',file=sys.stderr);return 3
if __name__=='__main__':raise SystemExit(entry())
