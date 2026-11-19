import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('full_descriptive',Path(__file__).resolve().parents[1]/'run_full_descriptive.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def methods(ids):
 return {name:{'top_20':[{'paper_id':pid,'score':1} for pid in ids], 'target_ranks':{'target':21}} for name in ('bm25','tfidf_lsa')}

@pytest.mark.parametrize('fail_old_only',[False,True])
def test_old_only_controls_are_rejudged_for_new_question(tmp_path,monkeypatch,fail_old_only):
 monkeypatch.setattr(m,'OUT',tmp_path)
 b=object.__new__(m.Batch);calls=[]
 def call(q,pid,d):
  calls.append((q,pid))
  if fail_old_only and q=='new' and pid=='old-only':return {'paper_id':pid,'status':'error','verdict':None}
  return {'paper_id':pid,'status':'completed','verdict':pid=='target' or (q=='new' and pid=='old-only')}
 b.call=call
 e={'id':'N01','question':'old','rewritten_question':'new','targets':['target'],'pending':False,'table_row':{'id':'N01'}}
 old={'N01':{'methods':methods(['old-only','both','target'])}};new={'N01':{'methods':methods(['new-only','both'])}}
 row=b.evaluate(e,old,new);v=row['variants'][0]
 assert v['true_count']==1 and v['all_old_targets_true']
 assert ('old','old-only') in calls and ('new','old-only') in calls
 assert {pid for q,pid in calls if q=='new'}=={'target','old-only','new-only','both'}
 assert calls.count(('new','both'))==1
 assert v['controls']['total']==3
 assert v['controls']['true_count']==(0 if fail_old_only else 1)
 assert v['controls']['checked']==(2 if fail_old_only else 3)
 assert v['controls']['complete'] is (not fail_old_only)
 assert v['controls']['breakdown']['new']['true_count']==0

def test_failed_target_is_preserved_as_false_not_dropped(tmp_path,monkeypatch):
 monkeypatch.setattr(m,'OUT',tmp_path);b=object.__new__(m.Batch)
 b.call=lambda q,pid,d:{'paper_id':pid,'status':'completed','verdict':False}
 e={'id':'N01','question':'old','rewritten_question':'new','targets':['target'],'pending':False,'table_row':{'id':'N01'}}
 row=b.evaluate(e,{'N01':{'methods':methods(['a'])}},{'N01':{'methods':methods(['b'])}})
 v=row['variants'][0];assert v['false_ids']==['target'];assert not v['all_old_targets_true'];assert v['target_count']==1

def test_rewrite_requires_one_question_and_boolean_parser_is_strict():
 assert m.rewrite_value({'finish_reason':'stop','text':'{"question":"Q?"}'})=={'question':'Q?'}
 for text in ('"true"','`true`','{"verdict":true}'):
  with pytest.raises(ValueError):m.verdict({'finish_reason':'stop','text':text})
 assert m.verdict({'finish_reason':'stop','text':'false'}) is False
