from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .collect import collect,probe,write_report
from .local import Texts,index_legacy,index_parquet,prepare_seeds
from .s2 import S2
from .store import Store


def main():
    parser = argparse.ArgumentParser(description='Local citation graph, API, and factory seed selection')
    parser.add_argument('--db',type=Path,required=True)
    sub = parser.add_subparsers(dest='command',required=True)
    factory = sub.add_parser('factory-step1', help='Select factory seeds from a read-only local snapshot')
    factory.add_argument('--config', type=Path, required=True)
    factory.add_argument('--output', type=Path, required=True)
    factory.add_argument('--sampler', choices=['sequential', 'gumbel-native'], default='sequential')
    factory.add_argument('--native-binary', type=Path,
                         default=Path(__file__).resolve().parents[1] / 'gumbel_topk/build/gumbel_topk')
    factory.add_argument('--threads', type=int, default=1)
    factory.add_argument('--repeat', type=int, default=1, help='Native kernel repetitions; same candidates and keys')
    index = sub.add_parser('index')
    index.add_argument('--parquet',type=Path,required=True)
    index.add_argument('--merger',type=Path,required=True)
    index.add_argument('--legacy-root',type=Path)
    index.add_argument('--snapshot-id',required=True)
    seeds = sub.add_parser('seeds')
    seeds.add_argument('--count',type=int,default=3)
    sub.add_parser('report')
    text = sub.add_parser('text')
    text.add_argument('paper_id')
    unarxive = sub.add_parser('import-unarxive')
    unarxive.add_argument('--archive',type=Path,required=True)
    unarxive.add_argument('--snapshot-id',required=True)
    unarxive.add_argument('--expected-md5')
    unarxive.add_argument('--max-candidates',type=int,default=30000)
    unarxive.add_argument('--max-nodes',type=int,default=10000)
    unarxive.add_argument('--max-document-mib',type=int,default=1536)
    unarxive.add_argument('--seconds',type=int,default=2400)
    unarxive.add_argument('--category-prefix',action='append',default=None)
    for command in ('probe','collect'):
        run = sub.add_parser(command)
        run.add_argument('--seconds',type=int,default=180 if command=='probe' else 3600)
        run.add_argument('--max-requests',type=int,default=12 if command=='probe' else 2500)
        run.add_argument('--retries',type=int,default=2)
        run.add_argument('--interval',type=float,default=1.1)
        if command=='collect':
            run.add_argument('--max-expanded',type=int,default=300)
            run.add_argument('--max-nodes',type=int,default=10000)
            run.add_argument('--max-depth',type=int,default=2)
            run.add_argument('--pages-per-direction',type=int,default=3)
    server = sub.add_parser('serve')
    server.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    for name in ('seconds','max_requests','interval','max_expanded','max_nodes','max_depth','pages_per_direction','count',
                 'max_candidates','max_document_mib'):
        if hasattr(args,name) and getattr(args,name)<=0:
            parser.error(f'{name} must be positive')
    if hasattr(args,'retries') and not 0<=args.retries<=3:
        parser.error('retries must be between 0 and 3')
    if args.command == 'factory-step1':
        from .factory_step1 import Config, run
        try:
            config = Config.load(args.config)
            if args.sampler == 'gumbel-native':
                from .gumbel_step1 import run as run_native
                result = run_native(args.db, config, args.output, binary=args.native_binary,
                                    threads=args.threads, repeat=args.repeat)
            else:
                if args.threads != 1 or args.repeat != 1:
                    raise ValueError('--threads/--repeat require --sampler gumbel-native')
                result = run(args.db, config, args.output)
        except (ValueError, TypeError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    store = Store(args.db)
    try:
        if args.command=='index':
            if store.setting('snapshot_id') not in (None,args.snapshot_id):
                parser.error('Use a new database for a different snapshot')
            store.setting('snapshot_id',args.snapshot_id)
            store.setting('merger_path',str(args.merger.resolve()))
            manifest = {'parquet':index_parquet(store,args.parquet)}
            if args.legacy_root:
                manifest['legacy'] = index_legacy(store,args.legacy_root)
            store.setting('local_manifest',manifest)
            result = manifest
        elif args.command=='seeds':
            result = prepare_seeds(store,args.count)
        elif args.command=='text':
            result = Texts(store).get(args.paper_id)
            result['characters'] = len(result.pop('text'))
        elif args.command=='report':
            if store.setting('backend')=='unarxive':
                from .unarxive import graph_report
                result=graph_report(store)
            else:
                result = write_report(store)
        elif args.command=='import-unarxive':
            from .unarxive import build
            if store.setting('snapshot_id') not in (None,args.snapshot_id):
                parser.error('Use a new database for a different snapshot')
            md5,sha256=hashlib.md5(),hashlib.sha256()
            with args.archive.open('rb') as stream:
                for block in iter(lambda:stream.read(8*1024**2),b''):
                    md5.update(block)
                    sha256.update(block)
            if args.expected_md5 and md5.hexdigest()!=args.expected_md5:
                parser.error('Archive MD5 does not match the published checksum')
            store.setting('snapshot_id',args.snapshot_id)
            store.setting('archive_provenance',{'path':str(args.archive.resolve()),'md5':md5.hexdigest(),
                                              'sha256':sha256.hexdigest(),'published_md5_verified':bool(args.expected_md5)})
            result=build(store,args.archive,max_candidates=args.max_candidates,max_nodes=args.max_nodes,
                         max_document_bytes=args.max_document_mib*1024**2,seconds=args.seconds,
                         categories=tuple(args.category_prefix or ['cs.']))
        elif args.command in ('probe','collect'):
            if not (store.setting('seeds') or {}).get('seeds'):
                parser.error('Prepare seeds first')
            client = S2(store.path.parent/'s2-cache',args.seconds,args.max_requests,args.interval,args.retries)
            result = probe(store,client) if args.command=='probe' else collect(store,client,args.max_expanded,args.max_nodes,args.max_depth,args.pages_per_direction)
            if args.command=='probe':
                write_report(store)
        elif args.command=='serve':
            import uvicorn
            from .api import create_app
            store.close()
            store = None
            uvicorn.run(create_app(args.db),host='127.0.0.1',port=args.port,workers=1)
            return
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        if store:
            store.close()


if __name__=='__main__':
    main()
