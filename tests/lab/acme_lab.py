#!/usr/bin/env python3
"""Private Pebble fixture for real HTTP-01 issuance and renewal in test VMs.

No validation bypass, production domains, Docker socket mounts or host network.
Fresh transport PKI is generated outside Git; only its public roots are shared
with disposable guests. See README-acme.md for the tested procedure.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

IMAGE = 'ghcr.io/letsencrypt/pebble:2.10.3@sha256:b436c398c723ca209129218e907a3c3fdcaeab71bc42e5bdef819645ad94ac37'
SOURCES = ['https://github.com/letsencrypt/pebble/releases/tag/v2.10.3',
           'https://github.com/letsencrypt/pebble/blob/v2.10.3/test/config/pebble-config.json',
           'https://github.com/letsencrypt/pebble/blob/v2.10.3/README.md']


class Failure(RuntimeError):pass


def require(ok,message):
    if not ok:raise Failure(message)


def private_write(path,body):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(body if isinstance(body,bytes) else body.encode())
    path.chmod(0o600)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise Failure('local test authority redirects are forbidden')


class Pebble:
    def __init__(self,root):
        self.root=Path(root).expanduser().resolve()
        require(not any((p/'.git').is_file() or (p/'.git/HEAD').exists() for p in (self.root,*self.root.parents)),'test PKI directory must be outside Git')
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        require(self.root.stat().st_uid==os.geteuid() and not self.root.stat().st_mode&0o077,'test PKI directory must be owned and0700')
        self.path=self.root/'fixture.json'

    def run(self,args,timeout=120):
        if args[0]=='docker':args=['docker','--host','unix:///var/run/docker.sock',*args[1:]]
        try:r=subprocess.run(args,cwd=self.root,capture_output=True,text=True,timeout=timeout,check=False)
        except (OSError,subprocess.TimeoutExpired):raise Failure('fixture command unavailable or timed out') from None
        if r.returncode:
            private_write(self.root/'command-failure.log',r.stdout+r.stderr)
            raise Failure('fixture command failed; output retained privately')
        return r.stdout

    def data(self):return json.loads(self.path.read_text())

    def opener(self):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(self.root/'transport-ca.crt'))))

    def get(self,path,management=False):
        data=self.data();port=data['managementPort' if management else 'httpsPort']
        with self.opener().open('https://localhost:'+str(port)+path,timeout=5) as response:return response.read()

    def sign_server(self,address=None):
        san='DNS:localhost,DNS:pebble.pni.test,IP:127.0.0.1'
        if address:san+=',IP:'+str(ipaddress.ip_address(address))
        private_write(self.root/'server.extensions','subjectAltName='+san+'\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
        self.run(['openssl','x509','-req','-days','3','-in','server.csr','-CA','transport-ca.crt','-CAkey','transport-ca.key','-CAcreateserial','-extfile','server.extensions','-out','server.crt'])

    def start(self,network,node_host,node_address,https_port=31400,management_port=31500,pull=False):
        require(not self.path.exists(),'fixture exists; preserve it or stop explicitly')
        require(re.fullmatch(r'pni-[a-z0-9-]+',network),'use an explicitly caller-owned pni- lab network')
        require(re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)*\.pni\.test',node_host),'only synthetic .pni.test Node domains are accepted')
        address=ipaddress.ip_address(node_address)
        require(address.version==4 and address.is_private and not address.is_loopback,'Node target must be an isolated bridge IPv4 address')
        require(https_port!=management_port and all(20000<=p<=65535 for p in (https_port,management_port)),'distinct loopback test ports required')
        for port in (https_port,management_port):
            with socket.socket() as probe:probe.bind(('127.0.0.1',port))
        if pull:self.run(['docker','pull',IMAGE],timeout=600)
        self.run(['docker','image','inspect',IMAGE],timeout=30)
        self.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','3','-subj','/CN=Polaris isolated ACME transport CA','-keyout','transport-ca.key','-out','transport-ca.crt','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign'])
        self.run(['openssl','req','-newkey','rsa:2048','-nodes','-subj','/CN=pebble.pni.test','-keyout','server.key','-out','server.csr'])
        self.sign_server()
        config={'pebble':{'listenAddress':'0.0.0.0:14000','managementListenAddress':'0.0.0.0:15000',
            'certificate':'/run/pni/server.crt','privateKey':'/run/pni/server.key','httpPort':80,'tlsPort':443,
            'externalAccountBindingRequired':False,'retryAfter':{'authz':1,'order':1},'keyAlgorithm':'ecdsa',
            'profiles':{'default':{'description':'Isolated real HTTP-01 tests','validityPeriod':7776000}}}}
        private_write(self.root/'pebble.json',json.dumps(config,indent=2)+'\n')
        name='pni-pebble-'+secrets.token_hex(6)
        cmd=['docker','run','-d','--name',name,'--label','io.polaris.acme='+name,'--network',network,
             '--network-alias','pebble.pni.test','--user',str(os.getuid())+':'+str(os.getgid()),'--add-host',node_host+':'+str(address),
             '--read-only','--tmpfs','/tmp:rw,nosuid,size=32m','--cap-drop','ALL','--security-opt','no-new-privileges:true',
             '--memory','128m','--cpus','0.5','--pids-limit','64',
             '-p','127.0.0.1:'+str(https_port)+':14000','-p','127.0.0.1:'+str(management_port)+':15000',
             '-e','PEBBLE_VA_NOSLEEP=1','-e','PEBBLE_AUTHZREUSE=0','-e','NO_PROXY=*','-e','no_proxy=*']
        for source,target in [('pebble.json','config.json'),('server.crt','server.crt'),('server.key','server.key')]:
            cmd+=['--mount','type=bind,src='+str(self.root/source)+',dst=/run/pni/'+target+',readonly']
        cmd+=[IMAGE,'-config','/run/pni/config.json','-strict']
        self.run(cmd)
        bridge=self.run(['docker','inspect','--format','{{(index .NetworkSettings.Networks "'+network+'").IPAddress}}',name]).strip()
        # Finalize transport SAN before fetching Pebble's ephemeral issuer root;
        # restarting only this new container intentionally rotates its issuer.
        self.sign_server(bridge);self.run(['docker','restart',name])
        data={'name':name,'network':network,'bridgeIp':bridge,'nodeHost':node_host,'nodeAddress':str(address),
              'httpsPort':https_port,'managementPort':management_port,'directory':'https://pebble.pni.test:14000/dir',
              'transportCa':str(self.root/'transport-ca.crt'),'issuerRoot':str(self.root/'issuer-root.crt'),
              'image':IMAGE,'realHttp01':True,'authorizationReuse':False,'validitySeconds':7776000,'sources':SOURCES}
        private_write(self.path,json.dumps(data,indent=2)+'\n')
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            try:
                directory=json.loads(self.get('/dir'));require('newOrder' in directory,'ACME directory schema')
                root=self.get('/roots/0',management=True);require(root.startswith(b'-----BEGIN CERTIFICATE-----'),'issuer root response')
                private_write(self.root/'issuer-root.crt',root)
                print('PASS strict TLS directory and generated issuer root retrieved')
                print('FIXTURE='+str(self.path));print('PEBBLE_BRIDGE_IP='+bridge);return data
            except (OSError,urllib.error.URLError,ValueError):time.sleep(1)
        raise Failure('Pebble did not become ready; private fixture retained')

    def probe(self,pull=False):
        """Issue and renew with pinned Certbot and actual Nginx HTTP-01."""
        p=self;f=self.data()
        r=p.root/('probe-'+secrets.token_hex(6));r.mkdir(mode=0o700,exist_ok=True)
        for name in ['conf','work','logs','webroot']:(r/name).mkdir(mode=0o755 if name=='webroot' else 0o700,exist_ok=True)
        (r/'webroot').chmod(0o755)
        (r/'ca.pem').write_bytes(Path('/etc/ssl/certs/ca-certificates.crt').read_bytes()+Path(f['transportCa']).read_bytes()+Path(f['issuerRoot']).read_bytes())
        (r/'nginx.conf').write_text('user nginx;\nworker_processes 1;\npid /tmp/nginx.pid;\nerror_log /dev/stderr warn;\nevents {}\nhttp { log_format pni "$request_method $status"; access_log /dev/stdout pni; server { listen 80; server_name probe.node.pni.test; location ^~ /.well-known/acme-challenge/ { root /var/www/acme; default_type text/plain; } location / { return 404; } } }\n')
        certbot='certbot/certbot:v5.10.0@sha256:c5698da859429ccee0fcc299a8000368198222d1f9e789ab6e388b491e8ce06d'
        nginx='pni-acme-web-'+secrets.token_hex(6);image='nginx:1.30.6-alpine@sha256:901e593c95dc85f5a729f5765516321366ef4ac401821431d408897e95287d0a'
        cmd=['docker','run','-d','--name',nginx,'--label','io.polaris.acme-probe='+f['name'],'--network',f['network'],'--network-alias','probe.node.pni.test','--read-only','--tmpfs','/var/cache/nginx','--tmpfs','/var/run','--tmpfs','/tmp','--cap-drop','ALL']
        for cap in ['NET_BIND_SERVICE','SETUID','SETGID','CHOWN','DAC_OVERRIDE']:cmd+=['--cap-add',cap]
        cmd+=['--mount','type=bind,src='+str(r/'nginx.conf')+',dst=/etc/nginx/nginx.conf,readonly','--mount','type=bind,src='+str(r/'webroot')+',dst=/var/www/acme,readonly',image]
        if pull:
            p.run(['docker','pull',image],timeout=600)
            p.run(['docker','pull',certbot],timeout=600)
        p.run(cmd)
        cmd=['docker','run','--rm','--network',f['network'],'--read-only','--tmpfs','/tmp:rw,nosuid,size=64m','--cap-drop','ALL','--security-opt','no-new-privileges:true','--user',str(os.getuid())+':'+str(os.getgid())]
        for src,dst in [(r/'conf','/etc/letsencrypt'),(r/'work','/var/lib/letsencrypt'),(r/'logs','/var/log/letsencrypt'),(r/'webroot','/var/www/acme')]:cmd+=['--mount','type=bind,src='+str(src)+',dst='+dst]
        cmd+=['--mount','type=bind,src='+str(r/'ca.pem')+',dst=/run/host-ca.pem,readonly','-e','REQUESTS_CA_BUNDLE=/run/host-ca.pem','-e','NO_PROXY=*','-e','no_proxy=*',certbot]
        def calls():return p.run(['docker','logs',nginx]).count('GET 200')
        try:
         p.run(cmd+['certonly','--webroot','-w','/var/www/acme','--server',f['directory'],'--cert-name','pni-probe','-d','probe.node.pni.test','--agree-tos','--non-interactive','--register-unsafely-without-email'],timeout=300)
         cert=r/'conf/live/pni-probe/fullchain.pem';serial1=p.run(['openssl','x509','-in',str(cert),'-noout','-serial']).strip();initial=calls();require(initial>0,'real HTTP-01 validation was not observed')
         p.run(['openssl','verify','-CAfile',str(r/'ca.pem'),'-untrusted',str(cert),'-verify_hostname','probe.node.pni.test',str(cert)])
         p.run(['openssl','x509','-in',str(cert),'-noout','-checkend','86400']);print('PASS real Certbot5.10.0 HTTP01 issued90daycertificate viaNginxwebroot withstrictCAtrust',flush=True)
         p.run(cmd+['renew','--cert-name','pni-probe','--non-interactive','--no-random-sleep-on-renew','--force-renewal'],timeout=300)
         serial2=p.run(['openssl','x509','-in',str(cert),'-noout','-serial']).strip();renewed=calls();require(serial1!=serial2 and renewed>initial,'renewal must change serial and perform fresh HTTP-01 validation')
         print('PASS real forcedrenewal changedserial andcausednewHTTP01GET200 validation',flush=True)
         report={'success':True,'client':certbot,'server':IMAGE,'issue':'PASS','renew':'PASS','strictTls':True,'realHttp01':True,'initialHttp200Requests':initial,'afterRenewalHttp200Requests':renewed,'validBeyond24h':True,'scope':'Independent Docker bridge protocol fixture; Ubuntu System.acme test remains separate.'};(p.root/'bridge-probe-evidence.json').write_text(json.dumps(report,indent=2)+'\n')
        finally:
         private_write(r/'nginx-debug.log',p.run(['docker','logs',nginx]))
         p.run(['docker','rm','-f',nginx])

    def stop(self):
        data=self.data();name=data['name']
        require(re.fullmatch(r'pni-pebble-[0-9a-f]{12}',name),'invalid owned fixture identity')
        label=self.run(['docker','inspect','--format','{{index .Config.Labels "io.polaris.acme"}}',name]).strip()
        require(label==name,'container ownership label mismatch')
        self.run(['docker','rm','-f',name]);self.path.unlink()
        print('PASS only owned Pebble container removed; private PKI retained')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','status','probe','stop'])
    p.add_argument('--work-dir',type=Path,default=Path(tempfile.gettempdir())/'pni-acme-lab');p.add_argument('--network',default='pni-lab')
    p.add_argument('--node-host',default='jammy.node.pni.test');p.add_argument('--node-address')
    p.add_argument('--https-port',type=int,default=31400);p.add_argument('--management-port',type=int,default=31500);p.add_argument('--pull',action='store_true')
    args=p.parse_args();lab=Pebble(args.work_dir)
    if args.action=='start':
        require(bool(args.node_address),'--node-address is required')
        lab.start(args.network,args.node_host,args.node_address,args.https_port,args.management_port,args.pull)
    elif args.action=='probe':lab.probe(args.pull)
    elif args.action=='stop':lab.stop()
    else:
        directory=json.loads(lab.get('/dir'));print(json.dumps({'ready':'newOrder' in directory,'image':lab.data()['image'],'realHttp01':True}))

if __name__=='__main__':main()
