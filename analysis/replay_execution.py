from pathlib import Path
import json,sys,hashlib,collections,ast
import pandas as pd
import numpy as np
R=Path(__file__).resolve().parents[1];O=R/'results/reproduced';E=R/'build';H=R/'src/harness'
sys.path.insert(0,str(H))
from sc_policy import SCPolicyEngine
from trigger_controller import TriggerController
import prompt_builder
from prompt_builder import build_messages
def read(n):return pd.read_csv(E/'db/csv'/f'{n}.csv',keep_default_na=False,low_memory=False)
def sha(s):return hashlib.sha256(s.encode()).hexdigest()
r=read('experiment_runs');t=read('turn_node_logs');m=read('metric_logs');p=read('payload_audit_logs');iv=read('intervention_logs');rag=read('rag_retrieval_logs')
fr=r[(r.acceptance_status=='accepted')&(r.run_mode=='formal')];ft=t[t.experiment_run_id.isin(fr.id)];fm=m[m.turn_node_log_id.isin(ft.id)]
run_by_id=fr.set_index('id').run_id.to_dict();db={(run_by_id[x.experiment_run_id],int(x.turn_no),x.node):x for x in ft.itertuples()};metric=fm.set_index('turn_node_log_id');payload=p.set_index('turn_node_log_id');intervention=iv.set_index('turn_node_log_id')
logs={};inventory=[];raw_fields=set();all_fields=set()
for path in sorted((E/'logs/formal').glob('*.jsonl')):
 count=0
 for line in path.read_text().splitlines():
  x=json.loads(line);key=(x['run_id'],int(x['turn_no']),x['node']);assert key not in logs;logs[key]=x;count+=1;all_fields.update(x)
  for k in ['response_raw','raw_response','logprobs','messages','request','token_candidates','top_logprobs']:
   if isinstance(x.get(k),(list,dict)) and x[k]:raw_fields.add(k)
 inventory.append({'path':str(path.relative_to(E)),'rows':count,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
assert set(logs)==set(db)
sc=SCPolicyEngine(str(H/'config/sc_policy.yaml'),str(H/'config/theta_config.json'));cfg=json.loads((H/'config/node_config.yaml').read_text());controller=TriggerController(sc,cfg)
theta=json.loads((H/'config/theta_config.json').read_text())
templates={'current_20260630':prompt_builder.BASE_SYSTEM_PROMPT}
for version,old_template_file in [('pre_cf_f_20260614',H/'historical/prompt_builder_pre_cf_f.py')]:
 for node in ast.parse(old_template_file.read_text()).body:
  if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='BASE_SYSTEM_PROMPT' for t in node.targets):
   value=ast.literal_eval(node.value)
   if value not in templates.values():templates[version]=value
policies={}
for policy_file in H.rglob('sc_policy.yaml*'):
 try:
  engine=SCPolicyEngine(str(policy_file),str(H/'config/theta_config.json'));policies[engine.policy_hash]=str(policy_file.relative_to(R))
 except Exception:pass
utterances={}
for file in (R/'src/jump/agent/scenario').glob('*.json'):
 x=json.loads(file.read_text());turns=x.get('turns',[]) if isinstance(x,dict) else x
 for turn in turns:
  text=turn.get('utterance',turn.get('content'))
  if text:utterances[sha(text)]=text
documents=json.loads((R/'data/rag/retrieved_documents.json').read_text())
chunks={}
for id,meta in documents.items():
 md={k:v for k,v in meta.items() if not k.startswith('chroma:')};chunks[id]={'chunk_id':md.get('chunk_id') or id,'id':id,'text':meta['chroma:document'],'metadata':md,'source':md.get('source_file') or md.get('source'),'collection_name':'lacp_docs_v1_full_guideline_table_safe_body_only_v1','retrieval_method':'chromadb_vector'}
rows=[];histories=collections.defaultdict(list);block_rows=[]
for key in sorted(logs):
 x=logs[key];z=db[key];mr=metric.loc[z.id];pr=payload.loc[z.id];ir=intervention.loc[z.id]
 a={'id':z.id,'run_id':key[0],'turn':key[1],'node':key[2],'stage':x['stage']}
 a['response_matches']=x['response_hash']==z.response_hash and x['response_text']==z.response_text
 a['metrics_match']=all(abs(float(x['metrics'][k])-float(mr[k]))<1e-12 for k in ['lms_value','cds','ma_assert','ma_epist','ma_hedge','srr','sci','sent_count','theta_entropy'])
 a['status_match']=x['metric_status']==json.loads(z.metric_status)
 a['payload_hash_matches_log']=x['payload_hash']==pr.payload_hash and x['prompt_hash']==pr.prompt_hash
 a['scenario_utterance_found']=z.utterance_hash in utterances
 a['configured_history_matches']=int(pr.history_window_turns_configured)==3
 a['used_history_matches']=int(pr.history_turns_used)==min(key[1]-1,3)
 block=sc.build_policy_block(x['sc_policy_payload']) if x['sc_policy_applied'] else None
 a['sc_block_hash_matches']=sha(block)==pr.sc_block_hash if block else not pr.sc_block_hash
 a['policy_hash_matches']=x['run_policy_hash'] in policies
 hkey=(key[0],key[2]);h=histories[hkey][-6:];utterance=utterances.get(z.utterance_hash,'UNRESOLVED')
 usedchunks=[chunks[id] for id in x['retrieved_chunk_ids'] or []]
 choices=[]
 for version,template in templates.items():
  prompt_builder.BASE_SYSTEM_PROMPT=template
  candidate=build_messages(key[2],utterance,h,usedchunks,block,sc.policy_hash,x['sc_policy_payload'])
  if candidate['prompt_metadata']['prompt_hash']==pr.prompt_hash:choices.append((version,candidate))
 a['prompt_template_version']=choices[0][0] if len(choices)==1 else 'unresolved'
 built=choices[0][1] if len(choices)==1 else candidate;md=built['prompt_metadata']
 for k in ['prompt_hash','payload_hash','message_count','final_prompt_chars','rag_context_chars','sc_block_chars']:
  a[k+'_reconstructed_match']=str(md[k])==str(pr[k])
 a['chunk_lengths_match']=md['chunk_lengths']==x['chunk_lengths']
 if x['history_eligible']:histories[hkey].extend([{'role':'user','content':utterance},{'role':'assistant','content':x['response_text']}])
 rows.append(a)
a=pd.DataFrame(rows);a.to_csv(O/'execution_chain_all_7200.csv',index=False)
boolcols=[c for c in a if c not in ['id','run_id','turn','node','stage','prompt_template_version']]
summary={'log_files':len(inventory),'log_rows':len(logs),'formal_runs':len(fr),'formal_rows':len(ft),'checks':{c:int(a[c].sum()) for c in boolcols},'full_request_or_token_candidate_fields_in_formal_jsonl':sorted(raw_fields),'jsonl_top_level_fields':sorted(all_fields),'policy_hash':sc.policy_hash}
summary['prompt_template_versions']=a.groupby(['stage','prompt_template_version']).size().reset_index(name='rows').to_dict('records')
summary['matched_policy_artifacts']=policies
a[~a[boolcols].all(axis=1)].to_csv(O/'execution_chain_mismatches.csv',index=False)
# Match original file bytes, never hash the sanitized local representation.
config_sources=collections.defaultdict(list)
for x in json.loads((R/'provenance/artifacts.json').read_text()):
 if 'node_config' in x['published_path']:config_sources[x['original_sha256']].append(x['published_path'])
cm=[]
for x in fr.itertuples():cm.append({'run_id':x.run_id,'stage':x.stage,'hash':x.node_config_hash,'matching_files':' | '.join(config_sources[x.node_config_hash]),'matched':bool(config_sources[x.node_config_hash])})
pd.DataFrame(cm).to_csv(O/'formal_config_hash_links.csv',index=False);summary['config_hash_matched_runs']=sum(x['matched'] for x in cm)
# Re-evaluate the actual trigger engine on the previous stored metrics.
tr=[]
for rid in fr[fr.stage=='run_b'].run_id:
 previous={}
 for turn in range(1,31):
  decision=controller.evaluate_shared_trigger(previous,turn,'run_b','formal');x=logs[(rid,turn,'A')]
  tr.append({'run_id':rid,'turn':turn,'expected_rbc':decision['apply_sc_to_a'],'stored_rbc':x['sc_policy_applied'],'matches':decision['apply_sc_to_a']==x['sc_policy_applied'],'reasons_match':decision['reasons']==x['trigger_reasons'],'source_nodes_match':decision['trigger_source_nodes']==x['trigger_source_nodes']})
  previous={node:logs[(rid,turn,node)]['metrics'] for node in 'ABC'}
tr=pd.DataFrame(tr);tr.to_csv(O/'trigger_replay_900_decisions.csv',index=False);summary['trigger_checks']={'decisions':len(tr),'matches':int(tr.matches.sum()),'reason_matches':int(tr.reasons_match.sum()),'source_nodes_matches':int(tr.source_nodes_match.sum()),'applied':int(tr.stored_rbc.sum()),'turns':sorted(tr[tr.stored_rbc].turn.unique().tolist())}
# Recompute CR2 thresholds, both first three and all five calibration runs.
cal=[];threshold_sets={}
for n in [3,5]:
 ids=theta['cr2_run_ids'][:n];cent=[e for (rid,turn,node),x in logs.items() if rid in ids and node=='C' for e in x['metric_status']['lms_token_entropies']];ent=float(np.quantile(cent,.7));by={}
 for (rid,turn,node),x in logs.items():
  if rid not in ids:continue
  st=x['metric_status'];es=[e for e in st['lms_token_entropies'] if e>0];marg=st['lms_selected_margins'];assert len(es)==len(marg)
  keep=[v for e,v in zip(es,marg) if e>ent];by[(rid,turn,node)]={'lms':float(np.mean(keep)),'cds':float(x['metrics']['cds']),'ma':float(x['metrics']['ma_assert'])}
 for metricname in ['lms','cds','ma']:
  ac=[abs(by[(rid,t,'A')][metricname]-by[(rid,t,'C')][metricname]) for rid in ids for t in range(1,31)]
  bc=[abs(by[(rid,t,'B')][metricname]-by[(rid,t,'C')][metricname]) for rid in ids for t in range(1,31)]
  pooled=float(np.quantile(ac+bc,.95));mx=max(float(np.quantile(ac,.95)),float(np.quantile(bc,.95)))
  cal.append({'runs':n,'metric':metricname,'entropy_q70':ent,'A_C_q95':float(np.quantile(ac,.95)),'B_C_q95':float(np.quantile(bc,.95)),'pooled_q95':pooled,'max_of_pair_q95':mx,'deployed':theta['theta_'+metricname],'abs_error':abs(pooled-theta['theta_'+metricname])})
  if n==5:threshold_sets[metricname]=mx
pd.DataFrame(cal).to_csv(O/'calibration_and_max_rule.csv',index=False);summary['calibration']=cal
# This is a retrospective assignment-rule sensitivity check on fixed saved histories.
sens=[]
for mode in ['cds_only_max','lms_only_max','both_max']:
 tl=threshold_sets['lms'] if mode in ['lms_only_max','both_max'] else theta['theta_lms'];tc=threshold_sets['cds'] if mode in ['cds_only_max','both_max'] else theta['theta_cds']
 for rid in fr[fr.stage=='run_b'].run_id:
  for turn in range(1,31):
   alt=False if turn==1 else any(abs(float(logs[(rid,turn-1,node)]['metrics']['d_lms']))>tl or abs(float(logs[(rid,turn-1,node)]['metrics']['d_cds']))>tc for node in ['A','B'])
   stored=logs[(rid,turn,'A')]['sc_policy_applied'];sens.append({'mode':mode,'run_id':rid,'turn':turn,'stored':stored,'alternative':alt,'changed':alt!=stored,'theta_lms':tl,'theta_cds':tc})
ss=pd.DataFrame(sens);ss.to_csv(O/'trigger_sensitivity_all_decisions.csv',index=False);summary['sensitivity']=[{'mode':mode,'decisions':len(g),'changed':int(g.changed.sum()),'retained_applied':int((g.stored&g.alternative).sum()),'new_applied':int((~g.stored&g.alternative).sum()),'changed_rows':g[g.changed].to_dict('records')} for mode,g in ss.groupby('mode')]
snap=sc.threshold_snapshot();snap_matches=sum(x['threshold_snapshot']==snap for x in logs.values() if x['stage']=='run_b' or x['stage'].startswith('cf_'));summary['deployed_theta_snapshot_matches']=snap_matches;summary['deployed_theta_snapshot_rows']=sum(x['stage']=='run_b' or x['stage'].startswith('cf_') for x in logs.values())
summary['empty_provenance_fields']={'harness_version_runs':int((fr.harness_version=='').sum()),'metric_pipeline_version_rows':int((fm.metric_pipeline_version=='').sum()),'model_digest_rows':int((ft.model_digest=='').sum())}
(O/'execution_chain_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
(O/'formal_log_manifest.json').write_text(json.dumps(inventory,indent=2))
print(json.dumps({k:v for k,v in summary.items() if k not in ['jsonl_top_level_fields','calibration']},ensure_ascii=False,indent=2))

assert all(v==7200 for v in summary['checks'].values()), 'Input reconstruction mismatch'
assert summary['config_hash_matched_runs']==80
assert summary['trigger_checks']['matches']==summary['trigger_checks']['reason_matches']==summary['trigger_checks']['source_nodes_matches']==900
assert summary['deployed_theta_snapshot_matches']==5850
