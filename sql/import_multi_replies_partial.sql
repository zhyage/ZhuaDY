-- Import Round 005 normalized replies for pilot-20261030-01.
-- Run inside the Postgres container after copying the CSVs to /tmp/multi-20261104-01/replies_partial/.
-- Inputs:
--   replies.csv                 one row per reply (normalized; no nickname/UID/cookie)
--   replies_quality.csv         one row per thread
--   replies_quality_video.csv   one aggregate row per video (thread_id='__replies__')
--   worker_jobs.csv             one row per video job

BEGIN;

CREATE TEMP TABLE reply_import (
    comment_id text,
    aweme_id text,
    thread_root_id text,
    reply_to_comment_id text,
    depth text,
    is_orphan text,
    text text,
    created_at text,
    digg_count text,
    reply_count text,
    is_pinned text,
    is_author_liked text,
    ip_province text,
    is_author text,
    is_thread_author text,
    author_hash text,
    hash_version text,
    label_text text,
    label_texts text,
    is_creator_label text,
    source text,
    raw_sha256 text,
    raw_page text,
    run_id text
);

\copy reply_import FROM '/tmp/multi-20261104-01/replies_partial/replies.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO comment (
    comment_id, aweme_id, thread_root_id, reply_to_comment_id, depth, is_orphan,
    text, created_at, digg_count, reply_count, is_pinned, is_author_liked,
    ip_province, is_author, is_thread_author, author_hash, hash_version,
    label_text, label_texts, is_creator_label, source, raw_sha256, raw_page, run_id
)
SELECT
    comment_id,
    aweme_id,
    NULLIF(thread_root_id, ''),
    NULLIF(reply_to_comment_id, ''),
    NULLIF(depth, '')::integer,
    COALESCE(NULLIF(is_orphan, '')::boolean, false),
    COALESCE(NULLIF(text, ''), ''),
    NULLIF(created_at, '')::timestamptz,
    NULLIF(digg_count, '')::bigint,
    NULLIF(reply_count, '')::bigint,
    NULLIF(is_pinned, '')::boolean,
    NULLIF(is_author_liked, '')::boolean,
    NULLIF(ip_province, ''),
    NULLIF(is_author, '')::boolean,
    NULLIF(is_thread_author, '')::boolean,
    NULLIF(author_hash, ''),
    COALESCE(NULLIF(hash_version, ''), 'v1'),
    NULLIF(label_text, ''),
    NULLIF(label_texts, '')::jsonb,
    NULLIF(is_creator_label, '')::boolean,
    COALESCE(NULLIF(source, ''), 'reply'),
    NULLIF(raw_sha256, ''),
    NULLIF(raw_page, ''),
    NULLIF(run_id, '')
FROM reply_import
ON CONFLICT (comment_id) DO UPDATE SET
    aweme_id = EXCLUDED.aweme_id,
    thread_root_id = EXCLUDED.thread_root_id,
    reply_to_comment_id = EXCLUDED.reply_to_comment_id,
    depth = EXCLUDED.depth,
    is_orphan = EXCLUDED.is_orphan,
    text = EXCLUDED.text,
    created_at = EXCLUDED.created_at,
    digg_count = EXCLUDED.digg_count,
    reply_count = EXCLUDED.reply_count,
    is_pinned = EXCLUDED.is_pinned,
    is_author_liked = EXCLUDED.is_author_liked,
    ip_province = EXCLUDED.ip_province,
    is_author = EXCLUDED.is_author,
    is_thread_author = EXCLUDED.is_thread_author,
    author_hash = EXCLUDED.author_hash,
    hash_version = EXCLUDED.hash_version,
    label_text = EXCLUDED.label_text,
    label_texts = EXCLUDED.label_texts,
    is_creator_label = EXCLUDED.is_creator_label,
    source = EXCLUDED.source,
    raw_sha256 = EXCLUDED.raw_sha256,
    raw_page = EXCLUDED.raw_page,
    fetched_at = now(),
    run_id = EXCLUDED.run_id;

CREATE TEMP TABLE reply_quality_import (
    run_id text,
    aweme_id text,
    thread_id text,
    expected_total text,
    fetched text,
    unique_count text,
    duplicates text,
    orphan_edges text,
    depth3 text,
    coverage text,
    stop_reason text
);

\copy reply_quality_import FROM '/tmp/multi-20261104-01/replies_partial/replies_quality.csv' WITH (FORMAT csv, HEADER true, NULL '')
\copy reply_quality_import FROM '/tmp/multi-20261104-01/replies_partial/replies_quality_video.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO quality_metric (
    run_id, aweme_id, thread_id, expected_total, fetched, unique_count,
    duplicates, orphan_edges, depth3, coverage, stop_reason
)
SELECT
    run_id,
    aweme_id,
    thread_id,
    NULLIF(expected_total, '')::integer,
    NULLIF(fetched, '')::integer,
    NULLIF(unique_count, '')::integer,
    COALESCE(NULLIF(duplicates, '')::integer, 0),
    COALESCE(NULLIF(orphan_edges, '')::integer, 0),
    COALESCE(NULLIF(depth3, '')::integer, 0),
    NULLIF(coverage, '')::double precision,
    NULLIF(stop_reason, '')
FROM reply_quality_import
ON CONFLICT (run_id, aweme_id, thread_id) DO UPDATE SET
    expected_total = EXCLUDED.expected_total,
    fetched = EXCLUDED.fetched,
    unique_count = EXCLUDED.unique_count,
    duplicates = EXCLUDED.duplicates,
    orphan_edges = EXCLUDED.orphan_edges,
    depth3 = EXCLUDED.depth3,
    coverage = EXCLUDED.coverage,
    stop_reason = EXCLUDED.stop_reason,
    computed_at = now();

CREATE TEMP TABLE worker_job_import (
    job_id text,
    run_id text,
    aweme_id text,
    threads text,
    status text,
    attempt text,
    result_path text
);

\copy worker_job_import FROM '/tmp/multi-20261104-01/replies_partial/worker_jobs.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO worker_job (
    job_id, run_id, aweme_id, threads, status, attempt, result_path
)
SELECT
    job_id,
    run_id,
    aweme_id,
    threads::jsonb,
    status,
    COALESCE(NULLIF(attempt, '')::integer, 1),
    NULLIF(result_path, '')
FROM worker_job_import
ON CONFLICT (job_id) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    aweme_id = EXCLUDED.aweme_id,
    threads = EXCLUDED.threads,
    status = EXCLUDED.status,
    attempt = EXCLUDED.attempt,
    result_path = EXCLUDED.result_path,
    updated_at = now();

UPDATE run
SET notes = 'Multi-account: 30 videos; top-level 5182; partial replies 1125; 178 threads complete; 51 threads blocked (wrapper_not_ready); import partial; remaining round pending'
WHERE run_id = 'multi-20261104-01';

COMMIT;
