from __future__ import annotations

import hashlib
import json
import time

from .s2 import APIError, BudgetStop, ingest_remote, utc
from .store import canonical_id, dump


def event(store, kind, payload):
    store.db.execute('INSERT INTO events(time,kind,payload) VALUES (?,?,?)',(utc(),kind,dump(payload)))
    store.db.commit()


def probe(store, client):
    results = []
    for seed in (store.setting('seeds') or {}).get('seeds',[]):
        pid = seed['paper_id']
        try:
            data = client.get(pid)
            ingest_remote(store,data,expected_id=pid)
            result = {'paper_id':pid,'status':'found','s2_id':data['paperId'],
                      'reference_count':data.get('referenceCount'),'citation_count':data.get('citationCount')}
        except APIError as exc:
            result = {'paper_id':pid,'status':'not_found' if exc.status==404 else 'api_error',
                      'http_status':exc.status,'error':str(exc)}
        except BudgetStop as exc:
            result = {'paper_id':pid,'status':'budget_stop','error':str(exc)}
        results.append(result)
        event(store,'probe',result)
        if result.get('http_status') in (0,401,403,429) or result['status']=='budget_stop':
            break
    store.setting('probe',{'observed_at':utc(),'requests_this_invocation':client.requests,'results':results})
    return store.setting('probe')


def collect(store, client, max_expanded=300, max_nodes=10000, max_depth=2, pages_per_direction=3):
    config = {'max_expanded':max_expanded,'max_nodes':max_nodes,'max_depth':max_depth,
              'pages_per_direction':pages_per_direction,'max_requests':client.max_requests,
              'deadline_seconds_remaining':round(client.deadline-time.monotonic()),'interval_seconds':client.interval,
              'arxiv_only':True,'queue_policy':'BFS, then canonical ID; technical pilot only'}
    previous = store.setting('collection_config')
    if previous and previous != config:
        event(store,'resume_configuration',{'previous':previous,'current':config})
    store.setting('collection_config',config)
    start = time.monotonic()
    run = {'started_at':utc(),'status':'running','requests_this_invocation':0,'config':config}
    store.setting('run',run)
    # All incomplete nodes can be retried explicitly on a later invocation.
    store.db.execute("UPDATE nodes SET state='pending' WHERE state IN ('partial','error','processing')")
    store.db.commit()
    reason = 'frontier_exhausted'
    current, direction, offset, received = None, None, 0, 0
    try:
        while True:
            if time.monotonic() >= client.deadline:
                raise BudgetStop('wall_time_budget')
            attempted = store.db.execute("SELECT count(DISTINCT json_extract(payload,'$.paper_id')) FROM events WHERE kind='expand_started'").fetchone()[0]
            if attempted >= max_expanded:
                # A resumed partial node already counts against the distinct-paper budget.
                node = store.db.execute("SELECT n.* FROM nodes n WHERE state='pending' AND depth<? AND EXISTS "
                                        "(SELECT 1 FROM events e WHERE e.kind='expand_started' AND json_extract(e.payload,'$.paper_id')=n.paper_id) "
                                        "ORDER BY depth,paper_id LIMIT 1",(max_depth,)).fetchone()
                if not node:
                    reason = 'expanded_paper_budget'
                    break
            else:
                node = store.db.execute("SELECT * FROM nodes WHERE state='pending' AND depth<? ORDER BY depth,paper_id LIMIT 1",(max_depth,)).fetchone()
            if not node:
                if store.db.execute("SELECT count(*) FROM nodes WHERE state='partial'").fetchone()[0]:
                    reason = 'incomplete_frontier'
                break
            current = node['paper_id']
            direction = None
            store.db.execute("UPDATE nodes SET state='processing' WHERE paper_id=?",(current,))
            event(store,'expand_started',{'paper_id':current,'depth':node['depth']})
            if not store.paper(current).get('s2_id'):
                try:
                    ingest_remote(store,client.get(current),expected_id=current)
                except APIError as exc:
                    if exc.status == 404:
                        store.db.execute("UPDATE nodes SET state='not_found' WHERE paper_id=?",(current,))
                        event(store,'remote_not_found',{'paper_id':current})
                        continue
                    raise
            for direction in ('references','citations'):
                existing = store.db.execute('SELECT * FROM expansions WHERE paper_id=? AND direction=?',(current,direction)).fetchone()
                if existing and existing['status']=='complete':
                    continue
                offset, received = (existing['next_offset'] or 0,existing['received']) if existing else (0,0)
                for _ in range(pages_per_direction):
                    store.expansion(current,direction,'in_progress',offset,received)
                    store.db.commit()
                    page = client.get(current,direction,offset)
                    rows = page.get('data')
                    if not isinstance(rows,list):
                        raise ValueError('Neighbor response has no data list')
                    next_offset = page.get('next')
                    if next_offset is not None and (not isinstance(next_offset,int) or next_offset <= offset):
                        raise ValueError('Neighbor pagination did not advance')
                    # Parse and insert a page atomically; safe replay on interruption or node cap.
                    with store.db:
                        for edge in rows:
                            record = edge.get('citedPaper' if direction=='references' else 'citingPaper')
                            if not isinstance(record,dict) or not record.get('paperId'):
                                store.db.execute('INSERT OR IGNORE INTO excluded VALUES (?,?,?,?)',
                                                 (current,direction,'unresolved:'+hashlib.sha256(dump(edge).encode()).hexdigest(),'unresolved_identity'))
                                continue
                            aid = (record.get('externalIds') or {}).get('ArXiv')
                            if not aid:
                                store.db.execute('INSERT OR IGNORE INTO excluded VALUES (?,?,?,?)',
                                                 (current,direction,record['paperId'],'non_arxiv'))
                                continue
                            # Validate identity before enforcing the graph-size cap.
                            try:
                                expected = canonical_id(aid)
                            except ValueError:
                                store.db.execute('INSERT OR IGNORE INTO excluded VALUES (?,?,?,?)',
                                                 (current,direction,record['paperId'],'invalid_arxiv_id'))
                                continue
                            known = store.db.execute('SELECT 1 FROM nodes WHERE paper_id=?',(expected,)).fetchone()
                            if not known and store.db.execute('SELECT count(*) FROM nodes').fetchone()[0] >= max_nodes:
                                raise BudgetStop('node_budget')
                            neighbor = ingest_remote(store,record)
                            if not neighbor or neighbor==current:
                                continue
                            store.add_node(neighbor,node['depth']+1)
                            src, dst = (current,neighbor) if direction=='references' else (neighbor,current)
                            evidence = {'source':'semantic_scholar_api','contexts':edge.get('contexts'),
                                        'intents':edge.get('intents'),'observed_from':current,'direction':direction}
                            store.db.execute('INSERT INTO edges VALUES (?,?,?,?) ON CONFLICT(src,dst) DO UPDATE SET '
                                             'influential=max(influential,excluded.influential)',
                                             (src,dst,int(bool(edge.get('isInfluential'))),dump(evidence)))
                        received += len(rows)
                        store.expansion(current,direction,'complete' if next_offset is None else 'in_progress',next_offset,received)
                    event(store,'page_saved',{'paper_id':current,'direction':direction,'offset':offset,'rows':len(rows),'next':next_offset})
                    if next_offset is None:
                        break
                    offset = next_offset
                else:
                    store.expansion(current,direction,'page_budget',offset,received)
                    store.db.commit()
            complete = store.db.execute("SELECT count(*) FROM expansions WHERE paper_id=? AND status='complete'",(current,)).fetchone()[0]==2
            store.db.execute('UPDATE nodes SET state=? WHERE paper_id=?',('complete' if complete else 'partial',current))
            event(store,'expand_finished',{'paper_id':current,'complete':complete})
            current = None
    except (APIError,BudgetStop,KeyboardInterrupt) as exc:
        reason = 'interrupted' if isinstance(exc,KeyboardInterrupt) else (f'api_{exc.status}' if isinstance(exc,APIError) else str(exc))
        if current:
            store.db.execute("UPDATE nodes SET state='partial' WHERE paper_id=?",(current,))
            if direction:
                store.expansion(current,direction,reason,offset,received,str(exc))
        event(store,'collection_stopped',{'reason':reason,'paper_id':current,'error':str(exc)})
    except Exception as exc:
        if current:
            store.db.execute("UPDATE nodes SET state='error' WHERE paper_id=?",(current,))
        event(store,'collection_error',{'paper_id':current,'error':f'{type(exc).__name__}: {exc}'})
        run.update(status='error',stop_reason=f'{type(exc).__name__}: {exc}',finished_at=utc())
        store.setting('run',run)
        raise
    run.update(status='stopped',stop_reason=reason,finished_at=utc(),elapsed_seconds=round(time.monotonic()-start,2),
               requests_this_invocation=client.requests)
    store.setting('run',run)
    return write_report(store)


def write_report(store):
    summary = store.summary()
    graph_ids = {r[0] for r in store.db.execute('SELECT paper_id FROM nodes')}
    adj = {pid:set() for pid in graph_ids}
    for src,dst in store.db.execute('SELECT src,dst FROM edges'):
        adj[src].add(dst)
        adj[dst].add(src)
    sizes = []
    seen = set()
    for pid in sorted(adj):
        if pid in seen:
            continue
        stack = [pid]
        seen.add(pid)
        n = 0
        while stack:
            u = stack.pop()
            n += 1
            for v in adj[u]-seen:
                seen.add(v)
                stack.append(v)
        sizes.append(n)
    summary['weak_components'] = {'count':len(sizes),'largest':max(sizes,default=0),'top_sizes':sorted(sizes,reverse=True)[:10]}
    summary['graph_nodes_with_available_local_text'] = store.db.execute("SELECT count(DISTINCT n.paper_id) FROM nodes n JOIN sources s ON s.paper_id=n.paper_id WHERE s.status='available'").fetchone()[0]
    summary['seeds'] = store.setting('seeds')
    summary['probe'] = store.setting('probe')
    destination = store.path.parent/'summary.json'
    temp = destination.with_suffix('.writing')
    temp.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    temp.replace(destination)
    return summary
