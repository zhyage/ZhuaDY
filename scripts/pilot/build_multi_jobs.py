#!/usr/bin/env python3
"""Build Windows reply jobs for a multi-account selection.

Rules:
  * one deep video per account: all reply threads, max_pages=10;
  * every other selected video: top 10 threads, max_pages=3;
  * each job carries the video's author sec_uid for is_author.
"""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def now_iso(): return datetime.now(timezone.utc).isoformat()

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--run-id', default='multi-20261104-01')
    ap.add_argument('--selected', default='data/pilot/multi-20261104-01/selected_videos.csv')
    ap.add_argument('--candidates', default='data/pilot/multi-20261104-01/thread_candidates.csv')
    ap.add_argument('--out', default='data/pilot/multi-20261104-01/jobs.json')
    ap.add_argument('--summary', default='data/pilot/multi-20261104-01/jobs_summary.json')
    ap.add_argument('--deep-per-account', type=int, default=1)
    ap.add_argument('--shallow-threads', type=int, default=10)
    ap.add_argument('--deep-max-pages', type=int, default=10)
    ap.add_argument('--shallow-max-pages', type=int, default=3)
    args=ap.parse_args()

    selected=list(csv.DictReader((ROOT/args.selected).open(encoding='utf-8')))
    by_video=defaultdict(list)
    for r in csv.DictReader((ROOT/args.candidates).open(encoding='utf-8')):
        r['reply_count']=int(r.get('reply_count') or 0)
        r['digg_count']=int(r.get('digg_count') or 0)
        by_video[r['aweme_id']].append(r)
    for rows in by_video.values():
        rows.sort(key=lambda r:(-r['reply_count'],-r['digg_count'],r['comment_id']))
    by_account=defaultdict(list)
    for r in selected:
        by_account[r.get('account_label') or r.get('account_id')].append(r)
    deep_ids=set()
    for account, rows in by_account.items():
        ranked=sorted(rows,key=lambda r:(-len(by_video.get(r['aweme_id'],[])),-sum(t['reply_count'] for t in by_video.get(r['aweme_id'],[])),r['aweme_id']))
        for r in ranked[:args.deep_per_account]:
            if by_video.get(r['aweme_id']): deep_ids.add(r['aweme_id'])
    jobs=[]; summary_rows=[]; skipped=[]
    for r in selected:
        aid=r['aweme_id']; deep=aid in deep_ids
        threads=by_video.get(aid,[])
        chosen=threads if deep else threads[:args.shallow_threads]
        max_pages=args.deep_max_pages if deep else args.shallow_max_pages
        if chosen:
            jobs.append({'aweme_id':aid,'author_sec_uid':r.get('account_id'),'max_pages':max_pages,
                         'selection':'deep' if deep else 'shallow','threads':[t['comment_id'] for t in chosen]})
        else:
            skipped.append(aid)
        summary_rows.append({'account':r.get('account_label') or r.get('account_id'),'aweme_id':aid,
            'selection':'deep' if deep else 'shallow','available_threads':len(threads),
            'chosen_threads':len(chosen),'expected_replies':sum(t['reply_count'] for t in chosen),'max_pages':max_pages})
    payload={'run_id':args.run_id,'created_at':now_iso(),'jobs':jobs}
    out=ROOT/args.out; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={'run_id':args.run_id,'created_at':now_iso(),'jobs':len(jobs),
        'deep_videos':sum(1 for j in jobs if j['selection']=='deep'),
        'deep_threads':sum(len(j['threads']) for j in jobs if j['selection']=='deep'),
        'deep_expected_replies':sum(r['expected_replies'] for r in summary_rows if r['selection']=='deep'),
        'shallow_videos':sum(1 for j in jobs if j['selection']=='shallow'),
        'shallow_threads':sum(len(j['threads']) for j in jobs if j['selection']=='shallow'),
        'shallow_expected_replies':sum(r['expected_replies'] for r in summary_rows if r['selection']=='shallow'),
        'total_threads':sum(len(j['threads']) for j in jobs),
        'total_expected_replies':sum(r['expected_replies'] for r in summary_rows),
        'skipped_videos_no_threads':skipped,'accounts':list(by_account),'videos':summary_rows,
        'files':{'jobs':str(out.relative_to(ROOT))}}
    (ROOT/args.summary).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('jobs','deep_videos','deep_threads','deep_expected_replies','shallow_videos','shallow_threads','shallow_expected_replies','total_threads','total_expected_replies','skipped_videos_no_threads')},ensure_ascii=False,indent=2))
    print('accounts',summary['accounts'])
    return 0
if __name__=='__main__': raise SystemExit(main())
