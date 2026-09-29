"""Reconstruct applied policy text and audit Run B repetition 6 and CF-C/E."""
from pathlib import Path
import collections,hashlib,json,sys
import pandas as pd
R=Path(__file__).resolve().parents[1];O=R/'results/reproduced'
sys.path.insert(0,str(R/'src/harness'))
from sc_policy import SCPolicyEngine
sc=SCPolicyEngine(str(R/'src/harness/config/sc_policy.yaml'),str(R/'src/harness/config/theta_config.json'))
logs=[];blocks=[]
for f in sorted((R/'build/logs/formal').glob('*.jsonl')):
 for line in f.open():
  x=json.loads(line);logs.append(x)
  if x['sc_policy_applied']:
   text=sc.build_policy_block(x['sc_policy_payload']);digest=hashlib.sha256(text.encode()).hexdigest()
   assert digest==x['sc_block_hash']
   blocks.append({'run_id':x['run_id'],'stage':x['stage'],'turn':x['turn_no'],'node':x['node'],'characters':len(text),'sha256':digest,'text':text,'payload':x['sc_policy_payload']})
with (O/'applied_policy_blocks.jsonl').open('w') as f:
 for x in blocks:f.write(json.dumps(x,ensure_ascii=False)+'\n')
b=[x for x in logs if x['stage']=='run_b'];groups=collections.defaultdict(list)
for x in b:groups[(x['turn_no'],x['node'])].append(x)
deviations=[]
for (turn,node),rows in sorted(groups.items()):
 mode=collections.Counter(x['response_hash'] for x in rows).most_common(1)[0][0]
 for x in rows:
  if x['response_hash']!=mode:deviations.append({'run_id':x['run_id'],'turn':turn,'node':node,'response_hash':x['response_hash'],'modal_response_hash':mode})
pd.DataFrame(deviations).to_csv(O/'run_b_nonmodal_responses.csv',index=False)
assert len(deviations)==25 and {x['node'] for x in deviations}=={'A'}
assert {x['turn'] for x in deviations}==set(range(6,31))
assert len({x['run_id'] for x in deviations})==1
variant=deviations[0]['run_id'];baseline=next(x['run_id'] for x in b if x['run_id'].startswith('run_b_neo_excute_#1_'))
indexed={(x['run_id'],x['turn_no'],x['node']):x for x in b}
blockmap={(x['run_id'],x['turn'],x['node']):x for x in blocks}
trace=[]
for turn in range(1,31):
 for node in 'ABC':
  a=indexed[(baseline,turn,node)];v=indexed[(variant,turn,node)]
  row={'turn':turn,'node':node,'baseline_run_id':baseline,'variant_run_id':variant}
  for key in ['prompt_hash','payload_hash','response_hash','retrieved_chunk_ids','rag_context_chars','sc_block_hash']:
   row[key+'_same']=a[key]==v[key]
   if key in ['prompt_hash','response_hash','sc_block_hash']:row['baseline_'+key]=a[key];row['variant_'+key]=v[key]
  row['baseline_sc_chars']=a['sc_block_chars'];row['variant_sc_chars']=v['sc_block_chars']
  for label,x in [('baseline',a),('variant',v)]:
   payload=x.get('sc_policy_payload') or {};row[label+'_trigger_reason']=payload.get('sc_trigger_reason','')
  pa=a.get('sc_policy_payload') or {};pv=v.get('sc_policy_payload') or {}
  row['same_policy_except_trigger_reason']={k:v for k,v in pa.items() if k!='sc_trigger_reason'}=={k:v for k,v in pv.items() if k!='sc_trigger_reason'}
  trace.append(row)
df=pd.DataFrame(trace);df.to_csv(O/'run_b_repetition6_trace.csv',index=False)
ad=df[df.node=='A'];assert ad[ad.turn==6].prompt_hash_same.all()
assert not ad[ad.turn.between(7,30)].prompt_hash_same.any()
assert ad.same_policy_except_trigger_reason.all()
assert df.retrieved_chunk_ids_same.all() and df.rag_context_chars_same.all()
cf=[]
for stage in ['cf_c','cf_e']:
 g=[x for x in blocks if x['stage']==stage and x['node']=='A'];assert len(g)==150
 assert len({x['sha256'] for x in g})==1
 sample=g[0];payload=sample['payload']
 cf.append({'stage':stage,'runs':len({x['run_id'] for x in g}),'applied_rows':len(g),'characters':sample['characters'],'block_sha256':sample['sha256'],'evidence_sufficiency':payload['sc_evidence_sufficiency'],'verification_required':','.join(payload['sc_verification_required']),'anchor_chunks':len(payload['sc_policy_anchor_chunk_ids']),'rule_id':payload['sc_trigger_rule_id'],'trigger_reason':payload['sc_trigger_reason']})
pd.DataFrame(cf).to_csv(O/'cf_c_e_policy_comparison.csv',index=False)
for stage in ['cf_c','cf_e']:
 sample=next(x for x in blocks if x['stage']==stage)
 (O/f'{stage}_policy_block.txt').write_text(sample['text'])
examples=[]
for turn in [8,20,25]:
 for run in [baseline,variant]:
  examples.append(blockmap[(run,turn,'A')])
(O/'run_b_policy_examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2))
summary={'run_b_rows':len(b),'modal_matches':len(b)-len(deviations),'modal_match_rate':(len(b)-len(deviations))/len(b),'nonmodal_rows':len(deviations),'variant_run_id':variant,'variant_node':'A','response_difference_turns':list(range(6,31)),'prompt_difference_turns':list(range(7,31)),'cf_c_e':cf,'interpretation':'Observed replay evidence; does not identify the cause of the first response difference or isolate the causal effect of history.'}
(O/'path_trace_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
