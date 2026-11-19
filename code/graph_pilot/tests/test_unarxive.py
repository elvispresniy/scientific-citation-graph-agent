import io
import json
import tarfile

import pytest
from fastapi.testclient import TestClient

from graph_pilot.api import create_app
from graph_pilot.client import GraphClient
from graph_pilot.local import Texts
from graph_pilot.store import Store
from graph_pilot.unarxive import build, references


def document(aid,targets,category='cs.CL'):
    return {'paper_id':aid,'metadata':{'title':'Paper '+aid,'abstract':'An abstract','categories':category},
            'body_text':[{'section':'Introduction','text':'A mechanism {{formula:f}} explained by {{cite:b0}}.',
                          'cite_spans':[{'ref_id':'b0','start':38,'end':49}]}],
            'ref_entries':{'f':{'latex':'x^2','type':'formula'}},
            'bib_entries':{f'b{i}':{'bib_entry_raw':'A reference','ids':{'arxiv_id':target},
                                   'contained_arXiv_ids':[{'id':target}]} for i,target in enumerate(targets)}}


@pytest.fixture
def imported(tmp_path):
    docs=[document('1901.00001',['1901.00002','1901.00001','1801.99999']),
          document('1901.00002',['1901.00003']),document('1901.00003',[]),
          document('1901.00004',['1901.00003']),document('1901.00005',[],'math.PR')]
    archive=tmp_path/'source.tar.gz'
    data=''.join(json.dumps(d)+'\n' for d in docs).encode()
    with tarfile.open(archive,'w:gz') as stream:
        entry=tarfile.TarInfo('19/papers.jsonl')
        entry.size=len(data)
        stream.addfile(entry,io.BytesIO(data))
    store=Store(tmp_path/'pilot.sqlite')
    store.setting('snapshot_id','unarxive-test')
    report=build(store,archive,max_nodes=3)
    yield store,report,archive
    store.close()


def test_induced_snapshot_and_unknown_s2_fields(imported):
    store,report,_=imported
    assert report['indexed_papers']==4
    assert report['graph_nodes']==3
    assert report['weak_components']['largest']==3
    assert report['graph_nodes_with_available_local_text']==3
    assert report['selection']['largest_candidate_component']==4
    assert report['capabilities']['s2_influential'] is False
    assert store.db.execute('SELECT count(*) FROM unarxive_links WHERE src=dst').fetchone()[0]==0
    for row in store.db.execute('SELECT src,dst FROM edges'):
        outgoing=store.neighbors(row[0],'references')
        assert row[1] in [x['paper_id'] for x in outgoing['items']]
        assert outgoing['items'][0]['isinfluential'] is None
        assert outgoing['snapshot_list_complete']
        assert not outgoing['remote_list_complete']


def test_text_math_context_and_compatible_routes(imported):
    store,_,_=imported
    pid=store.db.execute('SELECT src FROM edges ORDER BY src LIMIT 1').fetchone()[0]
    text=Texts(store).get(pid)
    assert '$x^2$' in text['text'] and '[cite:b0]' in text['text']
    assert text['body_text'] and text['bib_entries'] and text['ref_entries']
    with TestClient(create_app(store.path)) as client:
        paper=client.get('/paper/'+pid[6:]+'v2').json()
        assert paper['merged_latex'] is None
        assert paper['corpusid'] is None
        assert paper['text_format']=='unarxive_structured_text'
        assert paper['text'] and paper['bib_entries']
        params={'direction':'references','limit':1,'offset':0}
        result=client.get('/neighbors/'+pid[6:],params=params).json()
        assert result['returned']==1 and result['total']>=1
        assert result['influential_total'] is None
        assert result['items'][0]['isinfluential'] is None
        assert result['snapshot_list_complete']
        params['influential_only']='true'
        unsupported=client.get('/neighbors/'+pid[6:],params=params)
        assert unsupported.status_code==422
        assert unsupported.json()['detail']['code']=='unsupported_feature'
        absent=client.get('/neighbors/1801.99999',params={'direction':'references'})
        assert absent.status_code==404


def test_reimport_is_idempotent_and_preserves_selection(imported):
    store,report,archive=imported
    again=build(store,archive,max_nodes=3)
    assert again['edges']==report['edges']
    assert again['graph_nodes']==report['graph_nodes']
    assert again['selection']==report['selection']


def test_only_bibliography_ids_and_deduplicated_identity():
    row=document('1901.00001',['1901.00002v3'])
    row['body_text'][0]['text']+=' arXiv:1801.88888'
    edges=list(references(row))
    assert len(edges)==1
    assert edges[0][0]=='arxiv:1901.00002'
    assert edges[0][1]['contexts'] and edges[0][1]['isinfluential'] is None


def test_exact_unique_doi_join_does_not_guess_titles():
    row=document('1901.00001',[])
    row['bib_entries']={'b0':{'bib_entry_raw':'A similar title','ids':{'doi':'https://doi.org/10.1234/EXACT'}},
                        'b1':{'bib_entry_raw':'A similar title','ids':{'doi':'10.1234/another'}}}
    edges=list(references(row,{'10.1234/exact':'arxiv:1901.00002'}))
    assert len(edges)==1 and edges[0][0]=='arxiv:1901.00002'
    assert edges[0][1]['identity_method']=='exact_unique_doi_match'


def test_doi_join_does_not_override_an_explicit_arxiv_identity():
    row=document('1901.00001',['1901.00002'])
    row['bib_entries']['b0']['ids']['doi']='10.1234/conflict'
    edges=list(references(row,{'10.1234/conflict':'arxiv:1901.00003'}))
    assert [pid for pid,_ in edges]==['arxiv:1901.00002']


def test_one_client_handles_original_latex_and_unarxive(monkeypatch):
    client=GraphClient('http://localhost:8765')
    monkeypatch.setattr(client,'_get',lambda path,params=None:{'arxiv_id':'1901.00001','merged_latex':'\\section{Intro} Real LaTeX'})
    assert client.text('1901.00001')['format']=='merged_latex'
    monkeypatch.setattr(client,'_get',lambda path,params=None:{'arxiv_id':'1901.00001','merged_latex':None,
                                                           'text':'Structured scientific text','text_format':'unarxive_structured_text'})
    assert client.text('1901.00001')['text']=='Structured scientific text'
