from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

from .store import canonical_id, dump


def lines(path):
    with Path(path).open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def index_parquet(store, path):
    import pyarrow.parquet as pq
    path = Path(path).resolve()
    pf = pq.ParquetFile(path)
    columns = ['id', 'title', 'abstract', 'categories', 'authors', 'doi', 'journal-ref','comments','update_date']
    columns = [c for c in columns if c in pf.schema_arrow.names]
    count = 0
    for rg in range(pf.num_row_groups):
        row_index = 0
        for batch in pf.iter_batches(batch_size=512, row_groups=[rg], columns=columns, use_threads=False):
            for record in batch.to_pylist():
                pid = canonical_id(record.pop('id'))
                store.upsert(pid, record)
                store.source(pid, 'parquet_latex', path, {'row_group': rg, 'row_index': row_index}, 'unchecked')
                row_index += 1
                count += 1
        store.db.commit()
    return {'path':str(path), 'rows':count, 'bytes':path.stat().st_size, 'sha256_policy':'local file stat; not hashed in full',
            'mtime_ns':path.stat().st_mtime_ns, 'text_availability':'unchecked until source extraction'}


def index_legacy(store, root):
    """Explicit optional import of the frozen cache; no old runners are imported."""
    root = Path(root).resolve()
    manifest = root / 'release-run/fulltexts.jsonl'
    ready = {canonical_id(r['paper_id']):r for r in lines(manifest) if r.get('status') == 'ready'}
    for record in lines(root / 'release-run/papers.jsonl'):
        try:
            pid = canonical_id(record['paper_id'])
        except ValueError:
            continue
        if pid in ready:
            store.upsert(pid, {k:record[k] for k in ('title','abstract','identifiers') if k in record})
    available = 0
    for pid, record in ready.items():
        store.upsert(pid, {})
        key = 'body_bundle_path' if record.get('body_bundle_path') else 'text_path'
        path = (root / record[key]).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Cache path escapes configured legacy root')
        kind = 'body_bundle' if key == 'body_bundle_path' else 'plain_text'
        status = 'available' if path.is_file() else 'missing'
        available += status == 'available'
        store.source(pid, kind, path, {'url':record.get('url'), 'source_sha256':record.get('source_sha256'),
                                     'format':record.get('format'), 'manifest':str(manifest)}, status,
                     'extracted_body_without_bibliography' if kind == 'body_bundle' else 'legacy_extracted_text')
    store.db.commit()
    return {'root':str(root), 'ready_records':len(ready), 'existing_files':available,
            'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}


class Texts:
    def __init__(self, store, merger_path=None):
        self.store = store
        self.cache = store.path.parent / 'text-cache'
        self.merger_path = merger_path or store.setting('merger_path')
        self._merger = None

    def merger(self):
        if self._merger is None:
            if not self.merger_path:
                raise ValueError('Configure merger_path for raw Parquet sources')
            spec = importlib.util.spec_from_file_location('graph_pilot_latex_merger', self.merger_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._merger = module
        return self._merger

    def get(self, value):
        pid = self.store.paper(value)['paper_id']
        sources = self.store.db.execute("SELECT rowid,* FROM sources WHERE paper_id=? ORDER BY "
                                        "CASE status WHEN 'available' THEN 0 ELSE 1 END,kind,path", (pid,)).fetchall()
        errors = []
        for row in sources:
            source = dict(row)
            if source['status'] in ('failed','missing','absent'):
                errors.append(source['error'] or source['status'])
                continue
            locator = json.loads(source['locator'])
            merge_info = {}
            try:
                if source['kind'] == 'unarxive_doc':
                    from .unarxive import render_text
                    with gzip.open(source['path'],'rt') as stream:
                        document = json.load(stream)
                    if canonical_id(document['paper_id'])!=pid:
                        raise ValueError('unarXive document does not match paper ID')
                    if locator.get('source_hash') and document.get('_source_hash')!=locator['source_hash']:
                        raise ValueError('unarXive source hash changed')
                    text = render_text(document)
                    if not text.strip():
                        raise ValueError('Empty unarXive body')
                    return {'paper_id':pid,'text':text,'format':'unarxive_structured_text',
                            'source_kind':source['kind'],'source_path':source['path'],
                            'provenance':locator,'quality':source['quality'],
                            'body_text':document.get('body_text',[]),'bib_entries':document.get('bib_entries',{}),
                            'ref_entries':document.get('ref_entries',{})}
                elif source['kind'] == 'body_bundle':
                    with gzip.open(source['path'], 'rt') as stream:
                        bundle = json.load(stream)
                    text = bundle['body_no_references']
                    fmt = 'plain_text_without_bibliography'
                elif source['kind'] == 'plain_text':
                    text = Path(source['path']).read_text()
                    fmt = 'plain_text'
                elif source.get('cache_path') and Path(source['cache_path']).is_file():
                    with gzip.open(source['cache_path'],'rt') as stream:
                        bundle = json.load(stream)
                    text, fmt = bundle['text'], 'merged_latex'
                    merge_info = bundle.get('merge',{})
                elif source['kind'] == 'parquet_latex':
                    import pyarrow.parquet as pq
                    pf = pq.ParquetFile(source['path'])
                    target = locator['row_index']
                    record = None
                    for batch in pf.iter_batches(batch_size=16, row_groups=[locator['row_group']],
                                                 columns=['id','latex'], use_threads=False):
                        if target < batch.num_rows:
                            record = batch.slice(target,1).to_pylist()[0]
                            break
                        target -= batch.num_rows
                    if record is None or canonical_id(record['id']) != pid:
                        raise ValueError('Parquet locator does not match paper ID')
                    raw = record['latex']
                    if not isinstance(raw,str) or not raw.strip():
                        self.store.db.execute("UPDATE sources SET status='absent',error='empty_latex' WHERE rowid=?", (source['rowid'],))
                        self.store.db.commit()
                        continue
                    if len(raw.encode()) > 64*1024**2:
                        raise ValueError('Source exceeds 64 MiB extraction limit')
                    result = self.merger().process_row(pid,raw)
                    merge_info = {k:v for k,v in result.items() if k!='merged_latex'}
                    # A partial merger result remains diagnostic, not verified usable text.
                    if result['status'] != 'ok' or not result['merged_latex']:
                        raise ValueError('LaTeX merge status: ' + result['status'])
                    text, fmt = result['merged_latex'], 'merged_latex'
                    self.cache.mkdir(exist_ok=True)
                    dest = self.cache / (hashlib.sha256(pid.encode()).hexdigest()+'.json.gz')
                    temp = dest.with_suffix('.writing')
                    with gzip.open(temp,'wt') as stream:
                        json.dump({'paper_id':pid,'text':text,'format':fmt,'merge':{k:v for k,v in result.items() if k!='merged_latex'},
                                   'raw_source_sha256':hashlib.sha256(raw.encode()).hexdigest()},stream)
                    temp.replace(dest)
                    self.store.db.execute("UPDATE sources SET status='available',quality='merged_ok_content_unvalidated',cache_path=?,error=NULL WHERE rowid=?",
                                          (str(dest),source['rowid']))
                    self.store.db.commit()
                else:
                    raise ValueError('Unknown local source kind')
                if not isinstance(text,str) or not text.strip():
                    raise ValueError('Empty extracted text')
                return {'paper_id':pid, 'text':text, 'format':fmt, 'source_kind':source['kind'],
                        'source_path':source['path'], 'provenance':locator,
                        'merge_info':merge_info,
                        'quality':'merged_ok_content_unvalidated' if fmt=='merged_latex' else source['quality']}
            except (OSError, ValueError, KeyError) as exc:
                error = f'{type(exc).__name__}: {exc}'
                errors.append(error)
                self.store.db.execute("UPDATE sources SET status='failed',error=? WHERE rowid=?", (error,source['rowid']))
                self.store.db.commit()
        raise LookupError(dump({'paper_id':pid,'reason':'no_readable_local_text','errors':errors}))


def prepare_seeds(store, count=3, categories=('cs.CL','cs.IR')):
    # Technical bootstrap only; the agreed research seed sampler is a later stage.
    rows = store.db.execute("SELECT p.id,p.metadata FROM papers p JOIN sources s ON s.paper_id=p.id "
                            "WHERE s.kind='parquet_latex'").fetchall()
    candidates = [r['id'] for r in rows if set(json.loads(r['metadata']).get('categories','').split()) & set(categories)]
    candidates.sort(key=lambda pid:hashlib.sha256(('graph-local-pilot-v1|'+pid).encode()).hexdigest())
    selected, rejected = [], []
    texts = Texts(store)
    for pid in candidates[:30]:
        try:
            text = texts.get(pid)
        except LookupError as exc:
            rejected.append({'paper_id':pid,'reason':str(exc)})
            continue
        selected.append({'paper_id':pid,'title':store.paper(pid).get('title'), 'text_characters':len(text['text'])})
        if len(selected) == count:
            break
    result = {'purpose':'technical bootstrap, not factory step-1 sampling', 'categories':list(categories),
              'ordering':'sha256(graph-local-pilot-v1|canonical_id)', 'seeds':selected, 'rejected':rejected}
    store.setting('seeds',result)
    for seed in selected:
        store.add_node(seed['paper_id'],0,True)
    store.db.commit()
    return result
