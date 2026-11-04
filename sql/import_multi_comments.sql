-- Import Stage 2 top-level comments for pilot-20261030-01.
-- Run inside the Postgres container after copying the CSVs to /tmp/pilot-20261030-01.

BEGIN;

CREATE TEMP TABLE comment_import (
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

\copy comment_import FROM '/tmp/multi-20261104-01/comments.csv' WITH (FORMAT csv, HEADER true, NULL '')

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
    COALESCE(NULLIF(source, ''), 'top_level'),
    NULLIF(raw_sha256, ''),
    NULLIF(raw_page, ''),
    NULLIF(run_id, '')
FROM comment_import
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

CREATE TEMP TABLE comment_raw_import (
    comment_id text,
    raw_json text,
    raw_sha256 text,
    run_id text
);

\copy comment_raw_import FROM '/tmp/multi-20261104-01/comment_raw.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO comment_raw (comment_id, raw_json, raw_sha256, run_id)
SELECT
    comment_id,
    raw_json::jsonb,
    NULLIF(raw_sha256, ''),
    NULLIF(run_id, '')
FROM comment_raw_import
ON CONFLICT (comment_id) DO UPDATE SET
    raw_json = EXCLUDED.raw_json,
    raw_sha256 = EXCLUDED.raw_sha256,
    fetched_at = now(),
    run_id = EXCLUDED.run_id;

CREATE TEMP TABLE fetch_state_import (
    run_id text,
    aweme_id text,
    thread_id text,
    cursor text,
    pages_done text,
    has_more text,
    expected_total text,
    fetched text,
    unique_count text,
    duplicates text,
    coverage text,
    stop_reason text
);

\copy fetch_state_import FROM '/tmp/multi-20261104-01/comment_fetch_state.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO comment_fetch_state (
    run_id, aweme_id, thread_id, cursor, pages_done, has_more,
    expected_total, fetched, unique_count, duplicates, coverage, stop_reason
)
SELECT
    run_id,
    aweme_id,
    thread_id,
    NULLIF(cursor, ''),
    COALESCE(NULLIF(pages_done, '')::integer, 0),
    NULLIF(has_more, '')::boolean,
    NULLIF(expected_total, '')::integer,
    COALESCE(NULLIF(fetched, '')::integer, 0),
    COALESCE(NULLIF(unique_count, '')::integer, 0),
    COALESCE(NULLIF(duplicates, '')::integer, 0),
    NULLIF(coverage, '')::double precision,
    NULLIF(stop_reason, '')
FROM fetch_state_import
ON CONFLICT (run_id, aweme_id, thread_id) DO UPDATE SET
    cursor = EXCLUDED.cursor,
    pages_done = EXCLUDED.pages_done,
    has_more = EXCLUDED.has_more,
    expected_total = EXCLUDED.expected_total,
    fetched = EXCLUDED.fetched,
    unique_count = EXCLUDED.unique_count,
    duplicates = EXCLUDED.duplicates,
    coverage = EXCLUDED.coverage,
    stop_reason = EXCLUDED.stop_reason,
    updated_at = now();

CREATE TEMP TABLE quality_import (
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

\copy quality_import FROM '/tmp/multi-20261104-01/quality_metric.csv' WITH (FORMAT csv, HEADER true, NULL '')

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
    NULLIF(duplicates, '')::integer,
    COALESCE(NULLIF(orphan_edges, '')::integer, 0),
    COALESCE(NULLIF(depth3, '')::integer, 0),
    NULLIF(coverage, '')::double precision,
    NULLIF(stop_reason, '')
FROM quality_import
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

UPDATE run
SET notes = 'Multi-account: 30 videos; top-level comments imported; 3 deep + 27 shallow replies pending'
WHERE run_id = 'multi-20261104-01';

COMMIT;
