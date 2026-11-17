"""Own-resource enrollment and separately confirmed publication."""
import re
from typing import Callable

from .core import PolarisError
from .render import xray_config

_UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def _ids(items):
    if not isinstance(items,list):
        raise PolarisError('Panel returned an invalid resource association.')
    values = [item.get('uuid') if isinstance(item,dict) else item for item in items]
    if any(not isinstance(value,str) or not _UUID.fullmatch(value) for value in values):
        raise PolarisError('Panel returned an invalid resource UUID.')
    return values


class Registrar:
    def __init__(self, api, state: dict, save: Callable[[],None]):
        install_id = state.get('install_id','')
        if not isinstance(install_id,str) or not re.fullmatch('[0-9a-f]{32}',install_id):
            raise PolarisError('Installation identity is invalid.')
        self.api, self.state, self.save = api, state, save
        self.config = state['config']
        self.resources = state.setdefault('resources',{})
        self.install_id = install_id
        self.profile_name = 'PNI '+install_id[:20]
        self.node_name = self.config['name'][:16]+'-'+install_id[:6]
        self.inbound_tag = 'PNI_'+install_id[:16].upper()
        self.marker = 'PNI_'+install_id[:16].upper()
        self.note = 'polaris-node-installer:'+install_id
        self.remark = self.config['name']+' [PNI:'+install_id[:12]+']'
        self.path = '/polaris-'+install_id[:16]+'/'
        self.host_visibility = None

    def _checkpoint(self, **values):
        self.resources.update(values)
        self.save()

    def _collection(self, resource):
        result = self.api.request('GET','/'+resource)
        if resource == 'config-profiles':
            result = result.get('configProfiles') if isinstance(result,dict) else None
        elif resource == 'internal-squads':
            result = result.get('internalSquads') if isinstance(result,dict) else None
        if not isinstance(result,list) or any(not isinstance(item,dict) for item in result):
            raise PolarisError('Panel resource list has an unexpected schema.')
        return result

    def _select(self, items, resource_key, matches):
        known = self.resources.get(resource_key)
        candidates = [item for item in items if item.get('uuid') == known or matches(item)]
        if len(candidates) > 1:
            raise PolarisError('Multiple matching remote resources found; resolve the ownership collision in the panel.')
        if not candidates:
            if known:
                raise PolarisError('A recorded remote resource is missing; manual recovery is required.')
            return None
        selected = candidates[0]
        if known and selected.get('uuid') != known:
            raise PolarisError('Remote identity differs from the recorded owned resource.')
        if not isinstance(selected.get('uuid'),str) or not _UUID.fullmatch(selected['uuid']):
            raise PolarisError('Panel returned an invalid resource UUID.')
        return selected

    def _identity(self, item, key):
        value = item.get('uuid') if isinstance(item,dict) else None
        if not isinstance(value,str) or not _UUID.fullmatch(value) or self.resources.get(key,value) != value:
            raise PolarisError('Panel resource UUID differs from the recorded installation identity.')

    def _profile(self, profile):
        self._identity(profile,'profile_id')
        if self.resources.get('node_id') and set(_ids(profile.get('nodes',[]))) - {self.resources['node_id']}:
            raise PolarisError('Owned profile is referenced by another Node; review the ownership conflict in the panel.')
        expected = xray_config(self.config,self.install_id)
        if profile.get('name') != self.profile_name or profile.get('config') != expected:
            raise PolarisError('Config Profile ownership or configuration differs; existing profiles are never overwritten.')
        inbounds = profile.get('inbounds')
        if not isinstance(inbounds,list) or len(inbounds) != 1 or inbounds[0].get('tag') != self.inbound_tag:
            raise PolarisError('Owned Config Profile inbound does not match this installation.')
        inbound_id = _ids(inbounds)[0]
        if self.resources.get('inbound_id',inbound_id) != inbound_id:
            raise PolarisError('Recorded inbound UUID differs from the owned profile.')
        return inbound_id

    def _node(self, node):
        self._identity(node,'node_id')
        active = node.get('configProfile',{})
        wanted = (node.get('name') == self.node_name and node.get('note') == self.note
                  and self.marker in node.get('tags',[])
                  and node.get('address') == self.config.get('management_address',self.config['domain'])
                  and node.get('port') == self.config.get('api_port',2222)
                  and active.get('activeConfigProfileUuid') == self.resources.get('profile_id')
                  and _ids(active.get('activeInbounds')) == [self.resources.get('inbound_id')])
        if not wanted:
            raise PolarisError('Node ownership, address or Config Profile differs; existing Nodes are never modified.')
        return node

    def _host(self, host, *, allow_enabled=False, inspect_visibility=False):
        self._identity(host,'host_id')
        expected = {'remark':self.remark,'address':self.config['domain'],
                    'port':self.config.get('vpn_port',443),'path':self.path,
                    'sni':self.config['domain'],'host':self.config['domain'],'alpn':'h2',
                    'securityLayer':'TLS','nodes':[self.resources.get('node_id')],
                    'inbound':{'configProfileUuid':self.resources.get('profile_id'),
                               'configProfileInboundUuid':self.resources.get('inbound_id')},
                    'xhttpExtraParams':{'mode':'packet-up'}}
        if any(host.get(key) != value for key,value in expected.items()) or self.marker not in host.get('tags',[]):
            raise PolarisError('Host ownership or transport differs; existing Hosts are never modified during installation.')
        if not all(isinstance(host.get(key),bool) for key in ('isDisabled','isHidden')):
            raise PolarisError('Panel returned invalid Host visibility flags.')
        if (not inspect_visibility and not self.state.get('published') and (host.get('isDisabled') is not True or host.get('isHidden') is not True)
                and not (allow_enabled and host.get('isDisabled') is False and host.get('isHidden') is False)):
            raise PolarisError('Owned Host is unexpectedly enabled or visible; review it in the panel before continuing.')
        self.host_visibility = {key:host[key] for key in ('isDisabled','isHidden')}
        return host

    def visibility(self):
        host_id = self.resources.get('host_id')
        if not isinstance(host_id,str) or not _UUID.fullmatch(host_id):
            raise PolarisError('No recorded owned Host is available for visibility checks.')
        if getattr(self.api,'purpose',None)=='install':
            host = self._select(self._collection('hosts'),'host_id',lambda h:h.get('remark')==self.remark or self.marker in h.get('tags',[]))
            if host is None:
                raise PolarisError('Owned Host is missing.')
        else:
            host = self.api.request('GET','/hosts/'+host_id)
        self._host(host,inspect_visibility=True)
        return dict(self.host_visibility)

    def ensure(self):
        """Read before each create. A failed POST is reconciled on the next run."""
        self.api.metadata()
        profiles = self._collection('config-profiles')
        profile = self._select(profiles,'profile_id',lambda p:p.get('name') == self.profile_name)
        if profile is None:
            profile = self.api.request('POST','/config-profiles',{'name':self.profile_name,
                                                               'config':xray_config(self.config,self.install_id)})
        inbound_id = self._profile(profile)
        self._checkpoint(profile_id=profile['uuid'],inbound_id=inbound_id)
        nodes = self._collection('nodes')
        address = self.config.get('management_address',self.config['domain'])
        node = self._select(nodes,'node_id',lambda n:n.get('name') == self.node_name
                            or n.get('note') == self.note or self.marker in n.get('tags',[])
                            or (n.get('address') == address and n.get('port') == self.config.get('api_port',2222)))
        referenced = set(_ids(profile.get('nodes',[])))
        if referenced and (node is None or referenced - {node['uuid']}):
            raise PolarisError('Owned profile has a foreign Node reference; no new Node was created.')
        if node is None:
            node = self.api.request('POST','/nodes',{'name':self.node_name,'address':address,
                'port':self.config.get('api_port',2222),'countryCode':self.config.get('country','XX'),
                'note':self.note,'tags':[self.marker],
                'configProfile':{'activeConfigProfileUuid':profile['uuid'],'activeInbounds':[inbound_id]}})
        self._node(node)
        self._checkpoint(node_id=node['uuid'])
        hosts = self._collection('hosts')
        host = self._select(hosts,'host_id',lambda h:h.get('remark') == self.remark
                            or self.marker in h.get('tags',[]) or h.get('address') == self.config['domain'])
        if host is None:
            host = self.api.request('POST','/hosts',{'remark':self.remark,'address':self.config['domain'],
                'port':self.config.get('vpn_port',443),'path':self.path,'sni':self.config['domain'],
                'host':self.config['domain'],'alpn':'h2','securityLayer':'TLS',
                'isDisabled':True,'isHidden':True,'tags':[self.marker],'nodes':[node['uuid']],
                'inbound':{'configProfileUuid':profile['uuid'],'configProfileInboundUuid':inbound_id},
                'xhttpExtraParams':{'mode':'packet-up'}})
        self._host(host)
        self._checkpoint(host_id=host['uuid'])
        return dict(self.resources)

    def online(self):
        node_id = self.resources.get('node_id')
        if not isinstance(node_id,str) or not _UUID.fullmatch(node_id):
            raise PolarisError('No recorded Node is available for diagnosis.')
        return self._node(self.api.request('GET','/nodes/'+node_id))

    def _recorded_resources(self, *, allow_enabled=False, inspect_visibility=False):
        for key in ('profile_id','inbound_id','node_id','host_id'):
            if not isinstance(self.resources.get(key),str) or not _UUID.fullmatch(self.resources[key]):
                raise PolarisError('Complete owned resource IDs are required for this operation.')
        profile = self.api.request('GET','/config-profiles/'+self.resources['profile_id'])
        self._profile(profile)
        self.online()
        return self._host(self.api.request('GET','/hosts/'+self.resources['host_id']),allow_enabled=allow_enabled,inspect_visibility=inspect_visibility)

    def _publication_intent(self, squad):
        intent = self.state.get('publication_intent')
        if intent is None:
            return None
        expected = {key:self.resources.get(key) for key in ('profile_id','inbound_id','node_id','host_id')}
        if (not isinstance(intent,dict) or intent.get('schema') != 1
                or intent.get('install_id') != self.install_id or intent.get('resources') != expected
                or intent.get('squad_name') != squad or intent.get('phase') not in ('prepared','host_pending')
                or not isinstance(intent.get('squad_id'),str) or not _UUID.fullmatch(intent['squad_id'])):
            raise PolarisError('Publication journal does not match this installation and Squad; review it before continuing.')
        _ids(intent.get('original_inbound_ids'))
        return intent

    def _save_intent(self, intent):
        previous = self.state.get('publication_intent')
        self.state['publication_intent'] = intent
        try:
            self.save()
        except Exception:
            if previous is None:
                self.state.pop('publication_intent',None)
            else:
                self.state['publication_intent'] = previous
            raise

    def publish(self, squad='Polaris personal', *, confirmed=False):
        if self.state.get('unpublication_intent'):
            raise PolarisError('Complete the interrupted unpublication before publishing again.')
        if confirmed is not True or getattr(self.api,'purpose',None) != 'publish':
            raise PolarisError('Publishing requires explicit owner confirmation and a separate publication token.')
        self.api.metadata()
        intent = self._publication_intent(squad)
        recovering = bool(intent and intent['phase'] == 'host_pending')
        # Enrollment always calls _host with its strict default. Only this
        # explicitly confirmed operation may inspect an enabled Host covered by
        # a matching journal saved before the previous Host PATCH.
        host = self._recorded_resources(allow_enabled=recovering)
        squads = [item for item in self._collection('internal-squads') if item.get('name') == squad]
        if len(squads) != 1:
            raise PolarisError('The named Internal Squad is missing or ambiguous; no publication changes were made.')
        squad_id = squads[0]['uuid']
        if intent and intent['squad_id'] != squad_id:
            raise PolarisError('Publication journal refers to a different Squad; no changes were made.')
        first = self.api.request('GET','/internal-squads/'+squad_id)
        original = _ids(first.get('inbounds'))
        second = self.api.request('GET','/internal-squads/'+squad_id)
        if second.get('name') != squad or _ids(second.get('inbounds')) != original:
            raise PolarisError('Internal Squad changed concurrently; retry publication in a quiet maintenance window.')
        inbound_id = self.resources['inbound_id']
        if intent and set(intent['original_inbound_ids']) - set(original):
            raise PolarisError('Squad permissions changed since publication began; review them before continuing.')
        already_enabled = host.get('isDisabled') is False and host.get('isHidden') is False
        if recovering and already_enabled and inbound_id not in original:
            raise PolarisError('Enabled Host lacks its journaled Squad inbound; review it before continuing.')
        needs_squad_patch = inbound_id not in original
        needs_host_patch = not already_enabled
        if needs_squad_patch or needs_host_patch:
            if intent is None:
                intent = {'schema':1,'install_id':self.install_id,
                          'resources':{key:self.resources[key] for key in ('profile_id','inbound_id','node_id','host_id')},
                          'squad_id':squad_id,'squad_name':squad,'original_inbound_ids':original,'phase':'prepared'}
                self._save_intent(intent)
            if needs_squad_patch:
                merged = list(dict.fromkeys(original+[inbound_id]))
                updated = self.api.request('PATCH','/internal-squads',{'uuid':squad_id,'inbounds':merged})
                if set(_ids(updated.get('inbounds'))) != set(merged):
                    raise PolarisError('Panel did not retain the complete Squad inbound list; Host remains unpublished.')
            if needs_host_patch:
                intent = {**intent,'phase':'host_pending'}
                self._save_intent(intent)
                updated = self.api.request('PATCH','/hosts',{'uuid':self.resources['host_id'],
                                                           'isDisabled':False,'isHidden':False})
                if updated.get('isDisabled') is not False or updated.get('isHidden') is not False:
                    raise PolarisError('Panel did not confirm Host publication; rerun the confirmed publication command to reconcile it.')
                self._host(updated,allow_enabled=True)
        previous_record = self.state.get('publication_record')
        if intent:
            self.state['publication_record'] = {**intent,'added_inbound':inbound_id not in intent['original_inbound_ids']}
        previous_published = self.state.get('published',False)
        previous_intent = self.state.pop('publication_intent',None)
        self.state['published'] = True
        try:
            self.save()
        except Exception:
            self.state['published'] = previous_published
            if previous_record is None:
                self.state.pop('publication_record',None)
            else:
                self.state['publication_record'] = previous_record
            if previous_intent is not None:
                self.state['publication_intent'] = previous_intent
            raise
        return dict(self.resources)

    def _bound_journal(self, value):
        expected = {key:self.resources.get(key) for key in ('profile_id','inbound_id','node_id','host_id')}
        if (not isinstance(value,dict) or value.get('schema')!=1
                or value.get('install_id')!=self.install_id or value.get('resources')!=expected):
            raise PolarisError('Visibility journal does not match this installation.')
        return value

    def _unpublication_cleanup(self):
        proof = self.state.get('publication_intent') or self.state.get('publication_record')
        if not proof:
            return None
        self._bound_journal(proof)
        original = _ids(proof.get('original_inbound_ids'))
        squad_id = proof.get('squad_id')
        if not isinstance(squad_id,str) or not _UUID.fullmatch(squad_id) or not isinstance(proof.get('squad_name'),str):
            raise PolarisError('Publication proof contains an invalid Squad identity.')
        if self.resources['inbound_id'] not in original:
            return {'squad_id':squad_id,'squad_name':proof['squad_name']}
        return None

    def unpublish(self, *, confirmed=False):
        if confirmed is not True or getattr(self.api,'purpose',None)!='publish':
            raise PolarisError('Unpublishing requires explicit owner confirmation and a separate publication token.')
        self.api.metadata()
        host = self._recorded_resources(inspect_visibility=True)
        expected_cleanup = self._unpublication_cleanup()
        intent = self.state.get('unpublication_intent')
        if intent is not None:
            self._bound_journal(intent)
            if intent.get('cleanup')!=expected_cleanup:
                raise PolarisError('Unpublication journal does not match the prior proven publication Squad.')
        else:
            intent = {'schema':1,'install_id':self.install_id,
                      'resources':{key:self.resources[key] for key in ('profile_id','inbound_id','node_id','host_id')},
                      'cleanup':expected_cleanup}
            self.state['unpublication_intent'] = intent
            try:
                self.save()
            except Exception:
                self.state.pop('unpublication_intent',None)
                raise
        if host.get('isDisabled') is not True or host.get('isHidden') is not True:
            hidden = self.api.request('PATCH','/hosts',{'uuid':self.resources['host_id'],'isDisabled':True,'isHidden':True})
            self._host(hidden,inspect_visibility=True)
            if hidden['isDisabled'] is not True or hidden['isHidden'] is not True:
                raise PolarisError('Panel did not confirm reduced Host visibility; rerun confirmed unpublication.')
        cleanup = intent.get('cleanup')
        if cleanup:
            squad_id = cleanup.get('squad_id')
            if not isinstance(squad_id,str) or not _UUID.fullmatch(squad_id):
                raise PolarisError('Unpublication journal contains an invalid Squad UUID.')
            first = self.api.request('GET','/internal-squads/'+squad_id)
            original = _ids(first.get('inbounds'))
            second = self.api.request('GET','/internal-squads/'+squad_id)
            if (first.get('uuid')!=squad_id or second.get('uuid')!=squad_id
                    or first.get('name')!=cleanup.get('squad_name') or second.get('name')!=cleanup.get('squad_name')
                    or _ids(second.get('inbounds'))!=original):
                raise PolarisError('Internal Squad changed concurrently; Host is hidden; retry unpublication in a quiet maintenance window.')
            inbound_id = self.resources['inbound_id']
            if inbound_id in original:
                retained = [value for value in original if value!=inbound_id]
                updated = self.api.request('PATCH','/internal-squads',{'uuid':squad_id,'inbounds':retained})
                if set(_ids(updated.get('inbounds')))!=set(retained):
                    raise PolarisError('Panel did not confirm preservation of the other Squad permissions; Host remains hidden.')
        previous = {key:self.state[key] for key in ('published','publication_intent','publication_record','unpublication_intent') if key in self.state}
        self.state['published'] = False
        for key in ('publication_intent','publication_record','unpublication_intent'):
            self.state.pop(key,None)
        try:
            self.save()
        except Exception:
            self.state.update(previous)
            raise
        return dict(self.resources)
