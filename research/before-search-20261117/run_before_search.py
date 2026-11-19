"""Six-hour existing factory chain through question composition/judging; no direct search."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import json,os,sys
from graph_pilot.factory_e2e import Pipeline, prepare, verify, now, collect_questions, export_questions, parse_verdict
from graph_pilot.factory_step2 import Step2ContextGuard, render_messages
from graph_pilot.step2_features import Step2Error
from graph_pilot.llm import LLMError
from graph_pilot.durable_llm import RunLimit, exclusive_run
from graph_pilot.factory_step3 import aspect_description
from graph_pilot.step2_features import ROOT, read_json, write_json, digest

HERE=Path(__file__).resolve().parent
OUT=HERE/'run-001'

class BeforeSearchPipeline(Pipeline):
 def finish_question(self,out,question,cards,graph):
  out.mkdir(parents=True)
  write_json(out/'question.json',question)
  prompt=(ROOT/self.plan['judge_prompt']).read_text();guard=Step2ContextGuard(self.cfg3)
  results=[];errors=[]
  for pid in sorted(c['paper_id'] for c in cards):
   directory=out.parent/'judge'/pid.replace(':','_').replace('/','_')
   def judge(attempt):
    attempt.mkdir(parents=True)
    messages=render_messages(prompt,{'question':question['question'],'full_text':self.index.item(pid)['paper']['text']})
    client=self.client('judge')
    write_json(attempt/'messages.json',messages);write_json(attempt/'context.json',guard.check(messages,client.config.max_output_tokens))
    response=client.complete(client.config.model,messages);write_json(attempt/'completion.json',response)
    return parse_verdict(response)
   try:value=self.stage(directory,judge);status='completed'
   except RunLimit:
    write_json(out/'partial-verdicts.json',{'verdicts':results,'errors':errors,'interrupted_by_limit':True});raise
   except (ValueError,LLMError) as exc:
    value=None;status='error';errors.append({'paper_id':pid,'error_type':type(exc).__name__})
   results.append({'paper_id':pid,'status':status,'verdict':value,'composer_selected':pid in question['answer_paper_ids'],'in_subgraph':True})
   write_json(out/'verdicts-progress.json',results)
  if errors:
   write_json(out/'partial-verdicts.json',{'verdicts':results,'errors':errors});raise Step2Error('Unresolved original judge pairs')
  result={**question,'targets':sorted(r['paper_id'] for r in results if r['verdict'] is True),'verdicts':results,
          'status':'completed','release_status':'awaiting_direct_search','judge_scope':'all step2 subgraph papers; no retrieval expansion',
          'judged_pool_size':len(results),'index_manifest_sha256':self.index.manifest_hash}
  write_json(out/'result.json',result);return result
 def execute(self):
  seeds=iter(self.probe_plan['neighbors']['seeds']);active={};results=[];exhausted=False;reason='seed_pool_exhausted'
  def save(status):
   questions=collect_questions(self.output)
   value={'status':status,'updated_at':now(),'stop_after':'question_composition_and_subgraph_judge_before_direct_search',
          'completed_questions':len(questions),'confirmed_target_papers':len({pid for q in questions for pid in q['targets']}),
          'http_attempts':self.journal.budget['http_attempts'],'stop_reason':reason,'seeds_processed':len(results),
          'questions':questions,'results':results}
   write_json(self.output/'summary.json',value);return value
  with ThreadPoolExecutor(max_workers=self.plan['workers']) as pool:
   while active or not exhausted:
    while not exhausted and len(active)<self.plan['workers']:
     try:
      self.journal.check()
      if self.journal.budget['http_attempts']>=self.plan['max_http_requests']:raise RunLimit('Request limit')
      seed=next(seeds)
     except StopIteration:exhausted=True;break
     except RunLimit:reason='run_limit';exhausted=True;break
     future=pool.submit(self.run_seed,seed);active[future]=seed['paper_id']
    if not active:break
    done,_=wait(active,timeout=30,return_when=FIRST_COMPLETED)
    for future in done:
     pid=active.pop(future)
     try:results.append(future.result())
     except RunLimit:
      reason='run_limit';exhausted=True;results.append({'seed_id':pid,'status':'run_limit','questions':[]})
    save('running')
  value=save('finished');write_json(self.output/'ready-for-search.json',value['questions']);export_questions(self.output,value)
  print(json.dumps({k:v for k,v in value.items() if k not in ('results','questions')},ensure_ascii=False),flush=True)
  return value

def main():
 if sys.argv[1]=='prepare':
  r=prepare(HERE/'plan.json',OUT);m=read_json(OUT/'manifest.json');m['files'][str(Path(__file__).resolve())]=digest(Path(__file__).read_bytes());m['scope']='Steps1,1.5,bootstrap,2,3,question composition,judge over all subgraph cards; stop before BM25/LSA search';write_json(OUT/'manifest.json',m);print(json.dumps(r),flush=True)
 else:
  with exclusive_run(OUT):
   m=verify(OUT);key=os.environ.get('GRAPH_LLM_API_KEY') or (ROOT/'.secrets/llm-api-key').read_text().strip()
   pipe=BeforeSearchPipeline(OUT,m,key)
   write_json(OUT/'started.json',{'pid':os.getpid(),'started_at':now(),'max_hours':6,'stop_after':'question_and_original_judge_before_direct_search'})
   try:pipe.execute()
   except BaseException as exc:
    write_json(OUT/'failure.json',{'time':now(),'error_type':type(exc).__name__});raise
if __name__=='__main__':main()
