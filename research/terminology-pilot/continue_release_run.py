"""Unattended continuation of the user's authorized run; no scheduler or LLM.

Writes files in this task only. Rate limits cause 30-minute pauses, not failed
zero scores. The driver can be stopped by its recorded process ID.
"""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parent;OUT=ROOT/'release-run'
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--sources',type=Path,required=True);ap.add_argument('--initial-delay',type=int,default=1800);args=ap.parse_args()
    def status(stage,**kw):
        (OUT/'driver-progress.json').write_text(json.dumps({'process_id':os.getpid(),'stage':stage,**kw},ensure_ascii=False,indent=2)+'\n')
    names=['run_release_metadata.py','measure_release.py','automatic_terms.py','section_text.py','measure_terms.py','collect_release_bodies.py','validate_release.py',
           'automatic-term-config.v1.json','stopwords.v1.json','related-work-boundaries.v1.json','reference-boundaries.v1.json']
    lockpath=OUT/'runner-code-lock.json'
    if not lockpath.exists():lockpath.write_text(json.dumps({n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names},indent=2)+'\n')
    locked=json.loads(lockpath.read_text())
    def run(script,*extra):
        if any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in locked.items()):
            status('stopped_rules_changed');return 92
        return subprocess.run([sys.executable,str(ROOT/script),*map(str,extra)]).returncode
    next_metadata=time.monotonic()+args.initial_delay;metadata_done=False
    # arXiv's metadata API and article endpoints can have different limits.
    # Collect articles while waiting for the API, using one request stream.
    while True:
        if not metadata_done and time.monotonic()>=next_metadata:
            status('metadata');code=run('run_release_metadata.py','--sources',args.sources)
            if code==75:next_metadata=time.monotonic()+1800
            elif code:status('failed_metadata',exit_code=code);return
            else:metadata_done=True
            status('measure_metadata');code=run('measure_release.py')
            if not code:code=run('validate_release.py')
            if code:status('failed_measurement',exit_code=code);return
        status('fulltexts',metadata_complete=metadata_done,next_metadata_retry_seconds=max(0,int(next_metadata-time.monotonic())) if not metadata_done else None)
        code=run('collect_release_bodies.py','--limit',250)
        if code==75:
            run('measure_release.py');run('validate_release.py')
            status('cooldown_after_fulltext_429',seconds=1800);time.sleep(1800);continue
        if code:status('failed_fulltexts',exit_code=code);return
        progress=json.loads((OUT/'collection-progress.json').read_text())
        if progress['status']=='complete':
            if metadata_done:status('complete');return
            status('cooldown_before_final_metadata',seconds=max(0,int(next_metadata-time.monotonic())))
            time.sleep(max(0,next_metadata-time.monotonic()));continue
        if progress['status']!='checkpoint':status(progress['status']);return

if __name__=='__main__':main()
