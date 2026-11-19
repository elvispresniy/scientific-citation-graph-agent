"""One client for the original PaSa graph API and the local compatible routes."""
import json
from urllib.error import HTTPError
from urllib.parse import quote,urlencode
from urllib.request import urlopen

from .store import canonical_id


class GraphClient:
    def __init__(self,base_url,timeout=30):
        self.base_url=base_url.rstrip('/')
        self.timeout=timeout

    def _get(self,path,params=None):
        url=self.base_url+path+('?' + urlencode(params) if params else '')
        try:
            with urlopen(url,timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code==404:
                raise LookupError(url) from exc
            raise

    def paper(self,arxiv_id):
        aid=canonical_id(arxiv_id)
        if not aid.startswith('arxiv:'):
            raise ValueError('This API expects an arXiv ID')
        return self._get('/paper/'+quote(aid[6:],safe='/'))

    def health(self):
        return self._get('/healthz')

    def neighbors(self,arxiv_id,direction,limit=50,offset=0,influential_only=False):
        if direction not in ('references','citations'):
            raise ValueError('Invalid direction')
        aid=canonical_id(arxiv_id)
        if not aid.startswith('arxiv:'):
            raise ValueError('This API expects an arXiv ID')
        return self._get('/neighbors/'+quote(aid[6:],safe='/'),
                         {'direction':direction,'limit':limit,'offset':offset,
                          'influential_only':str(influential_only).lower()})

    def text(self,arxiv_id):
        result=self.paper(arxiv_id)
        latex=result.get('merged_latex')
        if isinstance(latex,str) and latex.strip():
            return {'text':latex,'format':'merged_latex','arxiv_id':result['arxiv_id']}
        if result.get('text'):
            return {'text':result['text'],'format':result.get('text_format'),'arxiv_id':result['arxiv_id']}
        raise LookupError('No readable text in graph API response')
