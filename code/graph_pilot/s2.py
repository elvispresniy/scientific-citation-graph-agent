from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, urlencode

BASE = 'https://api.semanticscholar.org/graph/v1/paper/'
PAPER_FIELDS = 'paperId,corpusId,externalIds,title,abstract,year,referenceCount,citationCount'
NEIGHBOR_FIELDS = 'paperId,corpusId,externalIds,title,year,referenceCount,citationCount,contexts,intents,isInfluential'


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class APIError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class BudgetStop(RuntimeError):
    pass


class S2:
    def __init__(self, directory, seconds=3600, max_requests=2500, interval=1.1, retries=2):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.deadline = time.monotonic() + seconds
        self.max_requests, self.interval, self.retries = max_requests, interval, retries
        self.requests, self.last = 0, 0.0
        self.key = os.environ.get('S2_API_KEY')
        if self.key and not re.fullmatch(r'[A-Za-z0-9_.-]+', self.key):
            raise ValueError('Unexpected characters in S2_API_KEY')
        self.curl = '/usr/bin/curl' if Path('/usr/bin/curl').exists() else shutil.which('curl')
        if not self.curl:
            raise RuntimeError('curl is required (uses the system certificate store)')

    def pause(self, seconds):
        if time.monotonic() + seconds >= self.deadline:
            raise BudgetStop('wall_time_budget')
        time.sleep(max(0,seconds))

    def get(self, paper_id, direction=None, offset=0, limit=1000):
        remote_id = 'ARXIV:' + paper_id[6:] if paper_id.startswith('arxiv:') else paper_id.removeprefix('s2:')
        url = BASE + quote(remote_id,safe=':')
        params = {'fields':NEIGHBOR_FIELDS if direction else PAPER_FIELDS}
        if direction:
            url += '/' + direction
            params.update(offset=offset, limit=limit)
        url += '?' + urlencode(params)
        digest = hashlib.sha256(url.encode()).hexdigest()
        cache = self.directory / (digest + '.json')
        if cache.exists():
            # Error responses are never replayed as successful observations.
            return json.loads(cache.read_text())['data']
        for attempt in range(self.retries+1):
            if self.requests >= self.max_requests:
                raise BudgetStop('request_budget')
            self.pause(max(0,self.last+self.interval-time.monotonic()))
            remaining = self.deadline-time.monotonic()
            if remaining < 1:
                raise BudgetStop('wall_time_budget')
            timeout = min(30,remaining)
            args = [self.curl,'--silent','--show-error','--max-time',str(timeout),'--max-filesize','16777216',
                    '--user-agent','ScientificCitationGraphPilot/0.1','--config','-',
                    '--write-out','\n%{http_code}',url]
            config = 'header = "x-api-key: '+self.key+'"\n' if self.key else ''
            self.last = time.monotonic()
            self.requests += 1
            try:
                proc = subprocess.run(args,input=config,text=True,capture_output=True,timeout=timeout+1)
                body, sep, code = proc.stdout.rpartition('\n')
                status = int(code) if sep and code.isdigit() else 0
                if proc.returncode:
                    status = 0
                try:
                    data = json.loads(body)
                except ValueError:
                    data = {'message':body[:500] or proc.stderr[:500]}
            except subprocess.TimeoutExpired:
                status, data = 0, {'message':'transport_timeout'}
            event = {'time':utc(),'url':url,'status':status,'attempt':attempt+1,'authenticated':bool(self.key)}
            with (self.directory/'requests.jsonl').open('a') as stream:
                stream.write(json.dumps(event)+'\n')
            if status == 200:
                temp = cache.with_suffix('.writing')
                temp.write_text(json.dumps({**event,'data':data},ensure_ascii=False))
                temp.replace(cache)
                return data
            if status not in (0,429,500,502,503,504) or attempt == self.retries:
                raise APIError(status,json.dumps(data,ensure_ascii=False)[:700])
            # A single global client serializes all requests and backs off after throttling.
            self.pause(15 * 2**attempt)


def ingest_remote(store, record, expected_id=None):
    from .store import canonical_id
    ext = record.get('externalIds') or {}
    aid = ext.get('ArXiv')
    if expected_id and expected_id.startswith('arxiv:'):
        pid = canonical_id(expected_id)
        if aid and canonical_id(aid) != pid:
            raise ValueError('S2 returned a conflicting arXiv identity')
    elif aid:
        try:
            pid = canonical_id(aid)
        except ValueError:
            return None
    else:
        return None  # Preserve non-arXiv exclusions separately; graph scope stays explicit.
    sid = record.get('paperId')
    if not sid:
        raise ValueError('S2 paper has no paperId')
    store.merge_identity('s2:'+sid,pid)
    metadata = {'s2_id':sid,'external_ids':ext,'title':record.get('title'),'abstract':record.get('abstract'),
                'year':record.get('year'),'corpus_id':record.get('corpusId'),
                'remote_reference_count':record.get('referenceCount'),'remote_citation_count':record.get('citationCount'),
                'remote_observed_at':utc()}
    return store.upsert(pid,metadata)
