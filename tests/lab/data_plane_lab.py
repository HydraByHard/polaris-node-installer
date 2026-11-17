#!/usr/bin/env python3
"""Dedicated synthetic subscriber and actual subscription export for a lab Node.

This helper accepts only a private disposable Remnawave fixture and .pni.test
Node state. No production API or existing user/Squad is modified.
"""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import time

spec=importlib.util.spec_from_file_location('pni_remna_fixture',Path(__file__).with_name('remna_lab.py'))
lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)


def require(ok,message):
    if not ok:raise lab.legacy.LabFailure(message)


def prepare(remna_fixture,node_state,work):
    require(not (work/'fixture.json').exists(),'data-plane fixture already exists; preserve it or clean it explicitly')
    state=json.loads(node_state.read_text());c=state['config'];resources=state['resources'];identity=state['install_id']
    require(c['domain'].endswith('.pni.test') and re.fullmatch('[a-f0-9]{32}',identity),'only synthetic owned lab Node state is accepted')
    api=lab.Fixture.attach(remna_fixture)
    profile=api.api('config-profiles/'+resources['profile_id']);node=api.api('nodes/'+resources['node_id'])
    require(profile['name']=='PNI '+identity[:20] and node.get('note')=='polaris-node-installer:'+identity,'owned Node/profile markers must match')
    require([x['uuid'] for x in node['configProfile']['activeInbounds']]==[resources['inbound_id']],'owned inbound association must match')
    suffix=secrets.token_hex(5);name='pni_data_'+suffix;marker='PNI data lab '+suffix
    meta={'marker':marker,'username':name,'domain':c['domain'],'nodeId':resources['node_id'],'profileId':resources['profile_id'],'inboundId':resources['inbound_id']}
    # Checkpoint each synthetic create so a failed test can remove only its own
    # resources, including a partial fixture. Credentials never reach stdout.
    lab.private_json(work/'fixture.json',meta)
    squad=api.api('internal-squads','POST',{'name':marker,'inbounds':[resources['inbound_id']]});meta['squadId']=squad['uuid'];lab.private_json(work/'fixture.json',meta)
    host=api.api('hosts','POST',{'remark':marker,'address':c['domain'],'port':c['vpn_port'],'path':'/polaris-'+identity[:16]+'/',
        'sni':c['domain'],'host':c['domain'],'alpn':'h2','securityLayer':'TLS','isHidden':False,'isDisabled':False,
        'nodes':[resources['node_id']],'inbound':{'configProfileUuid':resources['profile_id'],'configProfileInboundUuid':resources['inbound_id']},'xhttpExtraParams':{'mode':'packet-up'}})
    meta['hostId']=host['uuid'];lab.private_json(work/'fixture.json',meta)
    user=api.api('users','POST',{'username':name,'activeInternalSquads':[squad['uuid']],'expireAt':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)).isoformat()})
    meta['userId']=user['id'];lab.private_json(work/'fixture.json',meta)
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        status,_,raw=api.http('/sub/'+user['shortUuid']+'/json',authenticated=False)
        if status==200:
            try:
                profiles=json.loads(raw);profile=profiles[0] if isinstance(profiles,list) and len(profiles)==1 else None
                out=[o for o in profile.get('outbounds',[]) if o.get('protocol')=='vless'] if profile else []
                if len(out)==1:break
            except (ValueError,AttributeError):pass
        time.sleep(2)
    else:raise lab.legacy.LabFailure('actual subscription did not yield one dedicated VLESS profile')
    endpoint=out[0]['settings']['vnext'][0];stream=out[0]['streamSettings']
    require(endpoint['address']==c['domain'] and endpoint['port']==c['vpn_port'] and endpoint['users'][0]['id']==user['vlessUuid'],'actual subscription endpoint/credential mismatch')
    require(stream['network']=='xhttp' and stream['security']=='tls' and stream['tlsSettings']['serverName']==c['domain'] and stream['tlsSettings'].get('alpn')==['h2'] and not stream['tlsSettings'].get('allowInsecure'),'actual subscription must use trusted TLS/h2/XHTTP')
    require(stream.get('xhttpSettings',{}).get('path')=='/polaris-'+identity[:16]+'/' and stream.get('xhttpSettings',{}).get('mode')=='packet-up','actual subscription must retain the dedicated packet-up XHTTP path')
    lab.private_json(work/'client.json',profiles)
    print('PASS dedicated synthetic user/Squad/Host created; actual subscription verified')
    print('TEST_CONFIG='+str(work/'client.json'))


def cleanup(remna_fixture,work):
    api=lab.Fixture.attach(remna_fixture);meta=json.loads((work/'fixture.json').read_text())
    for resource,key in [('hosts','hostId'),('users','userId'),('internal-squads','squadId')]:
        if key not in meta:continue
        path=resource+'/'+str(meta[key]);status,_,body=api.http('/api/'+path)
        if status==404:continue
        require(status==200,'cleanup must verify the owned synthetic object first')
        value=json.loads(body)['response']
        expected=value.get('remark') if resource=='hosts' else value.get('username') if resource=='users' else value.get('name')
        require(expected==(meta['username'] if resource=='users' else meta['marker']),'refusing cleanup of an unowned lab object')
        require(api.http('/api/'+path,'DELETE')[0]==204,'own synthetic object cleanup failed')
    (work/'fixture.json').unlink();(work/'client.json').unlink(missing_ok=True)
    print('PASS only own synthetic Host/user/Squad and private client file removed')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','cleanup']);p.add_argument('--remna-fixture',type=Path,required=True);p.add_argument('--node-state',type=Path);p.add_argument('--work-dir',type=Path,required=True);args=p.parse_args()
    work=args.work_dir.resolve()
    require(not any((q/'.git').is_file() or (q/'.git/HEAD').exists() for q in (work,*work.parents)),'private subscriber credentials must stay outside Git')
    work.mkdir(mode=0o700,parents=True,exist_ok=True)
    require(work.stat().st_uid==os.geteuid() and not work.stat().st_mode&0o077,'private owned0700 data-plane directory required')
    if args.action=='prepare':
        require(args.node_state is not None,'--node-state is required');prepare(args.remna_fixture,args.node_state,work)
    else:cleanup(args.remna_fixture,work)

if __name__=='__main__':main()
