"""Full descriptive rewrite batch; immutable inputs, bounded retries, automatic table export."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
import copy, gzip, json, os, subprocess, sys
from pathlib import Path
import numpy as np
from sklearn.preprocessing import normalize

from graph_pilot.step2_features import ROOT, Lexicon, TopicIndex, read_json, write_json, digest, encoded
from graph_pilot.factory_step2 import render_messages, Step2ContextGuard, parse_completion
from graph_pilot.factory_step3 import Config as GuardConfig, aspect_description
from graph_pilot.llm import Config as LLMConfig
from graph_pilot.durable_llm import DurableClient, Journal, exclusive_run
from graph_pilot.direct_retrieval import bm25_components, describe_ranks

BASE=ROOT/'research/factory-e2e'; NIGHT=BASE/'night-20'; OUT=BASE/'full-descriptive-20261115'

def now():return datetime.now(timezone.utc).isoformat()
def verdict(r):
    if r['finish_reason']!='stop' or r['text'].strip() not in ('true','false'):raise ValueError('Expected boolean')
    return r['text'].strip()=='true'
def rewrite_value(r):
    v=parse_completion(r)
    if set(v)!={'question'} or not isinstance(v['question'],str) or not v['question'].strip():raise ValueError('Expected question string only')
    return v

def union20(methods):return {r['paper_id'] for v in methods.values() for r in v['top_20']}
def control_summary(results,total):
    done=[r for r in results if r['status']=='completed'];yes=[r['paper_id'] for r in done if r['verdict'] is True]
    return {'true_count':len(yes),'true_ids':sorted(yes),'checked':len(done),'total':total,'complete':len(done)==total}

def load_entries():
    rows=read_json(BASE/'question-status-20261115/questions-status.json')['rows']
    questions=read_json(NIGHT/'summary.json')['questions'];pilot=ROOT/'research/factory-query-iterations/pilot-v1'
    direct=read_json(pilot.parent/'direct-search-v1/results.json')['questions']
    manifest=read_json(pilot/'manifest.json');groupby={g['name']:g for g in manifest['groups']}
    entries=[]
    for row in rows:
        ident=row['id'];targets=row['initial_target_ids'];pending=ident.startswith('U')
        entry={'id':ident,'question':row['question'],'targets':targets,'pending':pending,'table_row':copy.deepcopy(row)}
        if ident.startswith(('N','U')):
            src=ROOT/row['source'];group=src.parent
            seed=src.parents[2];anum=int(group.name)-1
            state=read_json(seed/'aspects/completed.json')['value'];entry['aspect']=aspect_description(state['shared_aspects'][anum])
            entry['source_dir']=str(src);entry['cards']=[c['paper_id'] for c in read_json(seed/'expansion/completed.json')['value']['cards']]
            if pending:
                saved=read_json(src/'search/completed.json')['value'];entry['methods']={m:{'top_20':v['top_20']} for m,v in saved.items()}
            else:entry['methods']=questions[int(ident[1:])-1]['methods']
        else:
            q=direct[int(ident[1:])-1];name=q['group'];entry['methods']=q['methods'];entry['source_dir']=str(pilot/name)
            entry['aspect']=read_json(pilot/name/'input.json')['shared_aspect'];entry['cards']=[]
        entries.append(entry)
    return entries

def prepare():
    OUT.mkdir(exist_ok=False); entries=load_entries(); source=read_json(NIGHT/'manifest.json');plan=source['plan']
    cfg_path=ROOT/plan['llm_config'];assert digest(cfg_path.read_bytes())==source['files'][str(cfg_path)]
    cfg=replace(LLMConfig.load(cfg_path),temperature=0,timeout_seconds=1500,max_requests=10000)
    judge=ROOT/plan['judge_prompt'];assert digest(judge.read_bytes())==source['files'][str(judge)]
    # Offline verification of the same frozen corpus before detaching a worker.
    TopicIndex(ROOT/plan['index'],Lexicon(ROOT/'research/terminology-pilot'),compatibility=ROOT/plan['index_compatibility'])
    rewrite=ROOT/'code/graph_pilot/prompts/group-query-descriptive-rewrite-v1-draft.md'
    (OUT/'judge-prompt.md').write_text(judge.read_text());(OUT/'rewrite-prompt.md').write_text(rewrite.read_text())
    files={str(p):digest(p.read_bytes()) for p in [Path(__file__).resolve(),judge,rewrite,ROOT/plan['llm_config'],ROOT/plan['step3_config'],ROOT/plan['index_compatibility'],ROOT/plan['index']/'manifest.json',ROOT/'code/graph_pilot/durable_llm.py',ROOT/'code/graph_pilot/direct_retrieval.py',BASE/'build_question_status.py']}
    write_json(OUT/'manifest.json',{'created_at':now(),'entries':entries,'llm_config':asdict(cfg),'plan':plan,'files':files,
       'judge_sha256':digest(judge.read_bytes()),'rewrite_sha256':digest(rewrite.read_bytes()),'workers':3,
       'max_http_requests':6000,'max_hours':24,'retry':plan['retry'],
       'scope':'32 known target sets + attempt recovery of4 interrupted originals; one generated descriptive version each; complete original and old/new control pools'})
    print(json.dumps({'prepared_entries':len(entries),'ready_for_rewrite':sum(not e['pending'] for e in entries),'pending_originals':sum(e['pending'] for e in entries),'max_http_requests':6000,'max_hours':24}),flush=True)

class Batch:
    def __init__(self,m):
        self.m=m;self.cfg=LLMConfig(**m['llm_config']);self.key=os.environ.get('GRAPH_LLM_API_KEY') or (ROOT/'.secrets/llm-api-key').read_text().strip()
        p=m['plan'];self.index=TopicIndex(ROOT/p['index'],Lexicon(ROOT/'research/terminology-pilot'),compatibility=ROOT/p['index_compatibility'])
        self.guard=Step2ContextGuard(GuardConfig.load(ROOT/p['step3_config']))
        self.journal=Journal(OUT/'journal',max_requests=m['max_http_requests'],max_hours=m['max_hours'])
        self.judge=(OUT/'judge-prompt.md').read_text();self.prompt=(OUT/'rewrite-prompt.md').read_text()
    def call(self,question,pid,directory):
        directory.mkdir(parents=True,exist_ok=True);result=directory/'result.json'
        if result.exists() and read_json(result)['status']=='completed':return read_json(result)
        record={'paper_id':pid}
        try:
            text=self.index.item(pid)['paper']['text'];messages=render_messages(self.judge,{'question':question,'full_text':text})
            write_json(directory/'messages.json',messages);write_json(directory/'context.json',self.guard.check(messages,self.cfg.max_output_tokens))
            identity={'model':self.cfg.model,'messages':messages,'config':{k:v for k,v in asdict(self.cfg).items() if k!='max_requests'}}
            key=digest(encoded(identity));old=NIGHT/'journal/responses'/key/'success.json.gz'
            cached=self.journal.directory/'responses'/key/'success.json.gz'
            if old.exists() and not cached.exists():
                with gzip.open(old,'rt') as stream:saved=json.load(stream)
                assert saved['identity']==identity;verdict(saved['completion'])
                with self.journal.key_lock(key):
                    cached.parent.mkdir(exist_ok=True)
                    if not cached.exists():cached.write_bytes(old.read_bytes())
            client=DurableClient(self.cfg,self.key,self.journal,self.m['retry'],validator=verdict)
            response=client.complete(self.cfg.model,messages);write_json(directory/'completion.json',response)
            record.update(status='completed',verdict=verdict(response))
        except Exception as exc:record.update(status='error',verdict=None,error_type=type(exc).__name__)
        write_json(result,record);return record
    def repair(self,e):
        if not e['pending']:return e
        dest=OUT/e['id'];dest.mkdir(exist_ok=True);file=dest/'recovered-original.json'
        if file.exists():
            v=read_json(file)
            if v['status']=='completed':return v['entry']
        pool=sorted(set(e['cards'])|union20(e['methods']))
        rs=[self.call(e['question'],pid,dest/'original-judge'/pid.replace(':','_')) for pid in pool]
        error=any(r['status']!='completed' for r in rs)
        e=copy.deepcopy(e)
        if not error:
            e['targets']=sorted(r['paper_id'] for r in rs if r['verdict']);e['pending']=False
        write_json(file,{'status':'error' if error else 'completed','results':rs,'entry':e})
        return e
    def search_batch(self,entries,field,filename,feedback=False):
        file=OUT/filename
        if file.exists():return read_json(file)
        entries=[e for e in entries if not e['pending'] and e.get(field)]
        if not entries:write_json(file,{});return {}
        ids=np.array(list(self.index.rows));queries=[e[field] for e in entries]
        vocab,terms,weights=bm25_components(self.index,ids,queries)
        vec=normalize(self.index.svd.transform(self.index.vectorizer.transform(queries)));lsa=vec@self.index.vectors.T
        byid={pid:i for i,pid in enumerate(ids)};out={}
        for n,e in enumerate(entries):
            scores=weights[:,[vocab[w] for w in sorted(terms[n])]].sum(axis=1)
            methods={'bm25':describe_ranks(ids,scores,e['targets']),'tfidf_lsa':describe_ranks(ids,lsa[n],e['targets'])}
            value={'methods':methods}
            if feedback:
                # Verify old retrieval is reproduced before using its feedback.
                for name in methods:
                    old=e['methods'][name]['top_20'];new=methods[name]['top_20']
                    assert [r['paper_id'] for r in old]==[r['paper_id'] for r in new]
                    assert np.allclose([r['score'] for r in old],[r['score'] for r in new])
                def contributions(pid):
                    return sorted([{'term':w,'contribution':float(weights[byid[pid],vocab[w]])} for w in terms[n] if weights[byid[pid],vocab[w]]>0],key=lambda t:-t['contribution'])
                value['feedback']={'target_papers':[{'paper_id':pid,'ranks':{m:methods[m]['target_ranks'][pid] for m in methods},'bm25_term_contributions':contributions(pid)} for pid in e['targets']],
                    'top_20':{m:[{'rank':rank,'paper_id':r['paper_id'],'score':r['score'],**({'bm25_term_contributions':contributions(r['paper_id'])} if m=='bm25' else {})} for rank,r in enumerate(v['top_20'],1)] for m,v in methods.items()}}
            out[e['id']]=value
        write_json(file,out);return out
    def generate(self,e,feedback):
        if e['pending'] or not e['targets']:return e
        d=OUT/e['id'];d.mkdir(exist_ok=True);file=d/'rewrite.json'
        e=copy.deepcopy(e)
        try:
            if file.exists():value=read_json(file)
            else:
                inputs={'original_question':e['question'],'shared_aspect':e['aspect'],'search_feedback':feedback[e['id']]['feedback']}
                messages=render_messages(self.prompt,{k:v if isinstance(v,str) else json.dumps(v,ensure_ascii=False) for k,v in inputs.items()})
                write_json(d/'rewrite-input.json',inputs);write_json(d/'rewrite-messages.json',messages)
                cfg=replace(self.cfg,temperature=1.0,max_output_tokens=32768)
                write_json(d/'rewrite-context.json',self.guard.check(messages,cfg.max_output_tokens))
                c=DurableClient(cfg,self.key,self.journal,self.m['retry'],validator=rewrite_value)
                response=c.complete(cfg.model,messages);write_json(d/'rewrite-completion.json',response)
                value=rewrite_value(response);write_json(file,value)
            e['rewritten_question']=value['question']
        except Exception as exc:e['rewrite_error']=type(exc).__name__
        return e
    def evaluate(self,e,oldsearch,newsearch):
        d=OUT/e['id'];d.mkdir(exist_ok=True);row=copy.deepcopy(e['table_row']);row['variants']=[]
        if e['pending'] or not e['targets']:
            row['state']='Не удалось завершить исходного судью' if e['pending'] else 'Исходный судья не подтвердил цели; переформулировка не генерировалась'
            return row
        targets=set(e['targets']);orig=oldsearch[e['id']]['methods'];oldpool=union20(orig)-targets
        ors=[self.call(e['question'],pid,d/'original-controls'/pid.replace(':','_')) for pid in sorted(oldpool)]
        row.update(initial_target_count=len(targets),initial_target_ids=sorted(targets),ranks={m:v['target_ranks'] for m,v in orig.items()},original_controls=control_summary(ors,len(oldpool)))
        if row['id'].startswith('U'):row['section']='Ночная серия — дополнительно восстановленные вопросы'
        if 'rewritten_question' not in e:
            row['state']='Описательная генерация не завершена: '+e.get('rewrite_error','unknown');return row
        question=e['rewritten_question'];methods=newsearch[e['id']]['methods'];newpool=union20(methods)-targets
        trs=[self.call(question,pid,d/'rewritten-targets'/pid.replace(':','_')) for pid in sorted(targets)]
        pool=oldpool|newpool
        rs=[]
        for pid in sorted(pool):
            r=self.call(question,pid,d/'rewritten-controls'/pid.replace(':','_'))
            rs.append({**r,'in_old_top20':pid in oldpool,'in_new_top20':pid in newpool})
        cs=control_summary(rs,len(pool));cs['pool_definition']='union_original_and_rewritten_top20_bm25_lsa_excluding_old_targets'
        cs['breakdown']={name:control_summary([r for r in rs if cond(r)],sum(cond(r) for r in rs)) for name,cond in {
            'old':lambda r:r['in_old_top20'],'new':lambda r:r['in_new_top20'],
            'old_only':lambda r:r['in_old_top20'] and not r['in_new_top20'],
            'new_only':lambda r:r['in_new_top20'] and not r['in_old_top20'],
            'both':lambda r:r['in_old_top20'] and r['in_new_top20']}.items()}
        yes=[r['paper_id'] for r in trs if r['status']=='completed' and r['verdict'] is True]
        no=[r['paper_id'] for r in trs if r['status']=='completed' and r['verdict'] is False];errors=[r for r in trs if r['status']!='completed']
        preserved=len(yes)==len(targets);far=preserved and all(methods[m]['target_ranks'][pid]>20 for m in methods for pid in targets)
        state=('Не все прежние цели сохранили true' if not preserved else 'Прежние цели сохранены; все вне top-20 обоих методов' if far else 'Прежние цели сохранены; есть цели в top-20')
        if question.strip()==e['question'].strip():state='Формулировка оставлена без изменения; '+state
        if cs['true_count']>=3:state+='; >=3 новых true в объединённом контроле'
        elif not cs['complete']:state+='; контроль не завершён'
        elif cs['true_count'] in (1,2):state+='; 1–2 новых true, решение открыто'
        else:state+='; контроль завершён, новых true нет (не окончательное принятие)'
        variant={'variant':'descriptive_generated','question':question,'state':state,'true_count':len(yes),'false_ids':no,'errors':len(errors),'target_count':len(targets),'all_old_targets_true':preserved,'ranks':{m:v['target_ranks'] for m,v in methods.items()},'controls':cs,'unchanged':question.strip()==e['question'].strip()}
        row['variants']=[variant];row['state']=state
        write_json(d/'evaluation.json',{'table_row':row,'entry':e,'original_controls':ors,'rewritten_targets':trs,'rewritten_controls':rs})
        return row
    def execute(self):
        entries=self.m['entries'];workers=self.m['workers']
        with ThreadPoolExecutor(max_workers=workers) as pool:entries=list(pool.map(self.repair,entries))
        old=self.search_batch(entries,'question','original-search-feedback.json',feedback=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:entries=list(pool.map(lambda e:self.generate(e,old),entries))
        new=self.search_batch(entries,'rewritten_question','rewritten-search.json')
        with ThreadPoolExecutor(max_workers=workers) as pool:rows=list(pool.map(lambda e:self.evaluate(e,old,new),entries))
        summary={'status':'finished','finished_at':now(),'http_attempts':self.journal.budget['http_attempts'],'table_rows':rows,
                 'generated_descriptive':sum('rewritten_question' in e for e in entries),'recovered_originals':sum(e['id'].startswith('U') and not e['pending'] for e in entries)}
        write_json(OUT/'summary.json',summary)
        subprocess.run([sys.executable,str(BASE/'build_question_status.py')],cwd=ROOT,check=True)
        print(json.dumps({k:v for k,v in summary.items() if k!='table_rows'}),flush=True)

def run():
    with exclusive_run(OUT):
        m=read_json(OUT/'manifest.json')
        for f,h in m['files'].items():assert digest(Path(f).read_bytes())==h,f
        assert digest((OUT/'judge-prompt.md').read_bytes())==m['judge_sha256']
        assert digest((OUT/'rewrite-prompt.md').read_bytes())==m['rewrite_sha256']
        write_json(OUT/'started.json',{'pid':os.getpid(),'started_at':now()})
        try:
            Batch(m).execute()
        except Exception as exc:
            write_json(OUT/'failure.json',{'time':now(),'error_type':type(exc).__name__})
            raise

if __name__=='__main__':{'prepare':prepare,'run':run}[sys.argv[1]]()
