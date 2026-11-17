import copy
import unittest
import uuid


class MemoryPanel:
    """An in-memory protocol boundary; real Registrar owns all decisions."""
    purpose='install'
    def __init__(self):
        self.profiles=[];self.nodes=[];self.hosts=[];self.squads=[];self.requests=[]
        self.ambiguous=None;self.squad_reads=0;self.change_squad_on_second_read=False
    def metadata(self):return {'version':'3.4.11'}
    def request(self,method,path,data=None):
        from polaris_node.core import PolarisError
        path=path.removeprefix('/api').strip('/');self.requests.append((method,path,copy.deepcopy(data)))
        resource,_,ident=path.partition('/')
        collection={'config-profiles':self.profiles,'nodes':self.nodes,'hosts':self.hosts,'internal-squads':self.squads}[resource]
        if method=='GET':
            if ident:
                value=next(x for x in collection if x['uuid']==ident)
                if resource=='internal-squads':
                    self.squad_reads+=1
                    if self.change_squad_on_second_read and self.squad_reads==2:value['inbounds'].append({'uuid':str(uuid.uuid4())})
                return copy.deepcopy(value)
            if resource=='config-profiles':return {'total':len(collection),'configProfiles':copy.deepcopy(collection)}
            if resource=='internal-squads':return {'total':len(collection),'internalSquads':copy.deepcopy(collection)}
            return copy.deepcopy(collection)
        if method=='POST':
            value=copy.deepcopy(data);value['uuid']=str(uuid.uuid4())
            if resource=='config-profiles':
                value['inbounds']=[{'uuid':str(uuid.uuid4()),'tag':x['tag'],'profileUuid':value['uuid']} for x in data['config']['inbounds']];value['nodes']=[]
            if resource=='nodes':
                value['configProfile']['activeInbounds']=[{'uuid':x} for x in data['configProfile']['activeInbounds']]
                value.update(isConnected=True,isDisabled=False,xrayUptime=17,versions={'node':'3.4.6','xray':'26.11.9'})
            collection.append(value)
            if self.ambiguous==resource:self.ambiguous=None;raise PolarisError('POST ambiguous')
            return copy.deepcopy(value)
        if method=='PATCH':
            value=next(x for x in collection if x['uuid']==data['uuid'])
            value.update(copy.deepcopy(data))
            if resource=='internal-squads':value['inbounds']=[{'uuid':x} for x in data['inbounds']]
            return copy.deepcopy(value)
        raise AssertionError('unexpected protocol operation')


def state():
    return {'install_id':'1234567890abcdef1234567890abcdef','config':{'name':'finland-01','country':'FI','domain':'new.pni.test','management_address':'new-api.pni.test','api_port':2222,'vpn_port':443,'xray_port':8082},'resources':{},'stages':{},'published':False}


class RegistrarTests(unittest.TestCase):
    def setUp(self):
        from polaris_node.registrar import Registrar
        from polaris_node.core import PolarisError
        self.Registrar,self.Error=Registrar,PolarisError
        self.panel=MemoryPanel();self.state=state();self.saved=[]
        self.reg=self.Registrar(self.panel,self.state,lambda:self.saved.append(copy.deepcopy(self.state)))

    def test_creates_hidden_dedicated_resources_and_rerun_is_read_only(self):
        result=self.reg.ensure();self.assertEqual(set(result),{'profile_id','inbound_id','node_id','host_id'})
        self.assertEqual(len(self.panel.profiles),1);self.assertEqual(len(self.panel.nodes),1);self.assertEqual(len(self.panel.hosts),1)
        self.assertTrue(self.panel.hosts[0]['isDisabled']);self.assertTrue(self.panel.hosts[0]['isHidden'])
        self.assertEqual([r[0] for r in self.panel.requests if r[0]!='GET'],['POST','POST','POST'])
        self.assertGreaterEqual(len(self.saved),3)
        self.panel.requests.clear();self.assertEqual(self.reg.ensure(),result)
        self.assertTrue(all(m=='GET' for m,_,_ in self.panel.requests));self.assertFalse(self.panel.squads)

    def test_reconciles_ambiguous_profile_post_without_duplicate(self):
        self.panel.ambiguous='config-profiles'
        with self.assertRaises(self.Error):self.reg.ensure()
        self.assertEqual(len(self.panel.profiles),1);self.assertNotIn('profile_id',self.state['resources'])
        self.reg.ensure();self.assertEqual(len(self.panel.profiles),1)

    def test_rejects_foreign_marker_collision_without_writes(self):
        self.panel.profiles=[{'uuid':str(uuid.uuid4()),'name':'PNI 1234567890abcdef1234','config':{},'inbounds':[],'nodes':[]}]
        with self.assertRaises(self.Error):self.reg.ensure()
        self.assertFalse(any(m!='GET' for m,_,_ in self.panel.requests))

    def test_refuses_foreign_node_and_enabled_host_on_rerun(self):
        self.reg.ensure();self.panel.nodes[0]['note']='foreign-owner'
        with self.assertRaises(self.Error):self.reg.ensure()
        self.panel.nodes[0]['note']='polaris-node-installer:'+self.state['install_id']
        self.panel.hosts[0]['isDisabled']=False
        with self.assertRaises(self.Error):self.reg.ensure()

    def test_reconciles_ambiguous_node_and_host_without_duplicates(self):
        for resource in ('nodes','hosts'):
            with self.subTest(resource=resource):
                panel=MemoryPanel();data=state();reg=self.Registrar(panel,data,lambda:None)
                panel.ambiguous=resource
                with self.assertRaises(self.Error):reg.ensure()
                reg.ensure()
                self.assertEqual((len(panel.profiles),len(panel.nodes),len(panel.hosts)),(1,1,1))

    def test_refuses_profile_attached_to_a_foreign_node_before_creating(self):
        self.reg.ensure()
        self.panel.profiles[0]['nodes']=[{'uuid':str(uuid.uuid4())}]
        self.panel.requests.clear()
        with self.assertRaises(self.Error):self.reg.ensure()
        self.assertFalse(any(m!='GET' for m,_,_ in self.panel.requests))

    def test_online_refuses_an_unexpected_response_uuid(self):
        self.reg.ensure()
        original=self.panel.request
        def response(method,path,data=None):
            result=original(method,path,data)
            if method=='GET' and path.startswith('/nodes/'):result['uuid']=str(uuid.uuid4())
            return result
        self.panel.request=response
        with self.assertRaises(self.Error):self.reg.online()

    def test_online_checks_profile_association(self):
        self.reg.ensure();self.assertTrue(self.reg.online()['isConnected'])
        self.panel.nodes[0]['configProfile']['activeConfigProfileUuid']=str(uuid.uuid4())
        with self.assertRaises(self.Error):self.reg.online()

    def test_publish_requires_confirmation_and_preserves_old_inbounds(self):
        self.reg.ensure();old=str(uuid.uuid4());self.panel.squads=[{'uuid':str(uuid.uuid4()),'name':'Polaris personal','inbounds':[{'uuid':old}]}];self.panel.purpose='publish'
        with self.assertRaises(self.Error):self.reg.publish()
        self.reg.publish(confirmed=True)
        ids=[x['uuid'] for x in self.panel.squads[0]['inbounds']]
        self.assertEqual(ids,[old,self.state['resources']['inbound_id']]);self.assertTrue(self.state['published'])
        self.assertFalse(self.panel.hosts[0]['isHidden']);self.assertFalse(self.panel.hosts[0]['isDisabled'])
        self.panel.requests.clear();self.reg.publish(confirmed=True)
        self.assertFalse(any(m=='PATCH' for m,_,_ in self.panel.requests))

    def test_journals_publication_before_remote_changes(self):
        self.reg.ensure();self.panel.purpose='publish'
        self.panel.squads=[{'uuid':str(uuid.uuid4()),'name':'Polaris personal','inbounds':[{'uuid':str(uuid.uuid4())}]}]
        durable=copy.deepcopy(self.state)
        def save():durable.clear();durable.update(copy.deepcopy(self.state))
        self.reg.save=save
        original=self.panel.request
        def request(method,path,data=None):
            if method=='PATCH':
                self.assertEqual(durable['publication_intent']['resources'],self.state['resources'])
                self.assertEqual(durable['publication_intent']['phase'],'host_pending' if path=='/hosts' else 'prepared')
            return original(method,path,data)
        self.panel.request=request
        self.reg.publish(confirmed=True)
        self.assertTrue(durable['published']);self.assertNotIn('publication_intent',durable)

    def test_failed_intent_save_never_patches_remote_state(self):
        self.reg.ensure();self.panel.purpose='publish'
        self.panel.squads=[{'uuid':str(uuid.uuid4()),'name':'Polaris personal','inbounds':[]}]
        def failed_save():raise OSError('disk full')
        self.reg.save=failed_save;self.panel.requests.clear()
        with self.assertRaises(OSError):self.reg.publish(confirmed=True)
        self.assertFalse(any(method=='PATCH' for method,_,_ in self.panel.requests))
        self.assertTrue(self.panel.hosts[0]['isHidden'])

    def test_confirmed_publish_recovers_after_host_patch_and_failed_state_save(self):
        self.reg.ensure();self.panel.purpose='publish'
        self.panel.squads=[{'uuid':str(uuid.uuid4()),'name':'Polaris personal','inbounds':[{'uuid':str(uuid.uuid4())}]}]
        durable=copy.deepcopy(self.state)
        def interrupted_save():
            if self.state['published']:raise OSError('disk full after Host PATCH')
            durable.clear();durable.update(copy.deepcopy(self.state))
        self.reg.save=interrupted_save
        with self.assertRaises(OSError):self.reg.publish(confirmed=True)
        self.assertFalse(self.panel.hosts[0]['isHidden']);self.assertFalse(durable['published'])
        recovered=copy.deepcopy(durable)
        reg=self.Registrar(self.panel,recovered,lambda:None)
        self.panel.requests.clear();reg.publish(confirmed=True)
        self.assertTrue(recovered['published']);self.assertNotIn('publication_intent',recovered)
        self.assertFalse(any(method=='PATCH' for method,_,_ in self.panel.requests))

    def test_install_never_adopts_host_from_interrupted_publication(self):
        self.reg.ensure();self.panel.purpose='publish'
        self.panel.squads=[{'uuid':str(uuid.uuid4()),'name':'Polaris personal','inbounds':[]}]
        durable=copy.deepcopy(self.state)
        def interrupted_save():
            if self.state['published']:raise OSError('disk full')
            durable.clear();durable.update(copy.deepcopy(self.state))
        self.reg.save=interrupted_save
        with self.assertRaises(OSError):self.reg.publish(confirmed=True)
        self.panel.purpose='install';self.panel.requests.clear()
        with self.assertRaises(self.Error):self.Registrar(self.panel,copy.deepcopy(durable),lambda:None).ensure()
        self.assertFalse(any(method!='GET' for method,_,_ in self.panel.requests))

    def test_publish_refuses_enabled_host_without_matching_journal(self):
        self.reg.ensure();self.panel.purpose='publish'
        self.panel.hosts[0].update(isHidden=False,isDisabled=False)
        self.state['publication_intent']={'schema':1,'phase':'host_pending','install_id':'f'*32,'resources':copy.deepcopy(self.state['resources']),'squad_id':str(uuid.uuid4()),'squad_name':'Polaris personal','original_inbound_ids':[]}
        self.panel.requests.clear()
        with self.assertRaises(self.Error):self.reg.publish(confirmed=True)
        self.assertFalse(any(method=='PATCH' for method,_,_ in self.panel.requests))

    def published_fixture(self,already_allowed=False):
        self.reg.ensure();self.panel.purpose='publish';old=str(uuid.uuid4())
        ids=[old]+([self.state['resources']['inbound_id']] if already_allowed else [])
        self.panel.squads=[{'uuid':str(uuid.uuid4()),'name':'Polaris personal','inbounds':[{'uuid':x} for x in ids]}]
        self.reg.publish(confirmed=True)
        return old

    def test_publish_caches_verified_actual_visible_flags(self):
        self.published_fixture()
        self.assertEqual(self.reg.host_visibility,{'isDisabled':False,'isHidden':False})

    def test_unpublish_rejects_journal_pointing_to_unproven_squad(self):
        self.published_fixture()
        self.state['unpublication_intent']={'schema':1,'install_id':self.state['install_id'],'resources':copy.deepcopy(self.state['resources']),'cleanup':{'squad_id':str(uuid.uuid4()),'squad_name':'foreign'}}
        self.panel.requests.clear()
        with self.assertRaises(self.Error):self.reg.unpublish(confirmed=True)
        self.assertFalse(any(method=='PATCH' for method,_,_ in self.panel.requests))

    def test_unpublish_hides_owned_host_and_removes_only_proven_added_inbound(self):
        old=self.published_fixture();self.panel.requests.clear()
        with self.assertRaises(self.Error):self.reg.unpublish()
        self.reg.unpublish(confirmed=True)
        self.assertFalse(self.state['published']);self.assertTrue(self.panel.hosts[0]['isDisabled']);self.assertTrue(self.panel.hosts[0]['isHidden'])
        self.assertEqual([x['uuid'] for x in self.panel.squads[0]['inbounds']],[old])
        self.assertEqual(self.reg.host_visibility,{'isDisabled':True,'isHidden':True})
        self.panel.requests.clear();self.reg.unpublish(confirmed=True)
        self.assertFalse(any(method=='PATCH' for method,_,_ in self.panel.requests))

    def test_unpublish_leaves_preexisting_permission_and_legacy_unknown_history(self):
        for history in ('preexisting','legacy'):
            with self.subTest(history=history):
                panel=MemoryPanel();data=state();reg=self.Registrar(panel,data,lambda:None);reg.ensure();panel.purpose='publish'
                inbound=data['resources']['inbound_id'];panel.squads=[{'uuid':str(uuid.uuid4()),'name':'Polaris personal','inbounds':[{'uuid':inbound}]}]
                if history=='preexisting':reg.publish(confirmed=True)
                else:data['published']=True;panel.hosts[0].update(isDisabled=False,isHidden=False)
                panel.requests.clear();reg.unpublish(confirmed=True)
                self.assertEqual(panel.squads[0]['inbounds'],[{'uuid':inbound}])
                self.assertFalse(any(method=='PATCH' and path=='internal-squads' for method,path,_ in panel.requests))

    def test_unpublish_recovers_failed_final_save_without_repeated_patches(self):
        self.published_fixture();durable=copy.deepcopy(self.state)
        def interrupted():
            if self.state['published'] is False:raise OSError('disk full')
            durable.clear();durable.update(copy.deepcopy(self.state))
        self.reg.save=interrupted
        with self.assertRaises(OSError):self.reg.unpublish(confirmed=True)
        self.assertTrue(self.panel.hosts[0]['isHidden']);self.assertTrue(durable['published'])
        recovered=copy.deepcopy(durable);self.panel.requests.clear()
        self.Registrar(self.panel,recovered,lambda:None).unpublish(confirmed=True)
        self.assertFalse(recovered['published']);self.assertNotIn('unpublication_intent',recovered)
        self.assertFalse(any(method=='PATCH' for method,_,_ in self.panel.requests))

    def test_publish_refuses_an_unfinished_visibility_reduction(self):
        self.published_fixture()
        proof=self.state['publication_record']
        self.state['unpublication_intent']={'schema':1,'install_id':self.state['install_id'],'resources':copy.deepcopy(self.state['resources']),'cleanup':{'squad_id':proof['squad_id'],'squad_name':proof['squad_name']}}
        self.panel.requests.clear()
        with self.assertRaises(self.Error):self.reg.publish(confirmed=True)
        self.assertFalse(any(method=='PATCH' for method,_,_ in self.panel.requests))

    def test_unpublish_save_failure_does_not_change_remote_visibility(self):
        self.published_fixture();self.panel.requests.clear()
        def failed():raise OSError('disk full')
        self.reg.save=failed
        with self.assertRaises(OSError):self.reg.unpublish(confirmed=True)
        self.assertFalse(any(method=='PATCH' for method,_,_ in self.panel.requests));self.assertFalse(self.panel.hosts[0]['isHidden'])

    def test_unpublish_preserves_concurrent_squad_changes_without_overwrite(self):
        old=self.published_fixture();self.panel.squad_reads=0;self.panel.change_squad_on_second_read=True;self.panel.requests.clear()
        with self.assertRaises(self.Error):self.reg.unpublish(confirmed=True)
        self.assertTrue(self.panel.hosts[0]['isHidden'])
        self.assertIn(old,[x['uuid'] for x in self.panel.squads[0]['inbounds']])
        self.assertFalse(any(method=='PATCH' and path=='internal-squads' for method,path,_ in self.panel.requests))

    def test_visibility_reads_actual_flags_without_install_write_permissions(self):
        self.reg.ensure();self.state['published']=True;self.panel.hosts[0].update(isDisabled=False,isHidden=False);self.panel.requests.clear()
        self.assertEqual(self.reg.visibility(),{'isDisabled':False,'isHidden':False})
        self.assertTrue(all(method=='GET' for method,_,_ in self.panel.requests))

    def test_publish_detects_concurrent_squad_update_before_patch(self):
        self.reg.ensure();self.panel.squads=[{'uuid':str(uuid.uuid4()),'name':'Polaris personal','inbounds':[{'uuid':str(uuid.uuid4())}]}];self.panel.purpose='publish';self.panel.change_squad_on_second_read=True;self.panel.requests.clear()
        with self.assertRaises(self.Error):self.reg.publish(confirmed=True)
        self.assertFalse(any(m=='PATCH' for m,_,_ in self.panel.requests))
        self.assertTrue(self.panel.hosts[0]['isHidden'])


if __name__=='__main__':unittest.main()
