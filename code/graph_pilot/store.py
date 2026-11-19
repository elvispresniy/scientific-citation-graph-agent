from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


def canonical_id(value: str) -> str:
    value = value.strip()
    value = re.sub(r'^https?://arxiv\.org/(abs|pdf)/', '', value)
    value = re.sub(r'^arxiv:', '', value, flags=re.I)
    value = re.sub(r'\.pdf$', '', value)
    value = re.sub(r'v\d+$', '', value)
    if re.fullmatch(r'\d{4}\.\d{4,5}|[a-z][a-z.-]+/\d{7}', value, re.I):
        return 'arxiv:' + value.lower()
    if re.fullmatch(r'(?:s2:)?[a-f0-9]{40}', value, re.I):
        return 's2:' + re.sub(r'^s2:', '', value, flags=re.I).lower()
    raise ValueError(f'Unsupported paper ID: {value!r}')


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA cache_size=-16384')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS papers(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS aliases(alias TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id));
          CREATE TABLE IF NOT EXISTS sources(
            paper_id TEXT NOT NULL REFERENCES papers(id), kind TEXT NOT NULL, path TEXT NOT NULL,
            locator TEXT NOT NULL, status TEXT NOT NULL, quality TEXT, cache_path TEXT, error TEXT,
            PRIMARY KEY(paper_id,kind,path));
          CREATE TABLE IF NOT EXISTS nodes(paper_id TEXT PRIMARY KEY REFERENCES papers(id), depth INTEGER NOT NULL,
            seed INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending');
          CREATE TABLE IF NOT EXISTS edges(src TEXT NOT NULL REFERENCES papers(id), dst TEXT NOT NULL REFERENCES papers(id),
            influential INTEGER NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(src,dst));
          CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst,src);
          CREATE TABLE IF NOT EXISTS expansions(paper_id TEXT NOT NULL REFERENCES papers(id), direction TEXT NOT NULL,
            status TEXT NOT NULL, next_offset INTEGER, received INTEGER NOT NULL DEFAULT 0,
            error TEXT, PRIMARY KEY(paper_id,direction));
          CREATE TABLE IF NOT EXISTS excluded(paper_id TEXT NOT NULL, direction TEXT NOT NULL,
            neighbor_id TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(paper_id,direction,neighbor_id));
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, time TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
        ''')

    def close(self):
        self.db.commit()
        self.db.close()

    def setting(self, key, value=None):
        if value is not None:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, dump(value)))
            self.db.commit()
            return value
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def resolve(self, value):
        pid = canonical_id(value)
        row = self.db.execute('SELECT paper_id FROM aliases WHERE alias=?', (pid,)).fetchone()
        return row[0] if row else pid

    def upsert(self, pid, metadata):
        pid = canonical_id(pid)
        old = self.db.execute('SELECT metadata FROM papers WHERE id=?', (pid,)).fetchone()
        merged = json.loads(old[0]) if old else {}
        merged.update({k: v for k, v in metadata.items() if v is not None})
        self.db.execute('INSERT OR REPLACE INTO papers VALUES (?,?)', (pid, dump(merged)))
        self.db.execute('INSERT OR REPLACE INTO aliases VALUES (?,?)', (pid, pid))
        sid = merged.get('s2_id')
        if sid:
            alias = canonical_id('s2:' + sid)
            previous = self.db.execute('SELECT paper_id FROM aliases WHERE alias=?', (alias,)).fetchone()
            if previous and previous[0] != pid:
                raise ValueError(f'Conflicting S2 identity {alias}: {previous[0]} / {pid}')
            self.db.execute('INSERT OR REPLACE INTO aliases VALUES (?,?)', (alias, pid))
        return pid

    def merge_identity(self, old, new):
        old, new = canonical_id(old), canonical_id(new)
        previous = self.db.execute('SELECT paper_id FROM aliases WHERE alias=?', (old,)).fetchone()
        if not previous or previous[0] == new:
            return
        old = previous[0]
        if old.startswith('arxiv:'):
            raise ValueError(f'Conflicting arXiv identities: {old} / {new}')
        row = self.db.execute('SELECT metadata FROM papers WHERE id=?',(old,)).fetchone()
        if row:
            metadata = json.loads(row[0])
            metadata.pop('s2_id',None)
            self.upsert(new,metadata)
            self.db.execute('INSERT OR IGNORE INTO sources SELECT ?,kind,path,locator,status,quality,cache_path,error '
                            'FROM sources WHERE paper_id=?',(new,old))
            self.db.execute('DELETE FROM sources WHERE paper_id=?',(old,))
            for edge in self.db.execute('SELECT * FROM edges WHERE src=? OR dst=?',(old,old)).fetchall():
                src, dst = (new if edge['src']==old else edge['src']), (new if edge['dst']==old else edge['dst'])
                if src != dst:
                    self.db.execute('INSERT OR IGNORE INTO edges VALUES (?,?,?,?)',(src,dst,edge['influential'],edge['evidence']))
            self.db.execute('DELETE FROM edges WHERE src=? OR dst=?',(old,old))
            node = self.db.execute('SELECT * FROM nodes WHERE paper_id=?',(old,)).fetchone()
            if node:
                self.add_node(new,node['depth'],node['seed'])
            self.db.execute('DELETE FROM nodes WHERE paper_id=?',(old,))
            self.db.execute('INSERT OR IGNORE INTO expansions SELECT ?,direction,status,next_offset,received,error '
                            'FROM expansions WHERE paper_id=?',(new,old))
            self.db.execute('DELETE FROM expansions WHERE paper_id=?',(old,))
            self.db.execute('UPDATE aliases SET paper_id=? WHERE paper_id=?',(new,old))
            self.db.execute('DELETE FROM papers WHERE id=?',(old,))

    def source(self, pid, kind, path, locator, status, quality=None):
        self.db.execute('INSERT OR IGNORE INTO sources(paper_id,kind,path,locator,status,quality) VALUES (?,?,?,?,?,?)',
                        (pid, kind, str(Path(path).resolve()), dump(locator), status, quality))

    def add_node(self, pid, depth, seed=False):
        self.db.execute('INSERT INTO nodes(paper_id,depth,seed) VALUES (?,?,?) ON CONFLICT(paper_id) DO UPDATE SET '
                        'depth=min(depth,excluded.depth),seed=max(seed,excluded.seed)', (pid, depth, int(seed)))

    def expansion(self, pid, direction, status, next_offset=0, received=0, error=None):
        self.db.execute('INSERT OR REPLACE INTO expansions VALUES (?,?,?,?,?,?)',
                        (pid, direction, status, next_offset, received, error))

    def paper(self, value):
        pid = self.resolve(value)
        row = self.db.execute('SELECT metadata FROM papers WHERE id=?', (pid,)).fetchone()
        if not row:
            raise KeyError(pid)
        sources = [dict(r) for r in self.db.execute('SELECT kind,status,quality,error FROM sources WHERE paper_id=?', (pid,))]
        ready = any(r['status'] == 'available' for r in sources)
        return {'paper_id': pid, **json.loads(row[0]), 'local_text_available': ready,
                'local_source_registered': bool(sources), 'text_sources': sources}

    def neighbors(self, value, direction, limit=50, offset=0):
        if direction not in ('references', 'citations') or not 1 <= limit <= 1000 or offset < 0:
            raise ValueError('Invalid direction or pagination')
        pid = self.paper(value)['paper_id']
        src, dst = ('src', 'dst') if direction == 'references' else ('dst', 'src')
        total = self.db.execute(f'SELECT count(*) FROM edges WHERE {src}=?', (pid,)).fetchone()[0]
        rows = self.db.execute(f'SELECT {dst} AS neighbor_id,influential FROM edges WHERE {src}=? '
                               f'ORDER BY {dst} LIMIT ? OFFSET ?', (pid, limit, offset))
        influence_known = (self.setting('capabilities') or {}).get('s2_influential',True)
        items = [{**self.paper(r['neighbor_id']), 'isinfluential': bool(r['influential']) if influence_known else None} for r in rows]
        exp = self.db.execute('SELECT * FROM expansions WHERE paper_id=? AND direction=?', (pid,direction)).fetchone()
        return {'paper_id': pid, 'direction': direction, 'total_local': total, 'offset': offset, 'limit': limit,
                'items': items, 'expansion': dict(exp) if exp else {'status':'unexpanded'},
                'snapshot_list_complete':bool(exp and exp['status']=='complete'),
                'completeness_scope':'induced_local_subgraph' if self.setting('backend')=='unarxive' else 'api_observation',
                'remote_list_complete': bool(exp and exp['status'] == 'complete' and self.setting('backend')!='unarxive')}

    def summary(self):
        def count(table):
            return self.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
        def grouped(table, column):
            return dict(self.db.execute(f'SELECT {column},count(*) FROM {table} GROUP BY {column}'))
        return {'snapshot_id': self.setting('snapshot_id'), 'indexed_papers':count('papers'), 'graph_nodes':count('nodes'),
                'edges':count('edges'), 'nodes_by_state':grouped('nodes','state'),
                'expansions_by_status':grouped('expansions','status'), 'sources_by_status':grouped('sources','status'),
                'excluded_by_reason':grouped('excluded','reason'),
                'run':self.setting('run'), 'backend':self.setting('backend') or 's2_pilot',
                'scope':self.setting('scope') or 'arxiv-only; partial API observation, not a global release'}
