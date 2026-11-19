from __future__ import annotations

from typing import Literal


def create_app(database):
    import time
    from fastapi import FastAPI, HTTPException, Query
    from .local import Texts
    from .store import Store

    app = FastAPI(title='Local citation graph pilot',version='0.1.0')
    started = time.monotonic()

    def call(operation):
        store = Store(database)
        try:
            return operation(store)
        except (KeyError,LookupError) as exc:
            raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        finally:
            store.close()

    @app.get('/healthz')
    def health():
        def result(store):
            summary=store.summary()
            return {**summary,'ok':store.setting('graph_status') in (None,'ready'),
                    'nodes':summary['graph_nodes'],'papers_lmdb':None,'lmdb':None,
                    'startup_seconds':startup_seconds,
                    'capabilities':store.setting('capabilities') or {'s2_influential':True,'s2_corpusid':True},
                    'storage':'sqlite_and_compressed_documents'}
        return call(result)

    @app.get('/paper')
    def paper(paper_id: str):
        return call(lambda s:s.paper(paper_id))

    @app.get('/text')
    def text(paper_id: str):
        return call(lambda s:Texts(s).get(paper_id))

    @app.get('/neighbors')
    def neighbors(paper_id: str,direction: Literal['references','citations'],
                  limit: int = Query(50,ge=1,le=1000),offset: int = Query(0,ge=0)):
        return call(lambda s:s.neighbors(paper_id,direction,limit,offset))

    @app.get('/paper/{arxiv_id:path}')
    def compatible_paper(arxiv_id: str):
        def result(store):
            meta=store.paper(arxiv_id)
            text=Texts(store).get(arxiv_id)
            payload={k:meta.get(k) for k in ('title','abstract','authors','categories','doi','comments','update_date')}
            payload.update(journal_ref=meta.get('journal-ref'),arxiv_id=meta['paper_id'].removeprefix('arxiv:'),
                           corpusid=meta.get('corpus_id'),merged_latex=text['text'] if text['format']=='merged_latex' else None,
                           text=text['text'],text_format=text['format'],provenance=text['provenance'],
                           capabilities=store.setting('capabilities') or {})
            merge=text.get('merge_info',{})
            for field,source in {'merge_status':'status','merge_n_files':'n_files','merge_main_file':'main_file',
                                 'merge_n_warnings':'n_warnings','merge_warnings_head':'warnings_head',
                                 'merge_expanded':'expanded','merge_missing':'missing'}.items():
                payload[field]=merge.get(source)
            for key in ('body_text','bib_entries','ref_entries'):
                if key in text:
                    payload[key]=text[key]
            return payload
        return call(result)

    @app.get('/neighbors/{arxiv_id:path}')
    def compatible_neighbors(arxiv_id: str,direction: Literal['citations','references'],
                             influential_only: bool = Query(False),limit: int = Query(50,ge=1,le=1000),
                             offset: int = Query(0,ge=0)):
        def result(store):
            pid=store.paper(arxiv_id)['paper_id']
            if store.setting('backend')=='unarxive' and not store.db.execute('SELECT 1 FROM nodes WHERE paper_id=?',(pid,)).fetchone():
                raise KeyError('arxiv_id not in published graph')
            known=(store.setting('capabilities') or {}).get('s2_influential',True)
            if influential_only and not known:
                raise HTTPException(422,{'code':'unsupported_feature','feature':'s2_influential','backend':'unarxive'})
            src,dst=('src','dst') if direction=='references' else ('dst','src')
            condition=f'{src}=?'+(' AND influential=1' if influential_only else '')
            total=store.db.execute(f'SELECT count(*) FROM edges WHERE {condition}',(pid,)).fetchone()[0]
            n_infl=store.db.execute(f'SELECT count(*) FROM edges WHERE {src}=? AND influential=1',(pid,)).fetchone()[0] if known else None
            rows=store.db.execute(f'SELECT {dst},influential FROM edges WHERE {condition} ORDER BY {dst} LIMIT ? OFFSET ?',
                                  (pid,limit,offset))
            items=[]
            for row in rows:
                meta=store.paper(row[0])
                items.append({'arxiv_id':meta['paper_id'].removeprefix('arxiv:'),'corpusid':meta.get('corpus_id'),
                              'title':meta.get('title'),'year':meta.get('year'),
                              'isinfluential':bool(row[1]) if known else None})
            complete=store.neighbors(pid,direction,1,0)
            return {'arxiv_id':pid.removeprefix('arxiv:'),'corpusid':store.paper(pid).get('corpus_id'),
                    'direction':direction,'influential_only':influential_only,'total':total,
                    'influential_total':n_infl,'offset':offset,'limit':limit,'returned':len(items),'items':items,
                    'snapshot_id':store.setting('snapshot_id'),'snapshot_list_complete':complete['snapshot_list_complete'],
                    'completeness_scope':complete['completeness_scope'],'capabilities':store.setting('capabilities') or {}}
        return call(result)

    startup_seconds=round(time.monotonic()-started,3)
    return app
