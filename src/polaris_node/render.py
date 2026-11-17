"""Pure, digest-pinned configurations. No filesystem or network side effects."""
from .core import PINS

PRIVATE=['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/4','240.0.0.0/4','::/128','::1/128','fc00::/7','fe80::/10','ff00::/8']
def tag(identity):return 'PNI_'+identity[:16].upper()
def transport_path(identity):return '/polaris-'+identity[:16]+'/'
def xray_config(c,identity):
    return {'log':{'loglevel':'warning'},'inbounds':[{'tag':tag(identity),'listen':'127.0.0.1','port':c['xray_port'],'protocol':'vless','settings':{'clients':[],'decryption':'none'},'streamSettings':{'network':'xhttp','security':'none','xhttpSettings':{'host':c['domain'],'path':transport_path(identity),'mode':'packet-up','scMaxEachPostBytes':1000000}}}],'outbounds':[{'tag':'DIRECT','protocol':'freedom'},{'tag':'BLOCK','protocol':'blackhole'}],'routing':{'domainStrategy':'IPOnDemand','rules':[{'type':'field','inboundTag':[tag(identity)],'ip':PRIVATE,'outboundTag':'BLOCK'}]}}
def nginx_config(c,identity,tls):
    http=f'''server {{
 listen {c['http_port']} default_server;
 server_name {c['domain']};
 location ^~ /.well-known/acme-challenge/ {{ root /var/www/acme; default_type text/plain; }}
 location / {{ return 404; }}
}}'''
    servers=[http]
    if c.get('public_ipv6'):http=http.replace(f"listen {c['http_port']} default_server;",f"listen {c['http_port']} default_server;\n listen [::]:{c['http_port']} default_server;");servers=[http]
    if tls:
        ipv6=f"listen [::]:{c['vpn_port']} ssl;"if c.get('public_ipv6')else''
        servers.append(f'''server {{
 listen {c['vpn_port']} ssl;
 {ipv6}
 http2 on;
 server_name {c['domain']};
 ssl_protocols TLSv1.2 TLSv1.3;
 ssl_certificate /etc/polaris-tls/live/fullchain.pem;
 ssl_certificate_key /etc/polaris-tls/live/privkey.pem;
 location ^~ {transport_path(identity)} {{
  client_max_body_size 2m;
  proxy_pass http://127.0.0.1:{c['xray_port']};
  proxy_http_version 1.1;
  proxy_set_header Host {c['domain']};
  proxy_set_header Connection "";
  proxy_buffering off; proxy_request_buffering off; proxy_cache off;
  proxy_read_timeout 3600s; proxy_send_timeout 3600s;
  add_header Cache-Control no-store always;
 }}
 location / {{ return 404; }}
}}''')
    return 'user nginx;\nworker_processes 1;\npid /var/run/nginx.pid;\nerror_log /dev/stderr warn;\nevents { worker_connections 1024; }\nhttp {\n access_log off;\n server_tokens off;\n'+ '\n'.join(servers)+'\n}\n'
def compose_config(c,identity,tls):
    base='/opt/polaris-node';logging={'driver':'json-file','options':{'max-size':'10m','max-file':'3'}}
    node={'image':PINS['images']['node'],'container_name':'polaris-node-'+identity[:12],'network_mode':'host','restart':'on-failure:5','env_file':['node.env'],'mem_limit':'512m','pids_limit':256,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'ulimits':{'nofile':{'soft':131072,'hard':131072}},'logging':logging,'labels':{'io.polaris.install':identity}}
    gateway={'image':PINS['images']['nginx'],'container_name':'polaris-gateway-'+identity[:12],'network_mode':'host','restart':'on-failure:5','read_only':True,'tmpfs':['/var/cache/nginx','/var/run','/tmp'],'cap_drop':['ALL'],'cap_add':['NET_BIND_SERVICE','SETUID','SETGID','CHOWN','DAC_OVERRIDE'],'security_opt':['no-new-privileges:true'],'mem_limit':'64m','pids_limit':64,'command':['nginx','-c','/etc/polaris/nginx.conf','-g','daemon off;'],'volumes':[base+'/nginx:/etc/polaris:ro','/var/lib/polaris-node/acme:/var/www/acme:ro'],'logging':logging,'labels':{'io.polaris.install':identity}}
    if tls:gateway['volumes'] += [base+'/tls:/etc/polaris-tls:ro']
    return {'name':'polaris-'+identity[:12],'services':{'node':node,'gateway':gateway}}
def chain_name(identity):return 'PNI_'+identity[:12].upper()
def firewall_rules(c,identity,family):
    name=chain_name(identity);lines=['*filter',':'+name+' - [0:0]','-F '+name,'-A '+name+' -i lo -j ACCEPT']
    for source in c['panel_ipv4'if family==4 else'panel_ipv6']:
        lines.append(f"-A {name} -s {source}/{'32'if family==4 else'128'} -p tcp --dport {c['api_port']} -j ACCEPT")
    lines += [f"-A {name} -p tcp -m multiport --dports {c['api_port']},{c['xray_port']} -j DROP",f"-A {name} -p tcp -m multiport --dports {c['http_port']},{c['vpn_port']} -j ACCEPT",'-A '+name+' -j RETURN','COMMIT','']
    return '\n'.join(lines)
def units(c,identity):
    marker='# Owned by Polaris Node Installer '+identity+'\n'
    return {'polaris-node-firewall.service':marker+'''[Unit]
Description=Polaris Node scoped API firewall
DefaultDependencies=no
After=local-fs.target systemd-modules-load.service systemd-tmpfiles-setup.service
Before=network-pre.target docker.service polaris-node.service shutdown.target
Wants=network-pre.target
Conflicts=shutdown.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/polaris-node _firewall
ExecReload=/usr/local/bin/polaris-node _firewall
[Install]
WantedBy=multi-user.target
''','polaris-node.service':marker+'''[Unit]
Description=Polaris owned Node and HTTPS gateway
Requires=docker.service polaris-node-firewall.service
After=docker.service polaris-node-firewall.service network-online.target
Wants=network-online.target
PartOf=docker.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/polaris-node _start
ExecStop=/usr/local/bin/polaris-node _stop
TimeoutStartSec=240
TimeoutStopSec=60
[Install]
WantedBy=multi-user.target docker.service
''','polaris-node-renew.service':marker+'''[Unit]
Description=Renew only Polaris Node TLS certificate
After=docker.service polaris-node.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/polaris-node _renew
UMask=0077
TimeoutStartSec=300
''','polaris-node-renew.timer':marker+'''[Unit]
Description=Polaris Node TLS renewal
[Timer]
OnCalendar=*-*-* 03,15:20:00 UTC
RandomizedDelaySec=600
Persistent=true
[Install]
WantedBy=timers.target
'''}
