import gzip
import json
import time

import pytest
from fastapi.testclient import TestClient

from graph_pilot.api import create_app
from graph_pilot.collect import collect
from graph_pilot.local import Texts, index_legacy, index_parquet
from graph_pilot.s2 import APIError, S2, ingest_remote
from graph_pilot.store import Store, canonical_id


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path/'pilot.sqlite')
    instance.setting('snapshot_id','test')
    yield instance
    instance.close()


def paper(aid, sid):
    return {'paperId':sid*40,'externalIds':{'ArXiv':aid},'title':aid,'referenceCount':2,'citationCount':1}


def seed(store, aid='2606.00001'):
    pid = store.upsert(aid,{})
    store.add_node(pid,0,True)
    store.setting('seeds',{'seeds':[{'paper_id':pid}]})
    return pid


class FakeS2:
    def __init__(self, responses):
        self.responses = responses
        self.deadline = time.monotonic()+60
        self.max_requests, self.interval, self.requests = 50,0,0

    def get(self, pid, direction=None, offset=0):
        self.requests += 1
        value = self.responses[(pid,direction,offset)]
        if isinstance(value,Exception):
            raise value
        return value


def test_ids_and_old_arxiv_routes(store):
    pid = store.upsert('hep-th/9901001',{'title':'Old paper'})
    assert canonical_id('https://arxiv.org/pdf/hep-th/9901001v3.pdf') == pid
    assert canonical_id('ARXIV:2606.00001v2') == 'arxiv:2606.00001'
    store.db.commit()
    with TestClient(create_app(store.path)) as client:
        assert client.get('/paper',params={'paper_id':'hep-th/9901001v2'}).json()['paper_id']==pid
        assert client.get('/neighbors',params={'paper_id':pid,'direction':'citations'}).json()['remote_list_complete'] is False
        assert client.get('/neighbors',params={'paper_id':pid,'direction':'invalid'}).status_code==422
        assert client.get('/text',params={'paper_id':pid}).status_code==404


def test_pages_direction_dedup_and_completeness(store):
    a=seed(store)
    b='arxiv:2401.00001'
    c='arxiv:2607.00001'
    references=[{'citedPaper':paper('2401.00001','b'),'isInfluential':True},
                {'citedPaper':paper('2606.00001','a')},
                {'citedPaper':{'paperId':'d'*40,'externalIds':{}}}, {'citedPaper':None}]
    client=FakeS2({(a,None,0):paper('2606.00001','a'),
                   (a,'references',0):{'data':references,'next':4},
                   (a,'references',4):{'data':[references[0]]},
                   (a,'citations',0):{'data':[{'citingPaper':paper('2607.00001','c')}]}})
    summary=collect(store,client,max_expanded=1)
    assert summary['edges']==2
    assert store.neighbors(a,'references')['items'][0]['paper_id']==b
    assert store.neighbors(a,'citations')['items'][0]['paper_id']==c
    assert store.neighbors(b,'citations')['items'][0]['paper_id']==a
    assert store.neighbors(a,'references')['remote_list_complete']
    assert not store.neighbors(b,'citations')['remote_list_complete']
    assert summary['excluded_by_reason']=={'non_arxiv':1,'unresolved_identity':1}
    assert summary['weak_components']['largest']==3
    assert store.neighbors(a,'references',offset=1)['items']==[]


def test_rate_limit_checkpoint_resume_and_known_empty_lists(store):
    a=seed(store)
    client=FakeS2({(a,None,0):paper('2606.00001','a'),
                   (a,'references',0):{'data':[{'citedPaper':paper('2401.00001','b')}],'next':1},
                   (a,'references',1):APIError(429,'throttled')})
    summary=collect(store,client,max_expanded=1)
    assert summary['edges']==1
    assert summary['run']['stop_reason']=='api_429'
    assert not store.neighbors(a,'references')['remote_list_complete']
    assert store.neighbors(a,'references')['expansion']['next_offset']==1
    resume=FakeS2({(a,'references',1):{'data':[]},(a,'citations',0):{'data':[]}})
    summary=collect(store,resume,max_expanded=1)
    assert summary['edges']==1
    assert store.neighbors(a,'references')['remote_list_complete']
    incoming=store.neighbors(a,'citations')
    assert incoming['total_local']==0 and incoming['remote_list_complete']


def test_node_cap_rolls_back_page_without_false_completeness(store):
    a=seed(store)
    client=FakeS2({(a,None,0):paper('2606.00001','a'),
                   (a,'references',0):{'data':[{'citedPaper':paper('2401.00001','b')},
                                                       {'citedPaper':paper('2401.00002','c')}]}})
    summary=collect(store,client,max_nodes=2)
    assert summary['run']['stop_reason']=='node_budget'
    assert summary['edges']==0 and summary['graph_nodes']==1
    assert store.neighbors(a,'references')['expansion']['next_offset']==0
    assert not store.neighbors(a,'references')['remote_list_complete']


def test_page_cap_can_resume(store):
    a=seed(store)
    client=FakeS2({(a,None,0):paper('2606.00001','a'),
                   (a,'references',0):{'data':[{'citedPaper':paper('2401.00001','b')}],'next':1},
                   (a,'citations',0):{'data':[]}})
    collect(store,client,max_expanded=1,pages_per_direction=1)
    assert store.neighbors(a,'references')['expansion']['status']=='page_budget'
    resume=FakeS2({(a,'references',1):{'data':[]}})
    collect(store,resume,max_expanded=1,pages_per_direction=1)
    assert store.neighbors(a,'references')['remote_list_complete']


def test_s2_alias_preserves_legacy_text(store,tmp_path):
    sid='b'*40
    old=store.upsert('s2:'+sid,{'title':'Legacy title'})
    text=tmp_path/'body.txt'
    text.write_text('Existing full text')
    store.source(old,'plain_text',text,{},'available','legacy')
    ingest_remote(store,paper('2401.00001','b'))
    assert Texts(store).get('arxiv:2401.00001')['text']=='Existing full text'
    assert store.paper('s2:'+sid)['paper_id']=='arxiv:2401.00001'


def test_compatible_s2_neighbor_filter_and_counts(store):
    a=seed(store)
    b=store.upsert('2401.00001',{'corpus_id':123,'title':'A reference','year':2024})
    c=store.upsert('2401.00002',{'corpus_id':456,'title':'Another reference','year':2024})
    store.db.execute('INSERT INTO edges VALUES (?,?,?,?)',(a,b,1,'{}'))
    store.db.execute('INSERT INTO edges VALUES (?,?,?,?)',(a,c,0,'{}'))
    store.db.commit()
    with TestClient(create_app(store.path)) as client:
        all_refs=client.get('/neighbors/2606.00001',params={'direction':'references','limit':1}).json()
        assert all_refs['total']==2 and all_refs['returned']==1 and all_refs['influential_total']==1
        assert all_refs['items'][0]['corpusid']==123 and all_refs['items'][0]['isinfluential'] is True
        filtered=client.get('/neighbors/2606.00001',params={'direction':'references','influential_only':True}).json()
        assert filtered['total']==1 and filtered['items'][0]['arxiv_id']=='2401.00001'
        reverse=client.get('/neighbors/2401.00001',params={'direction':'citations'}).json()
        assert reverse['items'][0]['arxiv_id']=='2606.00001'


def test_parquet_locator_and_lazy_availability(store,tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    source=tmp_path/'papers.parquet'
    pq.write_table(pa.Table.from_pylist([{'id':'2606.00001','title':'One','latex':'raw 1'},
                                       {'id':'2606.00002','title':'Two','latex':None}]),source,row_group_size=1)
    index_parquet(store,source)
    assert not store.paper('2606.00001')['local_text_available']
    assert store.paper('2606.00001')['local_source_registered']
    merger=tmp_path/'merger.py'
    merger.write_text("def process_row(pid,raw):\n    return {'status':'ok','merged_latex':'MERGED '+raw}\n")
    texts=Texts(store,str(merger))
    assert texts.get('2606.00001')['text']=='MERGED raw 1'
    assert store.paper('2606.00001')['local_text_available']
    # The second row group must not silently return the first article.
    with pytest.raises(LookupError):
        texts.get('2606.00002')
    assert store.paper('2606.00002')['text_sources'][0]['status']=='absent'


def test_explicit_legacy_import(store,tmp_path):
    root=tmp_path/'legacy'
    (root/'release-run').mkdir(parents=True)
    bundle=root/'text.json.gz'
    with gzip.open(bundle,'wt') as stream:
        json.dump({'body_no_references':'Frozen body'},stream)
    (root/'release-run/fulltexts.jsonl').write_text(json.dumps({'paper_id':'arxiv:2401.00001','status':'ready','body_bundle_path':'text.json.gz'})+'\n')
    (root/'release-run/papers.jsonl').write_text(json.dumps({'paper_id':'arxiv:2401.00001','title':'Frozen'})+'\n')
    assert index_legacy(store,root)['existing_files']==1
    assert Texts(store).get('2401.00001')['text']=='Frozen body'


def test_transport_retry_cache_and_no_error_cache(tmp_path,monkeypatch):
    from types import SimpleNamespace
    client=S2(tmp_path,seconds=60,retries=1)
    monkeypatch.setattr(client,'pause',lambda seconds:None)
    responses=iter([SimpleNamespace(stdout='{"message":"rate limit"}\n429',stderr='',returncode=0),
                    SimpleNamespace(stdout='{"paperId":"abc"}\n200',stderr='',returncode=0)])
    monkeypatch.setattr('graph_pilot.s2.subprocess.run',lambda *a,**kw:next(responses))
    assert client.get('arxiv:2606.00001')['paperId']=='abc'
    assert client.requests==2
    assert client.get('arxiv:2606.00001')['paperId']=='abc'
    assert client.requests==2
    failed=S2(tmp_path/'fail',seconds=60,retries=0)
    monkeypatch.setattr(failed,'pause',lambda seconds:None)
    monkeypatch.setattr('graph_pilot.s2.subprocess.run',lambda *a,**kw:SimpleNamespace(stdout='{}\n429',stderr='',returncode=0))
    with pytest.raises(APIError):
        failed.get('arxiv:2606.00001')
    assert not list((tmp_path/'fail').glob('*.json'))
