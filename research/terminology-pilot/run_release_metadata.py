"""Expand frozen releases and collect free metadata, with a resumable cache.

Does not alter the pilot. No LLM or paid API calls. Missing metadata is explicit.
"""
import argparse,csv,hashlib,json,re,subprocess,time,xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'release-run'
SOURCES={'scholarquest':('scholarquest.raw','https://raw.githubusercontent.com/pty12345/ScholarQuest/HEAD/datasets/ScholarQuest.jsonl'),
         'autoresearchbench':('autoresearchbench.local-decoded.json','https://huggingface.co/datasets/Lk123/AutoResearchBench'),
         'paperpilot':('paperpilot_s2.raw','https://raw.githubusercontent.com/mtilyxuegao/PaperPilot/HEAD/tests/dataset/testcases_s2ids_clean.csv')}
def jl(path):return [json.loads(x) for x in path.read_text().splitlines() if x]
def dump(path,rows):
    temporary=path.with_suffix('.writing')
    temporary.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
    temporary.replace(path)
def sha(data):return hashlib.sha256(data).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sources',type=Path,required=True);parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    OUT.mkdir(exist_ok=True);cache=OUT/'cache';cache.mkdir(exist_ok=True)
    pilot={p['paper_id']:p for p in jl(ROOT/'papers.jsonl')};previous={p['paper_id']:p for p in jl(OUT/'papers.jsonl')} if (OUT/'papers.jsonl').exists() else {}
    questions=[];papers={};sources=[];excluded=[]
    manifest=json.loads((ROOT/'manifest.json').read_text())
    for name,(file,url) in SOURCES.items():
        path=args.sources/file;data=path.read_bytes();expected=next(x['source_sha256'] for x in manifest['datasets'] if x['benchmark']==name)
        assert sha(data)==expected,(name,'Release differs from the pilot source')
        (cache/file).write_bytes(data)
        rows=[json.loads(x) for x in data.decode().splitlines() if x] if name=='scholarquest' else (json.loads(data) if name=='autoresearchbench' else list(csv.DictReader(data.decode().splitlines())))
        for i,row in enumerate(rows,1):
            if name=='scholarquest':sid=row['query_id'];text=row['final_query'];context={};targets=[('arxiv',x,None) for x in row['answer_arxiv_ids']]
            elif name=='autoresearchbench':
                sid=f'row_{i:06d}';text=row['question'];context={};targets=[('arxiv',x,None) for x in row['arxiv_id'] if str(x).strip().lower() not in ('','none','null','n/a','no answer','no_answer')]
            else:
                sid=row['case_id'];text=row['user_query'];context={k:row[k] for k in ('reference_arxiv_id','reference_title','reference_source_url','search_direction') if row.get(k)}
                targets=[('s2',row[f'target_s2_id_{j}'],row[f'target_paper_{j}']) for j in range(1,11) if row.get(f'target_s2_id_{j}')]
            qid=name+':'+sid
            if not targets:excluded.append({'question_id':qid,'reason':'No released target identifier','original_record':row});continue
            ids=list(dict.fromkeys(n+':'+str(x).strip() for n,x,t in targets))
            questions.append({'question_id':qid,'benchmark':name,'text':text,'context':context,'gold_paper_ids':ids,'source':{'url':url,'source_sha256':expected,'row_number':i},'original_record':row})
            for n,x,t in targets:
                pid=n+':'+str(x).strip()
                papers.setdefault(pid,previous.get(pid,pilot.get(pid,{'paper_id':pid,'identifiers':{n:str(x).strip()},'title':t,'abstract':None,'metadata_status':'partial' if t else 'pending','sources':[]})))
        sources.append({'benchmark':name,'source_url':url,'source_sha256':expected,'source_rows':len(rows)})
    dump(OUT/'questions.jsonl',questions);dump(OUT/'excluded-questions.jsonl',excluded)
    def save():
        dump(OUT/'papers.jsonl',[papers[k] for k in sorted(papers)])
        summary={'scope':'all rows of the exact frozen pilot releases','questions':len(questions),'pairs':sum(len(q['gold_paper_ids']) for q in questions),'unique_target_records':len(papers),'sources':sources,'excluded_no_target_questions':len(excluded),'metadata_counts':dict(Counter(p['metadata_status'] for p in papers.values())),
                 'crase':'exact release unavailable; not substituted','paperpilot':'public 50-case CSV; canonical test alignment unverified','fulltexts':'Separate resumable collection; see collection-progress.json and fulltexts.jsonl. Missing bodies remain null.'}
        (OUT/'inventory.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    save();print(json.loads((OUT/'inventory.json').read_text()),flush=True)
    if args.prepare_only:return
    last=0;blocked_hosts=set()
    def request(url,body=None):
        nonlocal last
        host=url.split('/')[2]
        if host in blocked_hosts:return b''
        key=sha((url+(body or '')).encode());path=cache/(key+'.response')
        if path.exists():return path.read_bytes()
        time.sleep(max(0,3.2-(time.monotonic()-last)));last=time.monotonic()
        cmd=['curl','-L','--max-time','45','--silent','--show-error','--write-out','\nHTTPSTATUS:%{http_code}',url]
        if body:cmd+=['-H','Content-Type: application/json','--data-binary',body]
        p=subprocess.run(cmd,capture_output=True)
        data,_,status=p.stdout.rpartition(b'\nHTTPSTATUS:')
        log={'url':url,'http_status':status.decode(errors='replace'),'exit_code':p.returncode,'bytes':len(data)}
        with (OUT/'metadata-request-log.jsonl').open('a') as file:file.write(json.dumps(log)+'\n')
        if status==b'429':
            if host=='api.semanticscholar.org':
                blocked_hosts.add(host);return b''
            save();(OUT/'metadata-progress.json').write_text(json.dumps({'status':'waiting_rate_limit','http_status':429,'retry_after_seconds':1800,'service':url.split('/')[2]})+'\n')
            print('HTTP 429: stopped requests; resume after cooldown.',flush=True);raise SystemExit(75)
        if p.returncode:return b''
        if data.startswith(b'<?xml') or data.startswith(b'['):path.write_bytes(data)
        return data
    def update(p,title,abstract,url,data,arxiv=None):
        if title:
            if p.get('title') and re.sub('[^a-z0-9]','',p['title'].lower())!=re.sub('[^a-z0-9]','',title.lower()):
                p.setdefault('released_title',p['title']);p['metadata_notes']='Fetched title differs from released target title; identity needs review.'
            p['title']=title
        if abstract:p['abstract']=abstract
        if arxiv:p['identifiers']['arxiv']=arxiv
        p['metadata_status']='ready' if p.get('title') and p.get('abstract') else 'partial'
        source={'url':url,'source_sha256':sha(data)}
        if source not in p['sources']:p['sources'].append(source)
    # S2 supports free batch metadata retrieval; missing abstracts remain null.
    s2=[p for p in papers.values() if 's2' in p['identifiers'] and (not p.get('abstract') or ('arxiv' not in p['identifiers'] and 'open_access_url' not in p))]
    for offset in range(0,len(s2),40):
        batch=s2[offset:offset+40];url='https://api.semanticscholar.org/graph/v1/paper/batch?fields=title,abstract,externalIds,openAccessPdf'
        data=request(url,json.dumps({'ids':[p['identifiers']['s2'] for p in batch]}))
        try:entries=json.loads(data)
        except Exception:entries=[]
        if isinstance(entries,list) and len(entries)==len(batch):
            for p,e in zip(batch,entries):
                if e:
                    update(p,e.get('title'),e.get('abstract'),url,data,(e.get('externalIds') or {}).get('ArXiv'))
                    p['open_access_url']=(e.get('openAccessPdf') or {}).get('url')
        save()
    namespace={'a':'http://www.w3.org/2005/Atom'}
    todo=[p for p in papers.values() if 'arxiv' in p['identifiers'] and not p.get('abstract')]
    # Prefer bulk requests; retry smaller groups only when the bulk response fails.
    queue=[todo[i:i+200] for i in range(0,len(todo),200)]
    completed=0
    while queue:
        batch=queue.pop(0);ids={re.sub(r'v\d+$','',p['identifiers']['arxiv']):p for p in batch}
        url='https://arxiv.org/api/query?id_list='+','.join(ids)+'&max_results='+str(len(ids))
        data=request(url);parsed=0
        try:
            tree=ET.fromstring(data)
            for e in tree.findall('a:entry',namespace):
                eid=re.sub(r'v\d+$','',e.findtext('a:id',default='',namespaces=namespace).rsplit('/abs/',1)[-1])
                if eid not in ids:continue
                title=e.findtext('a:title',default='',namespaces=namespace).strip();abstract=e.findtext('a:summary',default='',namespaces=namespace).strip()
                if title and abstract:update(ids[eid],title,abstract,url,data);parsed+=1
        except ET.ParseError:pass
        missing=[p for p in batch if not p.get('abstract')]
        if missing and len(batch)>10:
            size=40 if len(batch)>40 else 10;queue.extend([missing[i:i+size] for i in range(0,len(missing),size)])
        else:
            for p in missing:p['metadata_status']='partial' if p.get('title') else 'unavailable'
        completed+=1
        if completed%5==0 or not queue:save();print('batches',completed,'queue',len(queue),'ready',sum(p['metadata_status']=='ready' for p in papers.values()),'/',len(papers),flush=True)
    save()
    (OUT/'metadata-progress.json').write_text(json.dumps({'status':'complete_on_available_responses','metadata_counts':dict(Counter(p['metadata_status'] for p in papers.values())),'rate_limited_hosts':sorted(blocked_hosts)})+'\n')

if __name__=='__main__':main()
