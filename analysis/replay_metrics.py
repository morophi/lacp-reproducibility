from pathlib import Path
import json,importlib.util,hashlib
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/reproduced';BASE=ROOT/'build/db/csv'
def read(n):return pd.read_csv(BASE/f'{n}.csv',keep_default_na=False,low_memory=False)
r=read('experiment_runs');t=read('turn_node_logs');m=read('metric_logs');p=read('payload_audit_logs');iv=read('intervention_logs')
d=t.merge(r[['id','run_id','stage','run_mode','acceptance_status']],left_on='experiment_run_id',right_on='id',suffixes=('','_run'),validate='many_to_one').merge(m[['turn_node_log_id','lms_value','lms_token_count','theta_entropy','cds','ma_assert','ma_epist','ma_hedge','sent_count','srr','sci']],left_on='id',right_on='turn_node_log_id',validate='one_to_one')
d=d[(d.acceptance_status=='accepted')&(d.run_mode=='formal')].copy();assert len(d)==7200
spec=importlib.util.spec_from_file_location('metrics',ROOT/'src/harness/metrics.py');metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)
rows=[];cache={}
for z in d.itertuples():
 text=metrics.strip_empty_think_tags(z.response_text);st=json.loads(z.metric_status)
 if text not in cache:cache[text]=(metrics.compute_ma(text),metrics.compute_srr(text),metrics.compute_sci(text))
 ma,srr,sci=cache[text]
 result={'id':z.id,'run_id':z.run_id,'stage':z.stage,'turn':z.turn_no,'node':z.node,'response_hash_matches':hashlib.sha256(z.response_text.encode()).hexdigest()==z.response_hash}
 for k in ['ma_assert','ma_epist','ma_hedge','sent_count']:
  result[k+'_error']=float(ma[k])-float(getattr(z,k))
 result['ma_matches']=all(abs(result[k+'_error'])<1e-12 for k in ['ma_assert','ma_epist','ma_hedge','sent_count'])
 for k,res in [('srr',srr),('sci',sci)]:
  result[k+'_stored']=float(getattr(z,k));result[k+'_replayed']=res[k];result[k+'_error']=res[k]-float(getattr(z,k));result[k+'_matches']=abs(result[k+'_error'])<1e-12
 result['srr_boundary_matches']=srr['srr_boundary_count']==st.get('srr_boundary_count')
 result['srr_final_matches']=srr['srr_final_count']==st.get('srr_final_count')
 result['sci_components_match']=sci['sci_components']==st.get('sci_components')
 e=st['lms_token_entropies'];marg=st['lms_selected_margins']
 result['lms_selection_count_matches']=sum(x>float(z.theta_entropy) for x in e)==int(z.lms_token_count)==len(marg)
 result['lms_mean_error']=sum(marg)/len(marg)-float(z.lms_value)
 result['lms_mean_matches']=abs(result['lms_mean_error'])<1e-12
 rows.append(result)
a=pd.DataFrame(rows);a.to_csv(OUT/'metric_replay_all_7200.csv',index=False)
checks=['response_hash_matches','ma_matches','srr_matches','sci_matches','srr_boundary_matches','srr_final_matches','sci_components_match','lms_selection_count_matches','lms_mean_matches']
summary={'rows':len(a),'unique_responses_replayed':len(cache),'checks':{k:int(a[k].sum()) for k in checks},'maximum_absolute_errors':{k:float(a[k].abs().max()) for k in a if k.endswith('_error')},'by_stage':a.groupby('stage')[checks].agg(['count','sum']).to_dict()}
summary['by_stage']={stage:{'rows':len(g),**{k:int(g[k].sum()) for k in checks}} for stage,g in a.groupby('stage')}
a[~a[checks].all(axis=1)].to_csv(OUT/'metric_replay_mismatches.csv',index=False)
examples=[]
for text,g in d[(d.stage=='run_b')&(d.turn_no==25)].groupby('response_text'):
 clean=metrics.strip_empty_think_tags(text);sent=metrics.split_korean_sentences(clean);res=metrics.compute_sci(clean)
 cov=sum(any(metrics._contains_any(s,pat) for pat in [metrics.SCI_EVIDENCE_PATTERNS,metrics.SCI_VERIFICATION_PATTERNS,metrics.SCI_CAUTION_PATTERNS,metrics.SCI_NEXT_STEP_PATTERNS]) for s in sent)
 examples.append({'node':g.node.unique().tolist(),'count':len(g),'sentences':len(sent),'covered_sentences':cov,'flags':res['sci_components'],'score':res['sci'],'response':text})
(OUT/'sci_turn25_explained.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2))
(OUT/'metric_replay_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))

assert all(summary['checks'][key]==7200 for key in checks), 'Metric replay mismatch'
