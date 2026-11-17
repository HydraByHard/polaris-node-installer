"""Project-owned, self-contained Docker/HTTPS support for synthetic API tests.

Adapted from the repository's original disposable Remnawave integration lab.
See provenance.json. No production endpoint or credentials are accepted.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

TEMPLATES = Path(__file__).resolve().with_name('remna-templates')


def local_env():
    # Compose variables must come from this lab's private .env, never from an
    # invoking checkout, Docker context, credentials or proxy environment.
    allowed = ('PATH','HOME','USER','LOGNAME','LANG','LC_ALL','TMPDIR')
    return {key:os.environ[key] for key in allowed if key in os.environ}


class LabFailure(RuntimeError):
    pass


def require(condition, name):
    if not condition:
        raise LabFailure(name)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LabFailure('local lab HTTP redirects are forbidden')


class Lab:
    def __init__(self, port, pull=False, work_root=None):
        self.project = 'polaris-remna-' + secrets.token_hex(6)
        self.work = Path(tempfile.mkdtemp(prefix=self.project+'-',dir=work_root))
        self.work.chmod(0o700)
        self.port, self.origin = port, f'https://localhost:{port}'
        self.token, self.passed, self.started, self.pull = None, [], False, pull

    def run(self, args, timeout=240):
        if args[0] == 'docker':
            args = ['docker','--host','unix:///var/run/docker.sock',*args[1:]]
        try:
            result = subprocess.run(args,cwd=self.work,capture_output=True,timeout=timeout,
                                    text=True,check=False,env=local_env())
        except (subprocess.TimeoutExpired,OSError):
            raise LabFailure('command timed out or unavailable: '+args[0]) from None
        if result.returncode:
            path = self.work/'command-failure.log'
            fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as stream:
                stream.write(result.stdout+result.stderr)
            raise LabFailure('command failed: '+args[0]+' (private output withheld)')
        return result.stdout

    def compose(self,*args,timeout=240):
        return self.run(['docker','compose','--project-name',self.project,
                         '--file',str(self.work/'compose.yaml'),*args],timeout)

    def env_file(self,name,values):
        path = self.work/name
        fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as stream:
            stream.write(''.join(f'{key}={value}\n' for key,value in values.items()))
        path.chmod(0o600)

    def make_opener(self,cafile):
        self.context = ssl.create_default_context(cafile=str(cafile))
        # These requests are exclusively to this lab's loopback HTTPS gateway.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),
                                                  urllib.request.HTTPSHandler(context=self.context))

    def prepare(self):
        for name in ('compose.yaml','nginx.conf'):
            shutil.copyfile(TEMPLATES/name,self.work/name)
        self.pins = json.loads((TEMPLATES/'pins.json').read_text())
        require(set(self.pins)=={'backend','node','subscription','postgres','valkey','nginx'},'exactly six lab images required')
        for image in self.pins.values():
            require('@sha256:' in image,'all images digest pinned')
            if self.pull:
                self.run(['docker','pull',image],timeout=600)
            self.run(['docker','image','inspect',image],timeout=30)
        password = secrets.token_hex(24)
        self.env_file('.env',{**{key.upper()+'_IMAGE':value for key,value in self.pins.items()},
                              'DB_PASSWORD':password,'HTTPS_PORT':self.port})
        self.env_file('backend.env',{
            'APP_PORT':3000,'METRICS_PORT':3001,'API_INSTANCES':1,
            'DATABASE_URL':f'postgresql://lab:{password}@database:5432/lab',
            'REDIS_SOCKET':'/var/run/valkey/valkey.sock','APP_SECRET':secrets.token_hex(64),
            'PANEL_DOMAIN':f'localhost:{self.port}','FRONT_END_DOMAIN':self.origin,
            'SUB_PUBLIC_DOMAIN':f'localhost:{self.port}/sub','SERVICE_SNI_VERIFICATION':'true',
            'METRICS_USER':'lab','METRICS_PASS':secrets.token_hex(24),
            'IS_TELEGRAM_NOTIFICATIONS_ENABLED':'false','WEBHOOK_ENABLED':'false'})
        self.env_file('node.env',{'NODE_PORT':2222,'SNI_VERIFICATION':'true','SECRET_KEY':'not-started'})
        self.env_file('subscription.env',{'REMNAWAVE_API_TOKEN':'not-started'})
        tls = self.work/'tls';tls.mkdir(mode=0o700)
        self.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','2',
                  '-subj','/CN=Polaris disposable lab CA','-keyout','tls/ca.key','-out','tls/ca.crt',
                  '-addext','basicConstraints=critical,CA:TRUE'])
        self.run(['openssl','req','-newkey','rsa:2048','-nodes','-subj','/CN=localhost',
                  '-keyout','tls/server.key','-out','tls/server.csr'])
        (tls/'extensions').write_text('subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n')
        self.run(['openssl','x509','-req','-days','2','-in','tls/server.csr','-CA','tls/ca.crt',
                  '-CAkey','tls/ca.key','-CAcreateserial','-extfile','tls/extensions','-out','tls/server.crt'])
        self.make_opener(tls/'ca.crt')

    def http(self,path,method='GET',data=None,authenticated=True,headers=None):
        headers = {'User-Agent':'Polaris-synthetic-API-lab/1.0',**(headers or {})}
        if authenticated and self.token:
            headers['Authorization'] = 'Bearer '+self.token
            headers['X-Remnawave-Client-Type'] = 'browser'
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.origin+path,method=method,headers=headers,
                                         data=None if data is None else json.dumps(data).encode())
        try:
            with self.opener.open(request,timeout=8) as response:
                return response.status,response.headers,response.read()
        except urllib.error.HTTPError as response:
            return response.code,response.headers,response.read()

    def api(self,path,method='GET',data=None,authenticated=True):
        status,_,body = self.http('/api/'+path,method,data,authenticated)
        require(200<=status<300,f'API {method} {path.split("/")[0]} status {status}')
        try:
            return json.loads(body)['response']
        except (ValueError,KeyError,TypeError):
            raise LabFailure('API JSON response schema') from None

    def wait(self,predicate,name,seconds=120):
        deadline = time.monotonic()+seconds
        while time.monotonic()<deadline:
            try:
                if predicate():
                    self.ok(name)
                    return
            except (OSError,urllib.error.URLError,LabFailure):
                pass
            time.sleep(2)
        raise LabFailure(name+' timed out')

    def ok(self,name):
        self.passed.append(name)
        print('PASS '+name,flush=True)

    def cleanup(self):
        if self.started:
            self.compose('down','--volumes','--remove-orphans',timeout=90)
            for kind in ('container','volume','network'):
                command = ['docker','ps','-aq'] if kind=='container' else ['docker',kind,'ls','-q']
                found = self.run([*command,'--filter','label=com.docker.compose.project='+self.project])
                require(not found.strip(),'own lab '+kind+' cleanup')
        shutil.rmtree(self.work)
