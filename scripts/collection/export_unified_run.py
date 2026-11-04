#!/usr/bin/env python3
"""Export the unified 10-video run: video + comments + replies + downloads."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "pilot-unified-20261031-01"
OUT = ROOT / "exports" / RUN_ID
SOURCE = ROOT / "data" / "pilot" / RUN_ID / "export_source"
PARQUET = OUT / "parquet"
SAMPLES = OUT / "samples"
DB = ["docker", "exec", "dtk-postgres-1", "psql", "-U", "dtk", "-d", "douyin_research", "-X", "-q"]

Q = {
"videos": f"""SELECT run_id, aweme_id, author_sec_uid, author_nickname, is_target_author,
 caption, created_at, duration_ms, digg_count, comment_count, share_count, collect_count,
 play_count, is_deleted, is_private, web_url, kind, tags, recommend_count,
 media_width, media_height, media_format, media_size_bytes, media_bitrate,
 author_certification, author_favoriting_count, collected_at, raw_sha256, fetched_at,
 video_file_path, video_sha256, video_variant, video_bytes, video_width, video_height,
 video_format, video_duration_ms, downloaded_at, video_codec
 FROM video_snapshot WHERE run_id='{RUN_ID}' ORDER BY aweme_id""",
"comments": f"""SELECT comment_id, aweme_id, thread_root_id, reply_to_comment_id, depth,
 is_orphan, text, created_at, digg_count, reply_count, is_pinned, is_author_liked,
 ip_province, is_author, is_thread_author, author_hash, hash_version, label_text,
 is_creator_label, source, raw_sha256, fetched_at, run_id
 FROM comment WHERE run_id='{RUN_ID}'
 ORDER BY aweme_id, source, created_at NULLS LAST, comment_id""",
"reply_edges": f"""SELECT comment_id AS child_id, reply_to_comment_id AS parent_id,
 thread_root_id, depth, is_orphan, aweme_id, raw_sha256, run_id
 FROM comment WHERE run_id='{RUN_ID}' AND source='reply'
 ORDER BY aweme_id, thread_root_id, created_at NULLS LAST, comment_id""",
"quality": f"""SELECT q.run_id, q.aweme_id, q.thread_id,
 CASE WHEN q.thread_id='__top_level__' THEN 'top_level'
      WHEN q.thread_id='__replies__' THEN 'reply_video' ELSE 'reply_thread' END AS thread_kind,
 CASE WHEN q.thread_id='__top_level__' THEN NULL ELSE j.threads->>'selection' END AS selection,
 CASE WHEN q.thread_id='__top_level__' THEN NULL ELSE (j.threads->>'max_pages')::int END AS max_pages,
 q.expected_total, q.fetched, q.unique_count, q.duplicates, q.orphan_edges, q.depth3,
 q.coverage, q.stop_reason, q.computed_at
 FROM quality_metric q LEFT JOIN worker_job j
   ON j.run_id=q.run_id AND j.aweme_id=q.aweme_id
 WHERE q.run_id='{RUN_ID}' ORDER BY q.aweme_id, thread_kind, q.thread_id""",
"media": f"""SELECT run_id, aweme_id, status, codec, variant, file_path, bytes, sha256,
 width, height, format, duration_ms, bitrate, attempts, error, started_at, finished_at
 FROM media_download WHERE run_id='{RUN_ID}' ORDER BY aweme_id""",
"account": f"""SELECT run_id, signature, verified, follower_count, following_count,
 total_favorited, aweme_count, certification, favoriting_count, collected_at, raw_sha256, fetched_at
 FROM account_snapshot WHERE run_id='{RUN_ID}'""",
}
BOOL = {"videos": ["is_target_author","is_selected","is_deleted","is_private"],
        "comments": ["is_orphan","is_pinned","is_author_liked","is_author","is_thread_author","is_creator_label"],
        "reply_edges": ["is_orphan"], "quality": [], "media": [], "account": ["verified"]}
INT = {"videos": ["duration_ms","digg_count","comment_count","share_count","collect_count","play_count",
                  "recommend_count","media_width","media_height","media_size_bytes","media_bitrate",
                  "author_favoriting_count","video_bytes","video_width","video_height","video_duration_ms",
                  "pilot_rank_in_group"],
       "comments": ["depth","digg_count","reply_count"], "reply_edges": ["depth"],
       "quality": ["max_pages","expected_total","fetched","unique_count","duplicates","orphan_edges","depth3"],
       "media": ["bytes","width","height","duration_ms","bitrate","attempts"],
       "account": ["follower_count","following_count","total_favorited","aweme_count","favoriting_count"]}
TS = {"videos": ["created_at","collected_at","fetched_at","downloaded_at"],
      "comments": ["created_at","fetched_at"], "reply_edges": [],
      "quality": ["computed_at"], "media": ["started_at","finished_at"],
      "account": ["collected_at","fetched_at"]}

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def export(name, sql):
    p=SOURCE/f'{name}.csv'
    with p.open('wb') as f:
        subprocess.run(DB+['-c',f"\\copy ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true, NULL '')"],check=True,stdout=f)
    df=pd.read_csv(p,dtype=str,keep_default_na=False,na_values=[''],encoding='utf-8')
    for c in BOOL.get(name,[]):
        if c in df: df[c]=df[c].map({'true':True,'false':False,'t':True,'f':False}).astype('boolean')
    for c in INT.get(name,[]):
        if c in df: df[c]=pd.to_numeric(df[c],errors='coerce').astype('Int64')
    for c in TS.get(name,[]):
        if c in df: df[c]=pd.to_datetime(df[c],utc=True,errors='coerce')
    return df

def write(df,name):
    p=PARQUET/f'{name}.parquet'; pq.write_table(pa.Table.from_pandas(df,preserve_index=False),p,compression='zstd'); return p

def main():
    for d in (SOURCE,PARQUET,SAMPLES): d.mkdir(parents=True,exist_ok=True)
    f={n:export(n,q) for n,q in Q.items()}
    videos=f['videos']; comments=f['comments']; edges=f['reply_edges']; quality=f['quality']; media=f['media']; account=f['account']
    selected={r['aweme_id']:r for r in csv.DictReader(open(ROOT/'data/pilot'/RUN_ID/'selected_videos.csv',encoding='utf-8'))}
    videos['is_selected']=videos['aweme_id'].isin(selected).astype('boolean')
    videos['selection_reason']=videos['aweme_id'].map(lambda x:(selected.get(x) or {}).get('selection_reason'))
    videos['pilot_rank_in_group']=pd.to_numeric(videos['aweme_id'].map(lambda x:(selected.get(x) or {}).get('rank_in_group')),errors='coerce').astype('Int64')
    videos['tags']=videos['tags'].map(lambda x:json.loads(x) if isinstance(x,str) and x else [])
    videos=videos.drop(columns=['author_sec_uid','author_nickname'],errors='ignore')
    vcols=['run_id','aweme_id','is_target_author','is_selected','selection_reason','pilot_rank_in_group',
           'caption','created_at','duration_ms','digg_count','comment_count','share_count','collect_count',
           'play_count','is_deleted','is_private','web_url','kind','tags','recommend_count','media_width',
           'media_height','media_format','media_size_bytes','media_bitrate','author_certification',
           'author_favoriting_count','collected_at','raw_sha256','fetched_at','video_file_path','video_sha256',
           'video_variant','video_bytes','video_width','video_height','video_format','video_duration_ms',
           'downloaded_at','video_codec']
    videos=videos[vcols]
    ccols=['comment_id','aweme_id','thread_root_id','reply_to_comment_id','depth','is_orphan','text','created_at',
           'digg_count','reply_count','is_pinned','is_author_liked','ip_province','is_author','is_thread_author',
           'author_hash','hash_version','label_text','is_creator_label','source','raw_sha256','fetched_at','run_id']
    comments=comments[ccols]
    ecols=['child_id','parent_id','thread_root_id','depth','is_orphan','aweme_id','raw_sha256','run_id']
    edges=edges[ecols]
    qcols=['run_id','aweme_id','thread_id','thread_kind','selection','max_pages','expected_total','fetched',
           'unique_count','duplicates','orphan_edges','depth3','coverage','stop_reason','computed_at']
    quality=quality[qcols]
    mcols=['run_id','aweme_id','status','codec','variant','file_path','bytes','sha256','width','height',
           'format','duration_ms','bitrate','attempts','error','started_at','finished_at']
    media=media[mcols]
    acols=['run_id','signature','verified','follower_count','following_count','total_favorited','aweme_count',
           'certification','favoriting_count','collected_at','raw_sha256','fetched_at']
    account=account[acols]

    top=comments[comments['source']=='top_level'].sort_values(['aweme_id','created_at','comment_id'])
    top_sample=top.groupby('aweme_id',sort=False).head(100)
    rep=comments[comments['source']=='reply'].sort_values(['thread_root_id','created_at','comment_id'])
    rep_sample=rep.groupby('thread_root_id',sort=False).head(50)
    videos.to_csv(SAMPLES/'selected_videos.csv',index=False,encoding='utf-8-sig')
    media.to_csv(SAMPLES/'media_downloads.csv',index=False,encoding='utf-8-sig')
    top_sample.to_csv(SAMPLES/'comments_sample.csv',index=False,encoding='utf-8-sig')
    rep_sample.to_csv(SAMPLES/'replies_sample.csv',index=False,encoding='utf-8-sig')

    paths={n:write(df,n) for n,df in {'videos':videos,'comments':comments,'reply_edges':edges,'quality':quality,'media_downloads':media,'account':account}.items()}
    files={}
    for p in sorted(list(PARQUET.glob('*.parquet'))+list(SAMPLES.glob('*.csv'))):
        files[str(p.relative_to(OUT))]={'bytes':p.stat().st_size,'sha256':sha(p)}
    th=quality[quality['thread_kind']=='reply_thread']
    complete=th[th['stop_reason']=='complete']; maxp=th[th['stop_reason']=='max_pages']
    total_bytes=int(media.loc[media['status']=='success','bytes'].fillna(0).sum())
    author=comments[comments['is_author']==True]
    ip_top=int(comments[(comments['source']=='top_level')]['ip_province'].notna().sum())
    ip_rep=int(comments[(comments['source']=='reply')]['ip_province'].notna().sum())
    manifest={
      'export_version':'1.0','generated_at':datetime.now(timezone.utc).isoformat(),'run_id':RUN_ID,
      'row_counts':{n:int(len(df)) for n,df in {'videos':videos,'comments':comments,'reply_edges':edges,'quality':quality,'media_downloads':media,'account':account}.items()},
      'sample_row_counts':{'selected_videos':len(videos),'media_downloads':len(media),'comments_sample':len(top_sample),'replies_sample':len(rep_sample)},
      'top_level':{'rows':int((comments['source']=='top_level').sum()),'ip_nonnull':ip_top,'author_true':int((comments[(comments['source']=='top_level')]['is_author']==True).sum())},
      'replies':{'rows':len(rep),'threads':len(th),'complete':len(complete),'max_pages':len(maxp),
                 'expected_total':int(th['expected_total'].fillna(0).sum()),'unique':int(th['unique_count'].fillna(0).sum()),
                 'coverage':float(th['unique_count'].fillna(0).sum()/max(1,th['expected_total'].fillna(0).sum())),
                 'complete_expected':int(complete['expected_total'].fillna(0).sum()),'complete_unique':int(complete['unique_count'].fillna(0).sum()),
                 'complete_coverage':float(complete['unique_count'].fillna(0).sum()/max(1,complete['expected_total'].fillna(0).sum())),
                 'orphans':int((comments['is_orphan']==True).sum()),'depth_null':int(comments['depth'].isna().sum()),
                 'author_true':int(((comments['source']=='reply') & (comments['is_author']==True)).sum()),'ip_nonnull':ip_rep},
      'downloads':{'attempted':len(media),'success':int((media['status']=='success').sum()),'failed':int((media['status']=='failed').sum()),
                   'bytes':total_bytes,'GB':round(total_bytes/1e9,3),'codec_counts':{str(k):int(v) for k,v in media['codec'].value_counts().items()},
                   'duration_diff_max_ms':float((videos['video_duration_ms']-videos['duration_ms']).abs().max()) if len(videos) else None},
      'privacy':{'excluded':['account_id/sec_uid','author_sec_uid','author_nickname','unique_id','raw_page','signed URLs','cookies','headers'],
                 'note':'analysis layer; text retained; captions/tags public; media/frames local; IRB applies'},
      'incident':{'captcha':True,'worker_stopped':'~08:21Z','manual_verification':True,'resumed':'08:24:10Z',
                  'no_risk_control':True,'summary_undercount':'worker_summary normalized_rows=638; files contain 969'},
      'known_issues':['1 shallow thread hit max_pages=3 (7494177073062347557: 464 expected -> 150 unique).',
                      'complete threads: 147; complete coverage 819/822 = 99.64%.',
                      '20 orphan edges; 63 depth null.',
                      'top-level IP non-null 2034/3098; replies 911/969.',
                      'reply raw/state remain on Windows local; comment_raw only top-level.'],
      'files':files,
      'schema':{n:[{'name':f.name,'type':str(f.type)} for f in pq.read_schema(p)] for n,p in paths.items()},
    }
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    readme=f"""# Unified Export — {RUN_ID}

> 生成：{manifest['generated_at']}
> 10 条视频 + 3,098 一级评论 + 969 回复；同一 run。

| 文件 | 行数 |
|---|---:|
| parquet/videos.parquet | {len(videos)} |
| parquet/comments.parquet | {len(comments)} |
| parquet/reply_edges.parquet | {len(edges)} |
| parquet/quality.parquet | {len(quality)} |
| parquet/media_downloads.parquet | {len(media)} |
| parquet/account.parquet | {len(account)} |

- 下载：{manifest['downloads']['success']}/{manifest['downloads']['attempted']}，{manifest['downloads']['bytes']:,} bytes；codec {manifest['downloads']['codec_counts']}。
- 回复线程：{manifest['replies']['threads']}（complete {manifest['replies']['complete']} / max_pages {manifest['replies']['max_pages']}）。
- 整体回复 coverage {manifest['replies']['coverage']:.2%}；complete coverage {manifest['replies']['complete_coverage']:.2%}。
- Captcha：worker 在 08:21Z 停止，人工验证后 08:24Z resume；normalized 文件 969 行，summary 的 normalized_rows 只统计 resume 部分（638）。
- 不含 sec_uid/昵称/raw page/签名 URL/cookie/header。
"""
    (OUT/'README.md').write_text(readme,encoding='utf-8')
    print(json.dumps({'out':str(OUT),'row_counts':manifest['row_counts'],'replies':manifest['replies'],'downloads':manifest['downloads']},ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
