"""Real native-u0 preparation: first/hot/member/profile/publication changes."""
assert a.host=='center'
state.update(virtual=True,visible=True,allowed=True,unbound=False,members=['111','222'],profile=0)
for index,member in enumerate(('111','222','333')):
 data=copy.deepcopy(payload)
 data['profile'].update(name=member,mydon_name=member)
 data['songs'][0]['high_score']+=index*1000
 publish(member,data)
principal='onebot_v11:76543'
command=prepare_b30(CommandContext(match=b30.PATTERN.match('taikob')),b30.build_ports())
observations=[]
for case in ('first','hot','member','profile','member-current'):
 if case=='member':state['members']=['111','333']
 if case=='profile':state['profile']=1
 if case=='member-current':
  data=copy.deepcopy(payload);data['profile'].update(name='333-new',mydon_name='333-new');data['songs'][0]['high_score']+=5000
  publish('333',data)
 instance=entry.create_provider();private=instance.prepare_b30(principal,principal,command)
 instance.verify(private)
 target=private.authorized_target
 assert target.members==tuple(state['members']) and target.profile_source==state['members'][state['profile']]
 store=PublicationStore(a.work/'userdata',target.user_id,max_file_bytes=64*1024*1024)
 with store.shared():
  view=store.reader()
  assert json.loads(view.current_raw())==thaw(private.current)
  assert view.manifest['dependencyHash']==private.provenance.dependency_hash
  observed={'case':case,'publication':view.publication,'dependency':private.provenance.dependency_hash,'profile':thaw(private.current)['profile']}
 if case=='hot':assert observed['publication']==observations[-1]['publication']
 if case in ('member','profile','member-current'):assert observed['dependency']!=observations[-1]['dependency']
 if case=='profile':assert observed['profile']['mydon_name']=='333'
 if case=='member-current':assert observed['profile']['mydon_name']=='333-new'
 observations.append(observed)
assert not violations,violations
(a.work/'native.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2))
print('center',len(observations),'native-u0 publication cases PASS',flush=True)
