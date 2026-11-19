"""Stream an official unarXive archive into a bounded, explicit local snapshot."""
from __future__ import annotations

import collections
import datetime as dt
import gzip
import hashlib
import json
import re
import shutil
import tarfile
import time
from pathlib import Path

from .store import canonical_id, dump


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def records(archive):
    # Never extract archive paths to the filesystem or load entire JSONL members.
    with tarfile.open(archive,'r|*') as stream:
        for member in stream:
            if not member.isfile() or not member.name.endswith('.jsonl'):
                continue
            with stream.extractfile(member) as lines:
                for number,line in enumerate(lines,1):
                    if line.strip():
                        yield member.name,number,json.loads(line)


def normalize_doi(value):
    if not isinstance(value,str):
        return None
    value=re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)','',value.strip(),flags=re.I).lower()
    return value if re.fullmatch(r'10\.\d{4,9}/[^\s,;]+',value) else None


def references(record,doi_map=None):
    """Resolve explicit arXiv identities, retaining the bibliography/citation evidence."""
    entries = record.get('bib_entries') or {}
    if not isinstance(entries,dict):
        raise ValueError('bib_entries must be a dictionary')
    contexts = collections.defaultdict(list)
    for paragraph in record.get('body_text') or []:
        for span in paragraph.get('cite_spans') or []:
            key = span.get('ref_id')
            if key and len(contexts[key]) < 2:
                text=paragraph.get('text','')
                start=span.get('start') if isinstance(span.get('start'),int) else 0
                lo=max(0,start-400)
                contexts[key].append({'section':paragraph.get('section'),'text':text[lo:start+800],
                                      'window_start':lo,'start':span.get('start'),'end':span.get('end')})
    for key,bib in entries.items():
        candidates = []
        value = (bib.get('ids') or {}).get('arxiv_id')
        if value:
            candidates.extend(value if isinstance(value,list) else [value])
        for item in bib.get('contained_arXiv_ids') or []:
            candidates.append(item.get('id') if isinstance(item,dict) else item)
        for link in bib.get('contained_links') or []:
            url = link.get('url','')
            if re.match(r'https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/',url,re.I):
                candidates.append(re.sub(r'^https?://www\.', 'https://',url))
        # Search only the bibliography and only explicit arXiv-labelled IDs.
        candidates.extend(re.findall(r'arxiv\s*:\s*(\d{4}\.\d{4,5}(?:v\d+)?|[a-z.-]+/\d{7}(?:v\d+)?)',
                                     bib.get('bib_entry_raw',''),re.I))
        targets = set()
        for candidate in candidates:
            try:
                target = canonical_id(str(candidate))
            except ValueError:
                continue
            if target.startswith('arxiv:'):
                targets.add(target)
        methods={target:'explicit_arxiv_identity' for target in targets}
        if doi_map and not targets:
            dois=[(bib.get('ids') or {}).get('doi')]
            dois.extend(link.get('url') for link in bib.get('contained_links') or []
                        if re.match(r'https?://(?:dx\.)?doi\.org/',link.get('url',''),re.I))
            for doi in dois:
                normalized=normalize_doi(doi)
                target=doi_map.get(normalized)
                if target:
                    targets.add(target)
                    methods.setdefault(target,'exact_unique_doi_match')
        for target in sorted(targets):
            yield target,{'source':'unarxive_bibliography','bib_key':key,
                          'raw_reference':bib.get('bib_entry_raw','')[:2500],
                          'contexts':contexts.get(key,[]),'identity_method':methods[target],'isinfluential':None}


def render_text(record):
    refs = record.get('ref_entries') or {}

    def formula(match):
        item = refs.get(match.group(1),{})
        return '$'+item['latex']+'$' if item.get('latex') else match.group(0)

    parts = []
    abstract = (record.get('metadata') or {}).get('abstract')
    if isinstance(abstract,str) and abstract.strip():
        parts.extend(['# Abstract',abstract.strip()])
    section = None
    for paragraph in record.get('body_text') or []:
        if paragraph.get('section') and paragraph['section'] != section:
            section = paragraph['section']
            parts.append('# '+section)
        text = re.sub(r'\{\{formula:([^}]+)\}\}',formula,paragraph.get('text',''))
        text = re.sub(r'\{\{cite:([^}]+)\}\}',r'[cite:\1]',text)
        if text.strip():
            parts.append(text.strip())
    return '\n\n'.join(parts)


def metadata(record):
    source = record.get('metadata') or {}
    result = {k:source.get(k) for k in ('title','abstract','authors','categories','doi','journal-ref','comments','update_date','license')}
    aid = canonical_id(record['paper_id'])[6:]
    year = int(aid.split('/')[-1][:2])
    result.update(year=1900+year if year>=91 else 2000+year,discipline=record.get('discipline'),
                  graph_source='unarxive',source_hash=record.get('_source_hash'))
    return result


def build(store, archive, *, max_candidates=30000,max_nodes=10000,max_document_bytes=1536*1024**2,
          seconds=2400,categories=('cs.',)):
    archive = Path(archive).resolve()
    if store.setting('backend') not in (None,'unarxive'):
        raise ValueError('Use a separate database for unarXive')
    config = {'archive':str(archive),'archive_bytes':archive.stat().st_size,'max_candidates':max_candidates,
              'max_nodes':max_nodes,'max_document_bytes':max_document_bytes,'seconds':seconds,'categories':list(categories)}
    old = store.setting('unarxive_config')
    if old and old != config:
        raise ValueError('Import configuration changed: use a new database')
    store.setting('unarxive_config',config)
    store.setting('backend','unarxive')
    store.setting('capabilities',{'s2_corpusid':False,'s2_influential':False,'merged_latex':False,
                                 'structured_fulltext':True,'citation_contexts':True})
    store.setting('scope','induced subgraph of text-bearing CS papers in unarXive open subset; explicit arXiv identities and exact unique DOI matches')
    store.db.executescript('''
      CREATE TABLE IF NOT EXISTS unarxive_links(src TEXT NOT NULL,dst TEXT NOT NULL,evidence TEXT NOT NULL,
        PRIMARY KEY(src,dst));
      CREATE INDEX IF NOT EXISTS unarxive_links_dst ON unarxive_links(dst,src);
      CREATE TABLE IF NOT EXISTS unarxive_imported(paper_id TEXT PRIMARY KEY,bytes INTEGER NOT NULL);
    ''')
    if store.setting('graph_status')=='ready':
        return graph_report(store)
    store.setting('graph_status','building')
    directory = store.path.parent/'documents'/store.path.stem
    directory.mkdir(parents=True,exist_ok=True)
    start = time.monotonic()
    counts = collections.Counter()
    saved,stored = store.db.execute('SELECT count(*),coalesce(sum(bytes),0) FROM unarxive_imported').fetchone()
    finished,stop = False,'archive_complete'
    try:
        for member,line,record in records(archive):
            counts['scanned'] += 1
            if time.monotonic()-start>=seconds:
                stop='time_budget'
                break
            pid = canonical_id(record['paper_id'])
            if store.db.execute('SELECT 1 FROM unarxive_imported WHERE paper_id=?',(pid,)).fetchone():
                continue
            cats = (record.get('metadata') or {}).get('categories','').split()
            if categories and not any(c.startswith(prefix) for c in cats for prefix in categories):
                continue
            if saved >= max_candidates:
                stop='candidate_budget'
                break
            if not any(p.get('text','').strip() for p in record.get('body_text') or []):
                counts['empty_body'] += 1
                continue
            encoded = gzip.compress(json.dumps(record,ensure_ascii=False).encode(),compresslevel=3,mtime=0)
            if stored+len(encoded)>max_document_bytes:
                stop='document_storage_budget'
                break
            if shutil.disk_usage(directory).free < 5*1024**3:
                stop='free_disk_budget'
                break
            if store.path.stat().st_size>2*1024**3:
                stop='staging_database_budget'
                break
            dest = directory/(hashlib.sha256(pid.encode()).hexdigest()+'.json.gz')
            temp = dest.with_suffix('.writing')
            temp.write_bytes(encoded)
            temp.replace(dest)
            store.upsert(pid,metadata(record))
            store.source(pid,'unarxive_doc',dest,{'archive':str(archive),'member':member,'line':line,
                                                'source_hash':record.get('_source_hash')},'available','unarxive_structured_text')
            for target,evidence in references(record):
                if target==pid:
                    counts['self_references'] += 1
                    continue
                store.db.execute('INSERT OR IGNORE INTO unarxive_links VALUES (?,?,?)',(pid,target,dump(evidence)))
            store.db.execute('INSERT INTO unarxive_imported VALUES (?,?)',(pid,len(encoded)))
            saved += 1
            stored += len(encoded)
            if saved % 250==0:
                store.db.commit()
                progress={'time':utc(),'status':'building','saved_candidates':saved,'document_bytes':stored,
                          'scanned_this_invocation':counts['scanned'],'elapsed_seconds':round(time.monotonic()-start,1)}
                store.setting('import_progress',progress)
                print(dump(progress),flush=True)
        else:
            finished=True
    except (KeyboardInterrupt,tarfile.TarError,EOFError) as exc:
        stop=f'interrupted:{type(exc).__name__}'
    store.db.commit()
    progress={'time':utc(),'status':'catalogued','saved_candidates':saved,'document_bytes':stored,
              'scanned_this_invocation':counts['scanned'],'counts':dict(counts),
              'archive_scan_complete':finished,'stop_reason':stop,'elapsed_seconds':round(time.monotonic()-start,1)}
    store.setting('import_progress',progress)
    # Publish the explicitly bounded imported corpus, even if a configured budget stopped its growth.
    enrich_doi_links(store)
    finalize(store,max_nodes)
    return graph_report(store)


def enrich_doi_links(store,seconds=60):
    started=time.monotonic()
    grouped=collections.defaultdict(list)
    for row in store.db.execute('SELECT id,metadata FROM papers'):
        doi=normalize_doi(json.loads(row['metadata']).get('doi'))
        if doi:
            grouped[doi].append(row['id'])
    mapping={doi:ids[0] for doi,ids in grouped.items() if len(ids)==1}
    before=store.db.execute('SELECT count(*) FROM unarxive_links').fetchone()[0]
    processed,skipped,complete=0,0,True
    for i,row in enumerate(store.db.execute("SELECT paper_id,path FROM sources WHERE kind='unarxive_doc'").fetchall(),1):
        if time.monotonic()-started>=seconds:
            complete=False
            break
        with gzip.open(row['path'],'rt') as stream:
            raw=stream.read(16*1024**2+1)
        if len(raw)>16*1024**2:
            skipped+=1
            continue
        record=json.loads(raw)
        processed+=1
        for target,evidence in references(record,mapping):
            if evidence['identity_method']!='exact_unique_doi_match' or target==row['paper_id']:
                continue
            store.db.execute('INSERT OR IGNORE INTO unarxive_links VALUES (?,?,?)',(row['paper_id'],target,dump(evidence)))
        if i%500==0:
            store.db.commit()
            store.setting('doi_enrichment_progress',{'processed_documents':processed,'elapsed_seconds':round(time.monotonic()-started,1)})
    store.db.commit()
    after=store.db.execute('SELECT count(*) FROM unarxive_links').fetchone()[0]
    store.setting('doi_enrichment',{'unique_catalog_dois':len(mapping),'ambiguous_dois_skipped':sum(len(ids)>1 for ids in grouped.values()),
                                   'added_reference_edges':after-before,'processed_documents':processed,'complete':complete,
                                   'skipped_large_documents':skipped,'elapsed_seconds':round(time.monotonic()-started,2),
                                   'budget_seconds':seconds,'policy':'exact DOI from structured bibliography or DOI URL; no title matching'})
    store.setting('scope','induced subgraph of text-bearing CS papers in unarXive open subset; explicit arXiv identities and exact unique DOI matches')


def finalize(store,max_nodes):
    ids = [r[0] for r in store.db.execute('SELECT paper_id FROM unarxive_imported ORDER BY paper_id')]
    adjacency = {pid:set() for pid in ids}
    sql='SELECT l.src,l.dst FROM unarxive_links l JOIN unarxive_imported d ON d.paper_id=l.dst'
    for src,dst in store.db.execute(sql):
        adjacency[src].add(dst)
        adjacency[dst].add(src)
    components,seen = [],set()
    for pid in ids:
        if pid in seen:
            continue
        queue,component = [pid],[]
        seen.add(pid)
        while queue:
            u=queue.pop()
            component.append(u)
            for v in adjacency[u]-seen:
                seen.add(v)
                queue.append(v)
        components.append(component)
    components.sort(key=lambda c:(-len(c),min(c)))
    selected=[]
    for component in components:
        # A deterministic connected BFS prefix from the largest available component.
        root=min(component,key=lambda pid:(-len(adjacency[pid]),pid))
        queue=collections.deque([root])
        seen={root}
        while queue and len(selected)<max_nodes:
            u=queue.popleft()
            selected.append(u)
            for v in sorted(adjacency[u]):
                if v not in seen:
                    seen.add(v)
                    queue.append(v)
        if len(selected)>=max_nodes:
            break
    with store.db:
        store.db.execute('DELETE FROM edges')
        store.db.execute('DELETE FROM expansions')
        store.db.execute('DELETE FROM nodes')
        store.db.executemany("INSERT INTO nodes(paper_id,depth,seed,state) VALUES (?,0,0,'complete')",((pid,) for pid in selected))
        # influential=0 is an internal placeholder; capability=false exposes UNKNOWN, never false.
        store.db.execute('INSERT INTO edges(src,dst,influential,evidence) SELECT l.src,l.dst,0,l.evidence '
                         'FROM unarxive_links l JOIN nodes a ON a.paper_id=l.src JOIN nodes b ON b.paper_id=l.dst')
        for pid in selected:
            for direction in ('references','citations'):
                store.expansion(pid,direction,'complete',None)
    store.setting('selection',{'policy':'largest weak component first; BFS from max-degree vertex, ID tie-break',
                               'purpose':'technical debugging corpus, not factory seed selection or evaluation sample',
                               'candidate_components':len(components),'largest_candidate_component':len(components[0]) if components else 0,
                               'selected_nodes':len(selected),'max_nodes':max_nodes,'complete_only_within_published_snapshot':True})
    store.setting('graph_status','ready')


def graph_report(store):
    from .collect import write_report
    report=write_report(store)
    for key in ('backend','capabilities','scope','unarxive_config','import_progress','selection','archive_provenance','doi_enrichment'):
        report[key]=store.setting(key)
    sample = store.db.execute('SELECT src,dst FROM edges ORDER BY src,dst LIMIT 5').fetchall()
    report['example_edges']=[dict(r) for r in sample]
    report['staged_reference_edges']=store.db.execute('SELECT count(*) FROM unarxive_links').fetchone()[0]
    report['outgoing_edges_outside_snapshot']=store.db.execute('SELECT count(*) FROM unarxive_links l JOIN nodes n ON n.paper_id=l.src '
                                                              'LEFT JOIN nodes d ON d.paper_id=l.dst WHERE d.paper_id IS NULL').fetchone()[0]
    report['edges_with_citation_context']=store.db.execute("SELECT count(*) FROM edges WHERE json_array_length(json_extract(evidence,'$.contexts'))>0").fetchone()[0]
    report['years']=dict(store.db.execute("SELECT json_extract(p.metadata,'$.year'),count(*) FROM papers p JOIN nodes n ON n.paper_id=p.id "
                                         "GROUP BY json_extract(p.metadata,'$.year') ORDER BY 1"))
    # A short genuine mixed-direction walk for an end-to-end API smoke check.
    adjacency=collections.defaultdict(list)
    for src,dst in store.db.execute('SELECT src,dst FROM edges'):
        adjacency[src].append((dst,'references'))
        adjacency[dst].append((src,'citations'))
    report['example_walk']=[]
    if adjacency:
        root=min(adjacency,key=lambda p:(-len(adjacency[p]),p))
        queue=collections.deque([root])
        parents={root:None}
        last=root
        while queue:
            last=queue.popleft()
            for neighbor,direction in sorted(adjacency[last]):
                if neighbor not in parents:
                    parents[neighbor]=(last,direction)
                    queue.append(neighbor)
        steps=[]
        while parents[last]:
            previous,direction=parents[last]
            steps.append({'from':previous,'to':last,'direction':direction})
            last=previous
        report['example_walk']=list(reversed(steps))[:4]
    target=store.path.parent/'summary.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report
