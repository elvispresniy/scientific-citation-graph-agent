"""Download public target PDFs at <=1 request / 3 seconds, one connection.

Raw/extracted texts are local ignored cache; provenance is fulltexts.jsonl.
Run with the project Python 3, no model/token services are used.
"""
import hashlib
import json
import re
import subprocess
import time
from bs4 import BeautifulSoup
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/'fulltext-cache'
CACHE.mkdir(exist_ok=True)
PAPERS=[json.loads(x) for x in (ROOT/'papers.jsonl').read_text().splitlines()]
CAL=json.loads((ROOT/'calibration-pairs.json').read_text())['pairs']
PRIORITY={x['paper_id']:i for i,x in enumerate(CAL)}
LAST=0

def complete_pdf(path):
    if not path.exists(): return False
    data=path.read_bytes()
    return data.startswith(b'%PDF-') and b'%%EOF' in data[-4096:]

def complete_html(path):
    if not path.exists(): return False
    data=path.read_bytes().lower()
    return b'</html>' in data[-8192:] and b'</article>' in data

def html_text(path):
    if not path.exists(): return None
    data=path.read_bytes()
    if b'</html>' not in data[-8192:].lower() or b'</article>' not in data.lower(): return None
    soup=BeautifulSoup(data,'html.parser')
    article=soup.find('article')
    if article is None or 'ltx_document' not in (article.get('class') or []): return None
    for tag in article.select('script, style, nav, button, annotation, .ltx_TOC, .ltx_page_header, .ltx_page_footer'):
        tag.decompose()
    text=article.get_text(' ',strip=True)
    if len(re.findall(r'[A-Za-z]{3,}',text))<200: return None
    refnodes=article.select('.ltx_bibliography')
    refs='\n'.join(n.get_text(' ',strip=True) for n in refnodes)
    for node in refnodes: node.decompose()
    body=article.get_text(' ',strip=True)
    return text,body,refs, bool(refnodes)

def fetch(url,path,body=None,resume=False):
    global LAST
    time.sleep(max(0,3.1-(time.monotonic()-LAST)))
    LAST=time.monotonic()
    timeout='360' if '/pdf/' in url or url.endswith('.pdf') or '/pdf?' in url else '30'
    cmd=['curl','-L','--max-time',timeout,'--silent','--show-error',
         '--user-agent','ScientificCitationGraphTerminologyPilot/1.0',
         '--write-out','%{http_code}',url,'-o',str(path)]
    if body:
        cmd+=['-H','Content-Type: application/json','-d',body]
    if resume: cmd+=['--continue-at','-']
    result=subprocess.run(cmd,capture_output=True,text=True)
    return {'url':url,'http_status':result.stdout,'exit_code':result.returncode,'error':result.stderr[:300]}

# Semantic Scholar supplies public publisher/repository PDFs for targets without arXiv IDs.
other=[p for p in PAPERS if 'arxiv' not in p['identifiers']]
s2cache=CACHE/'s2-open-access.json'
if other and not s2cache.exists():
    fetch('https://api.semanticscholar.org/graph/v1/paper/batch?fields=title,openAccessPdf,url',s2cache,
          json.dumps({'ids':[p['identifiers']['s2'] for p in other]}))
try:
    s2=json.loads(s2cache.read_text())
    oa={p['paper_id']:(e.get('openAccessPdf') or {}).get('url') for p,e in zip(other,s2) if isinstance(e,dict)} if isinstance(s2,list) else {}
except Exception:
    oa={}

# Reviewed publisher/author sources can supplement missing Semantic Scholar URLs.
# The override retains the original target ID and records the identity evidence.
overrides_path=ROOT/'fulltext-source-overrides.v1.json'
overrides=json.loads(overrides_path.read_text()) if overrides_path.exists() else {}
for pid,entry in overrides.items():
    oa[pid]=entry['url']

existing={}
if (ROOT/'fulltexts.jsonl').exists():
    existing={r['paper_id']:r for r in map(json.loads,(ROOT/'fulltexts.jsonl').read_text().splitlines())}
rows=[]
ordered=sorted(PAPERS,key=lambda p:(PRIORITY.get(p['paper_id'],99999),p['paper_id']))
for i,p in enumerate(ordered,1):
    pid=p['paper_id']
    old=existing.get(pid,{})
    old_complete=(complete_html(ROOT/old['html_path']) and old.get('has_references_element')) if old.get('format')=='html' else (complete_pdf(ROOT/old['pdf_path']) if old.get('pdf_path') else False)
    if old.get('status')=='ready' and old_complete:
        rows.append(existing[pid]);continue
    arxiv=p['identifiers'].get('arxiv')
    key=pid.replace(':','_').replace('/','_')
    pdf=CACHE/(key+'.pdf');txt=CACHE/(key+'.txt')
    url=overrides[pid]['url'] if pid in overrides else (('https://arxiv.org/pdf/'+arxiv) if arxiv else oa.get(pid))
    row={'paper_id':pid,'status':'unavailable','url':url,'requests':[],
         'extraction':'pdftotext default reading order, UTF-8, no page breaks'}
    if pid in overrides: row['source_override']=overrides[pid]
    html=CACHE/(key+'.html')
    if arxiv and not complete_pdf(pdf):
        hurl='https://arxiv.org/html/'+arxiv
        if not html.exists(): row['requests'].append(fetch(hurl,html))
        parsed=html_text(html)
        if parsed and parsed[3]:
            text,body,refs,has_refs=parsed
            txt.write_text(text)
            bpath=CACHE/(key+'.body.txt');rpath=CACHE/(key+'.references.txt')
            bpath.write_text(body);rpath.write_text(refs)
            row.update({'status':'ready','format':'html','url':hurl,'extraction':'BeautifulSoup html.parser; arXiv ltx_document; bibliography removed structurally; math annotation duplicates removed',
                        'html_path':str(html.relative_to(ROOT)),'html_sha256':hashlib.sha256(html.read_bytes()).hexdigest(),
                        'text_path':str(txt.relative_to(ROOT)),'text_sha256':hashlib.sha256(txt.read_bytes()).hexdigest(),
                        'body_path':str(bpath.relative_to(ROOT)),'references_path':str(rpath.relative_to(ROOT)),
                        'has_references_element':has_refs,'characters':len(text)})
        elif parsed:
            row['html_warning']='HTML article has no bibliography element; conversion may be incomplete. Fall back to PDF.'
    if url and row['status']!='ready':
        if not complete_pdf(pdf):
            partial=pdf.exists() and pdf.stat().st_size>1000000 and pdf.read_bytes().startswith(b'%PDF-')
            row['requests'].append(fetch(url,pdf,resume=partial))
            if partial and row['requests'][-1]['exit_code']==33:
                row['requests'].append(fetch(url,pdf))
        if complete_pdf(pdf):
            proc=subprocess.run(['pdftotext','-enc','UTF-8','-nopgbrk',str(pdf),str(txt)],capture_output=True,text=True)
            if proc.returncode==0 and txt.exists():
                text=txt.read_text(errors='replace')
                if len(re.findall(r'[A-Za-z]{3,}',text))>=200:
                    row.update({'status':'ready','format':'pdf','pdf_path':str(pdf.relative_to(ROOT)),
                                'text_path':str(txt.relative_to(ROOT)),
                                'pdf_integrity':'PDF header and EOF marker present; pdftotext succeeded',
                                'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                'text_sha256':hashlib.sha256(txt.read_bytes()).hexdigest(),
                                'characters':len(text)})
                else:
                    row['reason']='PDF extracted fewer than 200 English word tokens; not treated as full text.'
            else:
                row['reason']='Text extraction failed: '+proc.stderr[:300]
        else:
            row['reason']='No complete PDF response: '+str(row['requests'])
    elif not url:
        row['reason']='No arXiv identifier or public PDF URL returned by Semantic Scholar.'
    rows.append(row)
    (ROOT/'fulltexts.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    print(f'{i}/{len(ordered)} ready={sum(r["status"]=="ready" for r in rows)} latest={pid} {row["status"]}',flush=True)
(ROOT/'fulltexts.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
print('Done',len(rows),'ready',sum(r['status']=='ready' for r in rows),flush=True)
