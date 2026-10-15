"""Resumable full-release text collection and periodic automatic remeasurement.

One HTTP request starts at most once per 3.2 seconds. Raw HTML/PDF is temporary;
compressed extracted views, source hashes and section audits are retained. Stops
before exhausting local disk. No tokens, API keys, LLMs, or manual review calls.
"""
import argparse,gzip,hashlib,json,os,re,shutil,subprocess,sys,time
from collections import Counter
from pathlib import Path
from section_text import split_html,split_pdf
from measure_terms import ROOT,split_references

OUT=ROOT/'release-run';CACHE=OUT/'cache/bodies';TMP=OUT/'cache/current-download'
RUNNER=OUT/'collection-progress.json'
def jl(path):return [json.loads(x) for x in path.read_text().splitlines() if x]
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--limit',type=int);ap.add_argument('--no-refresh',action='store_true');args=ap.parse_args()
    CACHE.mkdir(parents=True,exist_ok=True);TMP.mkdir(parents=True,exist_ok=True)
    papers=jl(OUT/'papers.jsonl');pby={p['paper_id']:p for p in papers}
    path=OUT/'fulltexts.jsonl'
    records={p['paper_id']:p for p in jl(path)} if path.exists() else {}
    pilot={p['paper_id']:p for p in jl(ROOT/'fulltexts.jsonl')}
    for p in papers:
        pid=p['paper_id'];records.setdefault(pid,pilot.get(pid,{'paper_id':pid,'status':'pending'}))
    last=0;processed=0
    def save(state):
        tmp=path.with_suffix('.writing');tmp.write_text(''.join(json.dumps(records[k],ensure_ascii=False)+'\n' for k in sorted(records)));tmp.replace(path)
        counts=Counter(x['status'] for x in records.values())
        status={'status':state,'counts':dict(counts),'target_records':len(records),'remaining':counts['pending'],
                'process_id':os.getpid(),
                'processed_this_run':processed,'rate_limit_seconds':3.2,'free_disk_bytes':shutil.disk_usage(OUT).free,
                'raw_sources':'temporary downloads deleted after extraction; source hashes retained',
                'text_storage':'gzip JSON with bibliography-free body, stricter body and section audit',
                'refresh_every_new_articles':250,'no_paid_token_calls':True}
        RUNNER.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(status),flush=True)
    def refresh():
        if not args.no_refresh:
            subprocess.run([sys.executable,str(ROOT/'measure_release.py')],check=True)
            subprocess.run([sys.executable,str(ROOT/'validate_release.py')],check=True)
    def fetch(url,suffix):
        nonlocal last
        time.sleep(max(0,3.2-(time.monotonic()-last)));last=time.monotonic()
        file=TMP/('source.'+suffix);file.unlink(missing_ok=True)
        proc=subprocess.run(['curl','-L','--silent','--show-error','--fail','--max-time','60','--max-filesize','125829120',url,'-o',str(file)],capture_output=True,text=True)
        data=file.read_bytes() if file.exists() else b'';file.unlink(missing_ok=True)
        if 'error: 429' in proc.stderr and url.startswith('https://arxiv.org/'):
            save('waiting_rate_limit')
            print('HTTP 429: stopped requests; driver will resume after cooldown.',flush=True)
            raise SystemExit(75)
        return data,{'url':url,'exit_code':proc.returncode,'error':proc.stderr[:400],'bytes':len(data),'sha256':sha(data)}
    save('running')
    # The queue is frozen independently of query vocabulary and lexical scores.
    queue=sorted((p for p in papers if records[p['paper_id']]['status']=='pending'),key=lambda p:sha(('release-bodies-v1|'+p['paper_id']).encode()))
    for p in queue:
        if args.limit is not None and processed>=args.limit:save('checkpoint');refresh();return
        if shutil.disk_usage(OUT).free<10*1024**3:save('stopped_low_disk');refresh();return
        pid=p['paper_id'];arxiv=p['identifiers'].get('arxiv');record={'paper_id':pid,'status':'unavailable','requests':[]}
        public_url=p.get('open_access_url')
        if not arxiv and not (public_url and public_url.startswith('https://')):
            record['reason']='No public full-text URL in frozen metadata; no target substitution.';records[pid]=record;processed+=1;continue
        htmlurl='https://arxiv.org/html/'+arxiv if arxiv else None
        body=strict=None;rwinfo={};rawhash=None;fmt=None
        if arxiv:
            data,request=fetch(htmlurl,'html');record['requests'].append(request)
            if request['exit_code']==0 and b'</html>' in data[-8192:].lower() and b'ltx_bibliography' in data and b'</article>' in data:
                body,strict,rwinfo=split_html(data.decode('utf-8',errors='replace'));rawhash=sha(data);fmt='html'
                if len(re.findall('[A-Za-z]{3,}',body))<200 or not rwinfo['bibliography_elements']:body=strict=None
        if body is None:
            pdfurl='https://arxiv.org/pdf/'+arxiv if arxiv else public_url
            data,request=fetch(pdfurl,'pdf');record['requests'].append(request)
            if request['exit_code']==0 and data.startswith(b'%PDF-') and b'%%EOF' in data[-4096:]:
                pdf=TMP/'extract.pdf';txt=TMP/'extract.txt';pdf.write_bytes(data)
                proc=subprocess.run(['pdftotext','-enc','UTF-8','-nopgbrk',str(pdf),str(txt)],capture_output=True,text=True)
                if proc.returncode==0:
                    raw=txt.read_text();body,refs,refinfo=split_references(raw)
                    if body is not None:
                        strict,rwinfo=split_pdf(body);rwinfo['bibliography_split']=refinfo
                        rawhash=sha(data);fmt='pdf'
                        if len(re.findall('[A-Za-z]{3,}',body))<200:body=strict=None
                pdf.unlink(missing_ok=True);txt.unlink(missing_ok=True)
        if body is not None:
            content={'body_no_references':body,'body_no_references_no_related_work':strict,'related_work':rwinfo,'source_sha256':rawhash}
            dest=CACHE/(sha(pid.encode())+'.json.gz');encoded=json.dumps(content,ensure_ascii=False).encode()
            with gzip.GzipFile(filename=str(dest),mode='wb',mtime=0) as gz:gz.write(encoded)
            record.update({'status':'ready','format':fmt,'url':htmlurl if fmt=='html' else pdfurl,'source_sha256':rawhash,
                           'body_bundle_path':str(dest.relative_to(ROOT)),'body_bundle_sha256':sha(dest.read_bytes()),
                           'related_work_split_status':rwinfo['status'],'body_characters':len(body),'strict_characters':len(strict) if strict is not None else None})
        else:record['reason']='No complete public article with reliably separated bibliography obtained; HTTP/extraction details retained.'
        records[pid]=record;processed+=1
        if processed%25==0:save('running')
        if processed%250==0:refresh()
    save('complete');refresh()

if __name__=='__main__':main()
