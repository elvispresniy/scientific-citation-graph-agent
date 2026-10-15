"""Section-based exclusion, independent of query and metric scores.

Only explicitly labelled reviews of prior literature are removed. Background
alone is retained. Mixed headings (e.g. Introduction and Related Work) are
flagged: the whole labelled section is excluded, not claimed to be own-work text.
"""
import re
from html.parser import HTMLParser

VERSION = 'explicit-related-work-sections-v1'
REVIEW = re.compile(r'\b(?:related\s+(?:works?|literature|studies)|prior\s+works?|previous\s+works?|literature\s+review)\b', re.I)
MIXED = re.compile(r'introduction|preliminar|background|discussion|contributions?|comparison', re.I)

def is_review_heading(title):
    return bool(REVIEW.search(title))

class ArticleParser(HTMLParser):
    """Match arXiv get_text(' ', strip=True), retaining structural section spans."""
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[]; self.parts=[]; self.sections=[]; self.headings=[];self.bibliographies=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);classes=set(a.get('class','').split())
        parent_active=any(x['article'] for x in self.stack)
        article=tag=='article' and 'ltx_document' in classes
        if parent_active and 'ltx_bibliography' in classes:self.bibliographies+=1
        skip=(self.stack and self.stack[-1]['skip']) or tag in {'script','style','nav','button','annotation'} or bool(classes & {'ltx_TOC','ltx_page_header','ltx_page_footer','ltx_bibliography'})
        node={'tag':tag,'article':article,'active':parent_active or article,'skip':bool(skip),'start':len(self.parts),'id':a.get('id')}
        if node['active'] and not skip:
            if tag=='section':
                self.sections.append(node);node['section']=True
            if re.fullmatch('h[1-6]',tag):
                self.headings.append(node);node['heading']=True
        if tag not in self.VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        match=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i]['tag']==tag),None)
        if match is None:return
        for node in self.stack[match:]:
            node['end']=len(self.parts)
            if node.get('heading'):
                node['title']=' '.join(self.parts[node['start']:node['end']])
                section=next((s for s in reversed(self.stack[:self.stack.index(node)]) if s.get('section')),None)
                if section is not None and 'title' not in section:section['title']=node['title']
        del self.stack[match:]
    def handle_data(self,data):
        if self.stack and self.stack[-1]['active'] and not self.stack[-1]['skip'] and data.strip():self.parts.append(data.strip())

def split_html(html):
    parser=ArticleParser();parser.feed(html);parser.close()
    body=' '.join(parser.parts)
    selected=[]
    for s in parser.sections:
        if is_review_heading(s.get('title','')) and 'end' in s:
            if not any(x['start']<=s['start'] and s['end']<=x['end'] for x in selected):selected.append(s)
    # Unsectioned review headings cannot be silently interpreted as absent.
    uncovered=[h for h in parser.headings if is_review_heading(h.get('title','')) and not any(s['start']<=h['start']<s['end'] for s in selected)]
    info={'version':VERSION,'format':'html','status':'ambiguous' if uncovered else ('removed' if selected else 'no_explicit_section'),
          'bibliography_elements':parser.bibliographies,
          'sections':[{'heading':s['title'],'html_id':s['id'],'mixed_heading':bool(MIXED.search(s['title'])),
                       'start_node':s['start'],'end_node':s['end'],'removed_characters':len(' '.join(parser.parts[s['start']:s['end']]))} for s in selected],
          'uncovered_headings':[h['title'] for h in uncovered]}
    if uncovered:return body,None,info
    keep=[True]*len(parser.parts)
    for s in selected:keep[s['start']:s['end']]=[False]*(s['end']-s['start'])
    return body,' '.join(x for x,k in zip(parser.parts,keep) if k),info

def pdf_candidates(text):
    """Candidate headings, not prose mentions; offsets are in extracted body."""
    lines=text.splitlines(keepends=True);positions=[];pos=0
    for line in lines:positions.append(pos);pos+=len(line)
    out=[]
    for i,line in enumerate(lines):
        title=line.strip()
        title=re.sub(r'R\s+ELATED\s+W\s*ORKS?', 'RELATED WORK',title)
        if len(title)>110 or not is_review_heading(title):continue
        # Restrict to actual short heading syntax; no sentence-level mentions.
        m=re.fullmatch(r'(?:(\d+(?:\.\d+)*|[IVX]+(?:-[A-Z])?|[A-Z](?:\.\d+)*)\.?\s+)?((?:(?:Additional|Further|Other|Overview of|Introduction and|Background and|Preliminaries and|Discussion and)\s+)?(?:Related\s+(?:Works?|Literature|Studies)|Prior\s+Works?|Previous\s+Works?|Literature\s+Review)(?:\s+(?:and\s+(?:Background|Preliminaries)|on\s+[^.!?]+))?)',title,re.I)
        if not m:continue
        number=m.group(1)
        if not number and not title[0].isupper():continue
        start=positions[i]
        if not number:
            prev=next((j for j in range(i-1,max(-1,i-4),-1) if lines[j].strip()),None)
            if prev is not None and re.fullmatch(r'(?:\d+(?:\.\d+)*|[IVX]+(?:-[A-Z])?)\.?',lines[prev].strip()):
                number=lines[prev].strip().rstrip('.');start=positions[prev]
        out.append({'heading':title,'number':number,'start':start,'heading_end':positions[i]+len(line),'line':i})
    return out,lines,positions

def split_pdf(text,override=None):
    candidates,lines,positions=pdf_candidates(text)
    ranges=[];sections=[];ambiguous=[]
    if override is not None:
        ranges=override['ranges'];sections=override['sections']
    else:
        for c in candidates:
            num=c['number'];end=None;next_heading=None
            if num:
                depth=num.count('.')+num.count('-')
                for j in range(c['line']+1,len(lines)):
                    title=lines[j].strip()
                    if not title:continue
                    # Heading may have its number on a separate line.
                    m=re.fullmatch(r'(\d+(?:\.\d+)*|[IVX]+(?:-[A-Z])?|[A-Z](?:\.\d+)*)\.?\s+([A-Z][^\n]{1,100})',title)
                    if not m and re.fullmatch(r'(?:\d+(?:\.\d+)*|[IVX]+(?:-[A-Z])?)\.?',title):
                        k=next((k for k in range(j+1,min(len(lines),j+4)) if lines[k].strip()),None)
                        if k is not None and re.fullmatch(r'[A-Z][A-Za-z :,&()–-]{2,95}',lines[k].strip()):
                            m=re.fullmatch(r'(\S+)\s+(.+)',title.rstrip('.')+' '+lines[k].strip())
                    if m:
                        nxt=m.group(1).rstrip('.')
                        # Do not confuse a displayed numbered equation/list with a section.
                        def family(value):
                            return 'decimal' if value[0].isdigit() else ('roman' if re.fullmatch('[IVX]+',value.split('-')[0]) else 'appendix')
                        same_family=family(num)==family(nxt)
                        def order(value):
                            if family(value)=='decimal':return tuple(map(int,value.split('.')))
                            roman={'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}
                            return (roman.get(value.split('-')[0],ord(value[0])),)
                        if same_family and order(nxt)>order(num) and nxt.count('.')+nxt.count('-')<=depth:
                            end=positions[j];next_heading=title;break
                    if re.fullmatch(r'(?:References|Bibliography|Appendix(?:\s+.*)?|Supplementary(?:\s+.*)?)',title,re.I):
                        end=positions[j];next_heading=title;break
            if end is None:
                ambiguous.append(c);continue
            ranges.append([c['start'],end]);sections.append({**c,'end':end,'next_heading':next_heading,'mixed_heading':bool(MIXED.search(c['heading']))})
    info={'version':VERSION,'format':'pdf','status':'ambiguous' if ambiguous else ('removed' if ranges else 'no_explicit_section'),
          'sections':sections,'ranges':ranges,'ambiguous_candidates':ambiguous,'explicit_override':override is not None}
    if ambiguous:return None,info
    chunks=[];last=0
    for start,end in sorted(ranges):
        if start<last:continue
        assert 0<=start<end<=len(text)
        chunks.append(text[last:start]);last=end
    chunks.append(text[last:])
    return '\n'.join(chunks) if ranges else text,info
