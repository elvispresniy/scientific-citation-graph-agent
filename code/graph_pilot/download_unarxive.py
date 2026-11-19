"""Four bounded HTTP Range transfers into one file, verified against Zenodo MD5."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

URL='https://zenodo.org/records/7752615/files/unarXive_230324_open_subset.tar.xz?download=1'
SIZE=4844918096
MD5='4e9af00b730f1b8a680e4d7a47465395'
NAME='unarXive_230324_open_subset.tar.xz'


def download(directory,seconds=1200):
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    part=directory/(NAME+'.part')
    final=directory/NAME
    checkpoint=directory/'download-state.json'
    if final.exists():
        candidate=final
    else:
        candidate=part
        if checkpoint.exists():
            state=json.loads(checkpoint.read_text())
            if state['url']!=URL or state['size']!=SIZE:
                raise ValueError('Checkpoint belongs to a different file')
        else:
            # The prefix must be a stopped, sequential transfer of this same official URL.
            prefix=part.stat().st_size if part.exists() else 0
            if prefix>SIZE:
                raise ValueError('Partial file larger than expected archive')
            length=(SIZE-prefix+3)//4
            state={'url':URL,'size':SIZE,'md5':MD5,'prefix_bytes':prefix,
                   'ranges':[{'start':start,'end':min(start+length,SIZE)-1,'complete':False}
                             for start in range(prefix,SIZE,length)] if length else []}
        stop=threading.Event()
        lock=threading.Lock()
        processes=[]
        counts={}
        deadline=time.monotonic()+seconds
        fd=os.open(part,os.O_CREAT|os.O_RDWR,0o600)

        def save():
            tmp=checkpoint.with_suffix('.writing')
            tmp.write_text(json.dumps(state,indent=2)+'\n')
            tmp.replace(checkpoint)

        def transfer(index,item):
            start,end=item['start'],item['end']
            expected=end-start+1
            header=directory/f'range-{index}.headers'
            args=['/usr/bin/curl','--fail','--location','--silent','--show-error','--connect-timeout','20',
                  '--max-time',str(max(1,int(deadline-time.monotonic()))),'--range',f'{start}-{end}',
                  '--max-filesize',str(expected),'--dump-header',str(header),URL]
            with lock:
                if stop.is_set():
                    raise RuntimeError('Download cancelled')
                proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                processes.append(proc)
            written=0
            try:
                while block:=proc.stdout.read(1024**2):
                    if stop.is_set() or written+len(block)>expected:
                        raise RuntimeError('Range cancelled or response exceeded expected size')
                    view=memoryview(block)
                    while view:
                        n=os.pwrite(fd,view,start+written)
                        if n<=0:
                            raise OSError('Short positional write')
                        written+=n
                        view=view[n:]
                    with lock:
                        counts[index]=written
                error=proc.stderr.read().decode(errors='replace')
                code=proc.wait()
                headers=header.read_text(errors='replace')
                content_ranges=re.findall(r'(?im)^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)',headers)
                if code or written!=expected or not content_ranges or tuple(map(int,content_ranges[-1]))!=(start,end,SIZE):
                    raise RuntimeError(f'Range {index} failed: curl={code},bytes={written},error={error[:300]}')
                os.fsync(fd)
                with lock:
                    item['complete']=True
                    counts.pop(index,None)
                    save()
            except BaseException:
                stop.set()
                with lock:
                    for other in processes:
                        if other.poll() is None:
                            other.terminate()
                raise
            finally:
                if proc.poll() is None:
                    proc.terminate()
                proc.wait()
                proc.stdout.close()
                proc.stderr.close()

        try:
            save()
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(transfer,i,item) for i,item in enumerate(state['ranges']) if not item['complete']]
                pending=set(futures)
                try:
                    while pending:
                        done,pending=concurrent.futures.wait(pending,timeout=30,return_when=concurrent.futures.FIRST_COMPLETED)
                        for future in done:
                            future.result()
                        with lock:
                            complete=state['prefix_bytes']+sum(r['end']-r['start']+1 for r in state['ranges'] if r['complete'])
                            progress={'downloaded_bytes':complete+sum(counts.values()),'total_bytes':SIZE,
                                      'completed_ranges':sum(r['complete'] for r in state['ranges'])}
                        print(json.dumps(progress),flush=True)
                except BaseException:
                    stop.set()
                    with lock:
                        for proc in processes:
                            if proc.poll() is None:
                                proc.terminate()
                    raise
        except BaseException:
            stop.set()
            with lock:
                for proc in processes:
                    if proc.poll() is None:
                        proc.terminate()
            raise
        finally:
            os.close(fd)
    if candidate.stat().st_size!=SIZE:
        raise ValueError('Archive size mismatch')
    md5,sha256=hashlib.md5(),hashlib.sha256()
    with candidate.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024**2),b''):
            md5.update(block)
            sha256.update(block)
    if md5.hexdigest()!=MD5:
        raise ValueError('Archive checksum mismatch; refusing to publish')
    if candidate!=final:
        part.replace(final)
    manifest={'url':URL,'bytes':SIZE,'md5':md5.hexdigest(),'sha256':sha256.hexdigest(),'verified':True}
    (directory/'archive-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=1200)
    args=parser.parse_args()
    if not 1<=args.seconds<=1800:
        parser.error('seconds must be between 1 and 1800')
    download(args.directory,args.seconds)
