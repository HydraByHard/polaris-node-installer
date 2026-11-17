#!/usr/bin/env python3
"""Disposable real Remnawave API fixture; all credentials are synthetic.

Start once, use protected fixture JSON in integration tests, stop explicitly.
No production URL is accepted and no secret value is printed.
"""
import argparse
import base64
import datetime
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import tempfile
import re
import urllib.request

MODULE = importlib.util.spec_from_file_location('polaris_remna_lab_base',Path(__file__).with_name('remna_base.py'))
legacy = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(legacy)
SCRATCH = Path(os.environ.get('PNI_REMNA_LAB_DIR',str(Path(tempfile.gettempdir())/'polaris-remna-lab'))).resolve()
PINS = json.loads((Path(__file__).with_name('remna-templates')/'pins.json').read_text())
ENROLLMENT_SCOPES = ['system:metadata', 'nodes:list', 'nodes:get', 'nodes:create',
                     'config-profiles:list', 'config-profiles:get', 'config-profiles:create',
                     'keygen:get', 'hosts:list', 'hosts:create']

def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    path.chmod(0o600)


class Fixture(legacy.Lab):
    def __init__(self, port=29443, pull=False):
        SCRATCH.mkdir(mode=0o700,parents=True,exist_ok=True)
        legacy.require(not SCRATCH.is_symlink() and SCRATCH.stat().st_uid==os.geteuid()
                       and not SCRATCH.stat().st_mode & 0o077,'private owned lab directory must have0700 mode')
        super().__init__(port,pull,work_root=SCRATCH)
        self.api_role = False

    def prepare(self):
        super().prepare()
        tls = self.work / 'tls'
        (tls / 'extensions').write_text('subjectAltName=DNS:localhost,DNS:remna-lab.local,IP:127.0.0.1,IP:10.0.2.2\nextendedKeyUsage=serverAuth\n')
        self.run(['openssl', 'x509', '-req', '-days', '2', '-in', 'tls/server.csr', '-CA', 'tls/ca.crt',
                  '-CAkey', 'tls/ca.key', '-CAcreateserial', '-extfile', 'tls/extensions', '-out', 'tls/server.crt'])

    def http(self, path, method='GET', data=None, authenticated=True, headers=None):
        if getattr(self, 'api_role', False) and authenticated:
            headers = {**(headers or {}), 'Authorization': 'Bearer ' + self.token}
            authenticated = False
        return super().http(path, method, data, authenticated, headers)

    def start(self):
        self.prepare()
        self.started = True
        self.compose('up', '-d', 'database', 'valkey', 'backend')
        config = (self.work / 'nginx.conf').read_text()
        (self.work / 'nginx.conf').write_text(config.replace('http://subscription:3010/', 'http://backend:3000/'))
        self.compose('up', '-d', 'gateway')
        self.wait(lambda: self.http('/api/auth/status', authenticated=False)[0] == 200,
                  'backend ready with verified local TLS', 180)
        credentials = {'username':'polaris_installer_lab_admin', 'password':'Aa1'+secrets.token_hex(24)}
        self.api('auth/register', 'POST', credentials, False)
        self.token = self.api('auth/login', 'POST', credentials, False)['accessToken']
        scopes = self.api('tokens/scopes')
        (self.work / 'scope-catalog.json').write_text(json.dumps(scopes, indent=2)+'\n')
        enrollment = self.api('tokens', 'POST', {'name':'polaris-enrollment-create-only', 'expiresInDays':1,
                                               'scopes': ENROLLMENT_SCOPES})
        subscription = self.api('tokens', 'POST', {'name':'polaris-synthetic-subscription', 'expiresInDays':1})
        self.env_file('subscription.env', {'APP_PORT':3010, 'REMNAWAVE_PANEL_URL':'http://backend:3000',
                                         'REMNAWAVE_API_TOKEN': subscription['token'], 'TRUST_PROXY':1})
        self.compose('up', '-d', 'subscription')
        (self.work / 'nginx.conf').write_text(config)
        self.compose('exec', '-T', 'gateway', 'nginx', '-s', 'reload')
        fixture = {'project':self.project, 'work':str(self.work), 'origin':self.origin, 'port':self.port,
                   'ca':str(self.work / 'tls/ca.crt'), 'adminToken':self.token,
                   'enrollmentToken':enrollment['token'], 'enrollmentTokenUuid':enrollment['uuid'],
                   'enrollmentScopes':ENROLLMENT_SCOPES}
        private_json(SCRATCH / 'fixture.json', fixture)
        self.ok('synthetic admin and scoped enrollment fixture saved privately')
        return fixture

    def connect_lab_network(self, network, hostname='panel.pni.test'):
        """Join only this fixture gateway/backend to a caller-owned lab bridge."""
        legacy.require(hostname=='panel.pni.test','test gateway hostname is fixed')
        import ipaddress
        addresses = {}
        for service,alias in [('gateway',hostname),('backend','pni-backend')]:
            container = self.compose('ps','-q',service).strip()
            networks = json.loads(self.run(['docker','inspect','--format','{{json .NetworkSettings.Networks}}',container]))
            if network not in networks:
                self.run(['docker','network','connect','--alias',alias,network,container])
                networks = json.loads(self.run(['docker','inspect','--format','{{json .NetworkSettings.Networks}}',container]))
            addresses[service] = str(ipaddress.ip_address(networks[network]['IPAddress']))
        address = addresses['gateway']
        (self.work/'tls/extensions').write_text('subjectAltName=DNS:localhost,DNS:remna-lab.local,DNS:pni-panel,DNS:panel.pni.test,IP:127.0.0.1,IP:10.0.2.2,IP:'+address+'\nextendedKeyUsage=serverAuth\n')
        self.run(['openssl','x509','-req','-days','2','-in','tls/server.csr','-CA','tls/ca.crt',
                  '-CAkey','tls/ca.key','-CAcreateserial','-extfile','tls/extensions','-out','tls/server.crt'])
        self.compose('exec','-T','gateway','nginx','-s','reload')
        path = self.work.parent/'fixture.json'
        data = json.loads(path.read_text())
        data.update(guestOrigin='https://'+address+':8443',guestDnsOrigin='https://'+hostname+':8443',
                    gatewayBridgeIp=address,backendBridgeIp=addresses['backend'],labNetwork=network)
        private_json(path,data)
        return data['guestDnsOrigin']

    @classmethod
    def attach(cls, fixture_path=None, role='admin'):
        fixture_path = Path(fixture_path) if fixture_path else SCRATCH/'fixture.json'
        data = json.loads(fixture_path.read_text())
        legacy.require(isinstance(data.get('port'),int) and 20000<=data['port']<=65535
                       and data.get('origin')==f"https://localhost:{data['port']}"
                       and re.fullmatch(r'polaris-remna-[0-9a-f]{12}',data.get('project',''))
                       and Path(data['work']).resolve().parent==fixture_path.resolve().parent,
                       'fixture must identify this private disposable loopback lab')
        # Do not allocate another project or directory when attaching.
        obj = cls.__new__(cls)
        obj.project, obj.work = data['project'], Path(data['work'])
        obj.port, obj.origin = data['port'], data['origin']
        obj.token = data['adminToken' if role == 'admin' else 'enrollmentToken']
        obj.passed, obj.started, obj.pull = [], True, False
        obj.api_role = role != 'admin'
        obj.make_opener(data['ca'])
        return obj


def verify_contracts():
    """Run real positive/negative contracts and preserve a synthetic baseline."""
    a=Fixture.attach();e=Fixture.attach(role='enrollment');checks=[];evidence={}
    def check(ok,name):
     legacy.require(ok,name);checks.append(name);print('PASS '+name,flush=True)
    def findcreate(resource,field,name,payload):
     r=a.api(resource); items=r if isinstance(r,list) else r[{'config-profiles':'configProfiles','internal-squads':'internalSquads','users':'users'}[resource]]
     return next((x for x in items if x.get(field)==name),None) or a.api(resource,'POST',payload)
    def cfg(tag,port,path):
     return {'log':{'loglevel':'warning'},'inbounds':[{'tag':tag,'listen':'127.0.0.1','port':port,'protocol':'vless','settings':{'clients':[],'decryption':'none'},'streamSettings':{'network':'xhttp','security':'none','xhttpSettings':{'path':path,'mode':'packet-up'}}}],'outbounds':[{'tag':'direct','protocol':'freedom'}]}
    def host(profile,node,name,domain,hidden):
     return {'remark':name,'address':domain,'port':443,'path':'/'+name+'/','sni':domain,'host':domain,'alpn':'h2','securityLayer':'TLS','isDisabled':hidden,'isHidden':hidden,'nodes':[node['uuid']],'inbound':{'configProfileUuid':profile['uuid'],'configProfileInboundUuid':profile['inbounds'][0]['uuid']},'xhttpExtraParams':{'mode':'packet-up'}}
    # Authentication and field wrappers.
    check(e.http('/api/system/metadata',authenticated=False)[0]==401,'metadata authentication required')
    metadata=e.api('system/metadata');check(metadata['version']=='3.4.11','version/build/source gate verified')
    evidence['metadata']=metadata
    for endpoint,typ in [('nodes',list),('config-profiles',dict),('hosts',list)]:
     check(isinstance(e.api(endpoint),typ),'GET '+endpoint+' response wrapper verified')
    # Seed an existing baseline isolated entirely in this fixture.
    oldprofile=findcreate('config-profiles','name','Polaris fixture existing',{'name':'Polaris fixture existing','config':cfg('fixture-existing',8081,'/fixture-existing/')})
    oldsecret=a.api('keygen')['secretKey'];a.env_file('node-existing.env',{'NODE_PORT':2222,'SNI_VERIFICATION':'true','SECRET_KEY':oldsecret})
    compose=a.work/'compose.yaml';text=compose.read_text();text=text.replace('  subscription:\n','  node-existing:\n    <<: *service\n    image: ${NODE_IMAGE:?}\n    env_file: node-existing.env\n  subscription:\n');compose.write_text(text) if '  node-existing:\n' not in compose.read_text() else None
    a.compose('up','-d','node-existing')
    oldnode=findcreate('nodes','name','fixture-existing-node',{'name':'fixture-existing-node','address':'node-existing','port':2222,'configProfile':{'activeConfigProfileUuid':oldprofile['uuid'],'activeInbounds':[oldprofile['inbounds'][0]['uuid']]}})
    squad=findcreate('internal-squads','name','Fixture personal',{'name':'Fixture personal','inbounds':[oldprofile['inbounds'][0]['uuid']]})
    oldhost=findcreate('hosts','remark','fixture-existing',host(oldprofile,oldnode,'fixture-existing','existing.pni.test',False))
    user=findcreate('users','username','fixture_existing_user',{'username':'fixture_existing_user','activeInternalSquads':[squad['uuid']],'expireAt':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)).isoformat()})
    a.wait(lambda:a.api('nodes/'+oldnode['uuid'])['isConnected'],'existing synthetic node connected',150)
    a.wait(lambda:a.api('nodes/'+oldnode['uuid'])['xrayUptime']>0,'existing synthetic Xray running',90)
    before={k:(next(x for x in a.api(v)['users'] if x['username']=='fixture_existing_user') if k=='user' else a.api(v)) for k,v in {'profile':'config-profiles/'+oldprofile['uuid'],'host':'hosts/'+oldhost['uuid'],'squad':'internal-squads/'+squad['uuid'],'user':'users'}.items()}
    # Narrow token creates only fresh resources.
    profile=e.api('config-profiles','POST',{'name':'PNI fixture new profile','config':cfg('pni-fixture-new',8082,'/pni-fixture-new/')})
    key1=e.api('keygen')['secretKey'];key2=e.api('keygen')['secretKey'];p1=json.loads(base64.b64decode(key1));p2=json.loads(base64.b64decode(key2))
    check(set(p1)=={'nodeCertPem','nodeKeyPem','caCertPem','jwtPublicKey'},'node payload has per-node key/certificate, CA certificate and public JWT key only')
    check(p1['nodeKeyPem']!=p2['nodeKeyPem'] and p1['nodeCertPem']!=p2['nodeCertPem'] and p1['caCertPem']==p2['caCertPem'],'keygen rotates per-node credentials without distributing CA private key')
    a.env_file('node.env',{'NODE_PORT':2222,'SNI_VERIFICATION':'true','SECRET_KEY':key1});a.compose('up','-d','node')
    node=e.api('nodes','POST',{'name':'pni-fixture-new-node','address':'node','port':2222,'countryCode':'FI','tags':['PNI_LAB_OWNED'],'configProfile':{'activeConfigProfileUuid':profile['uuid'],'activeInbounds':[profile['inbounds'][0]['uuid']]}})
    h=e.api('hosts','POST',host(profile,node,'pni-fixture-new','new.pni.test',True));check(h['isHidden'] and h['isDisabled'],'scoped token creates disabled hidden Host with explicit Node/inbound/TLS/h2/XHTTP mode')
    check(e.api('config-profiles/'+profile['uuid'])['uuid']==profile['uuid'],'scoped GET profile returns detailed config')
    check(any(x['uuid']==h['uuid'] for x in e.api('hosts')),'scoped list returns new Host for ownership/idempotency check')
    e.wait(lambda:e.api('nodes/'+node['uuid'])['isConnected'],'new Node connected through native mTLS',150)
    e.wait(lambda:e.api('nodes/'+node['uuid'])['xrayUptime']>0,'new Node Xray localhost8082 XHTTP configuration running',90)
    status=e.api('nodes/'+node['uuid']);evidence['nodeStatusFields']=list(status);evidence['nodeVersions']=status.get('versions')
    for endpoint,method,data in [('users','GET',None),('internal-squads','GET',None),('hosts','PATCH',{'uuid':h['uuid'],'isHidden':False}),('nodes','PATCH',{'uuid':node['uuid'],'name':'not-allowed'}),('config-profiles','PATCH',{'uuid':profile['uuid'],'name':'not-allowed'}),('tokens/'+json.loads((SCRATCH/'fixture.json').read_text())['enrollmentTokenUuid'],'DELETE',None)]:
     check(e.http('/api/'+endpoint,method,data)[0]==403,'enrollment denied '+method+' '+endpoint.split('/')[0])
    for k,v in {'profile':'config-profiles/'+oldprofile['uuid'],'host':'hosts/'+oldhost['uuid'],'squad':'internal-squads/'+squad['uuid'],'user':'users'}.items():
     after=(next(x for x in a.api(v)['users'] if x['username']=='fixture_existing_user') if k=='user' else a.api(v))
     # User updateAt can change due background initial squad assignment; compare authorization and subscription identity explicitly.
     if k=='user':
      keys=('uuid','shortUuid','vlessUuid','activeInternalSquads','subscriptionUrl')
      check(all(before[k].get(key)==after.get(key) for key in keys),'existing user identities, subscription and squad membership unchanged')
     else: check(before[k]==after,'existing '+k+' unchanged by enrollment')
    # Separate publication scopes, no user modification permissions.
    pubscopes=['hosts:get','hosts:update','internal-squads:list','internal-squads:get','internal-squads:update']
    t=a.api('tokens','POST',{'name':'pni-fixture-publish','expiresInDays':1,'scopes':pubscopes});p=Fixture.attach(role='enrollment');p.token=t['token']
    snap=p.api('internal-squads/'+squad['uuid']);evidence['squadResponseKeys']=list(snap)
    # Squad inbounds objects include UUIDs rather than a plain UUID array.
    oldids=[x['uuid'] if isinstance(x,dict) else x for x in snap['inbounds']]
    newid=profile['inbounds'][0]['uuid'];updated=p.api('internal-squads','PATCH',{'uuid':squad['uuid'],'inbounds':oldids+[newid]})
    check({x['uuid'] if isinstance(x,dict) else x for x in updated['inbounds']}==set(oldids+[newid]),'separate publication scope appends inbound while retaining every old UUID')
    published=p.api('hosts','PATCH',{'uuid':h['uuid'],'isDisabled':False,'isHidden':False});check(not published['isDisabled'] and not published['isHidden'],'separate publication scope enables/unhides exactly owned Host')
    check(p.http('/api/users','GET')[0]==403,'publication token cannot read/modify users')
    # Put own new Host back into unpublished state and restore synthetic squad original permissions.
    p.api('hosts','PATCH',{'uuid':h['uuid'],'isDisabled':True,'isHidden':True});p.api('internal-squads','PATCH',{'uuid':squad['uuid'],'inbounds':oldids})
    check(a.api('hosts/'+oldhost['uuid'])==before['host'],'existing Host unchanged after publish/unpublish')
    # Delete contract verifies only throwaway owned resources using separate scopes.
    dscopes=['hosts:delete','nodes:delete','config-profiles:delete'];dt=a.api('tokens','POST',{'name':'pni-fixture-delete','expiresInDays':1,'scopes':dscopes});d=Fixture.attach(role='enrollment');d.token=dt['token']
    for resource,uuid in [('hosts',h['uuid']),('nodes',node['uuid']),('config-profiles',profile['uuid'])]:
     check(d.http('/api/'+resource+'/'+uuid,'DELETE')[0]==204,'separate rollback DELETE '+resource+' returns204')
    for token in [t,dt]:check(a.http('/api/tokens/'+token['uuid'],'DELETE')[0]==204,'admin JWT revokes temporary scope token')
    evidence.update(enrollmentScopes=ENROLLMENT_SCOPES,publishScopes=pubscopes,rollbackScopes=dscopes,checks=checks,scope='Isolated synthetic Docker API/Node fixture. No production calls or credentials.',success=True)
    (SCRATCH/'contract-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    # Preserve baseline IDs privately for integration subscriber regression assertions.
    f=json.loads((SCRATCH/'fixture.json').read_text());f['baseline']={'profileUuid':oldprofile['uuid'],'nodeUuid':oldnode['uuid'],'hostUuid':oldhost['uuid'],'squadUuid':squad['uuid'],'userId':user['id'],'userShortUuid':user['shortUuid']};private_json(SCRATCH/'fixture.json',f)
    print('REPORT='+str(SCRATCH/'contract-evidence.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status', 'connect', 'contracts'])
    parser.add_argument('--port', type=int, default=29443)
    parser.add_argument('--pull', action='store_true')
    parser.add_argument('--network', help='Caller-owned isolated Docker network for VM test gateway')
    parser.add_argument('--work-dir',type=Path,default=SCRATCH,help='Private synthetic fixture directory (or PNI_REMNA_LAB_DIR)')
    args = parser.parse_args()
    globals()['SCRATCH'] = args.work_dir.resolve()
    if args.action == 'start':
        legacy.require(20000<=args.port<=65535,'lab port must be20000..65535')
        legacy.require(not (SCRATCH/'fixture.json').exists(), 'fixture already exists; attach or stop first')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', args.port))
        fixture = Fixture(args.port, args.pull)
        try:
            data = fixture.start()
        except Exception:
            # Keep private logs and own project for diagnosis; never print body.
            print('FAIL lab startup; private scratch retained at '+str(fixture.work))
            raise
        print('FIXTURE='+str(SCRATCH/'fixture.json'))
        print('ORIGIN='+data['origin'])
    elif args.action == 'contracts':
        verify_contracts()
    elif args.action == 'connect':
        legacy.require(bool(args.network), '--network is required')
        fixture = Fixture.attach()
        print('GUEST_ORIGIN='+fixture.connect_lab_network(args.network))
    elif args.action == 'stop':
        fixture = Fixture.attach()
        fixture.cleanup()
        (SCRATCH/'fixture.json').unlink()
        print('PASS own fixture containers, volumes and network removed')
    else:
        fixture = Fixture.attach()
        metadata = fixture.api('system/metadata')
        print(json.dumps({'origin':fixture.origin, 'metadata':metadata}, indent=2))

if __name__ == '__main__':
    main()
