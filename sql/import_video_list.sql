-- Import Stage 1 video list for pilot-20261030-01.
-- Run inside the Postgres container after copying the CSVs to /tmp/pilot-20261030-01.

BEGIN;

CREATE TEMP TABLE account_import (
    account_id text,
    sec_uid text,
    unique_id text,
    nickname text,
    signature text,
    verified text,
    follower_count text,
    following_count text,
    total_favorited text,
    aweme_count text,
    raw_path text,
    raw_sha256 text,
    run_id text
);

\copy account_import FROM '/tmp/pilot-20261030-01/account.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO account (
    account_id, sec_uid, unique_id, nickname, signature, verified,
    follower_count, following_count, total_favorited, aweme_count,
    raw_path, raw_sha256, run_id
)
SELECT
    account_id,
    sec_uid,
    NULLIF(unique_id, ''),
    NULLIF(nickname, ''),
    NULLIF(signature, ''),
    NULLIF(verified, '')::boolean,
    NULLIF(follower_count, '')::bigint,
    NULLIF(following_count, '')::bigint,
    NULLIF(total_favorited, '')::bigint,
    NULLIF(aweme_count, '')::bigint,
    NULLIF(raw_path, ''),
    NULLIF(raw_sha256, ''),
    NULLIF(run_id, '')
FROM account_import
ON CONFLICT (account_id) DO UPDATE SET
    sec_uid = EXCLUDED.sec_uid,
    unique_id = EXCLUDED.unique_id,
    nickname = EXCLUDED.nickname,
    signature = EXCLUDED.signature,
    verified = EXCLUDED.verified,
    follower_count = EXCLUDED.follower_count,
    following_count = EXCLUDED.following_count,
    total_favorited = EXCLUDED.total_favorited,
    aweme_count = EXCLUDED.aweme_count,
    raw_path = EXCLUDED.raw_path,
    raw_sha256 = EXCLUDED.raw_sha256,
    fetched_at = now(),
    run_id = EXCLUDED.run_id;

CREATE TEMP TABLE video_import (
    aweme_id text,
    account_id text,
    author_sec_uid text,
    author_nickname text,
    is_target_author text,
    caption text,
    created_at text,
    duration_ms text,
    digg_count text,
    comment_count text,
    share_count text,
    collect_count text,
    play_count text,
    is_deleted text,
    is_private text,
    raw_path text,
    raw_sha256 text,
    run_id text
);

\copy video_import FROM '/tmp/pilot-20261030-01/videos.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO video (
    aweme_id, account_id, author_sec_uid, author_nickname, is_target_author,
    caption, created_at, duration_ms, digg_count, comment_count,
    share_count, collect_count, play_count, is_deleted, is_private,
    raw_path, raw_sha256, run_id
)
SELECT
    aweme_id,
    account_id,
    NULLIF(author_sec_uid, ''),
    NULLIF(author_nickname, ''),
    NULLIF(is_target_author, '')::boolean,
    NULLIF(caption, ''),
    NULLIF(created_at, '')::timestamptz,
    NULLIF(duration_ms, '')::integer,
    NULLIF(digg_count, '')::bigint,
    NULLIF(comment_count, '')::bigint,
    NULLIF(share_count, '')::bigint,
    NULLIF(collect_count, '')::bigint,
    NULLIF(play_count, '')::bigint,
    NULLIF(is_deleted, '')::boolean,
    NULLIF(is_private, '')::boolean,
    NULLIF(raw_path, ''),
    NULLIF(raw_sha256, ''),
    NULLIF(run_id, '')
FROM video_import
ON CONFLICT (aweme_id) DO UPDATE SET
    account_id = EXCLUDED.account_id,
    author_sec_uid = EXCLUDED.author_sec_uid,
    author_nickname = EXCLUDED.author_nickname,
    is_target_author = EXCLUDED.is_target_author,
    caption = EXCLUDED.caption,
    created_at = EXCLUDED.created_at,
    duration_ms = EXCLUDED.duration_ms,
    digg_count = EXCLUDED.digg_count,
    comment_count = EXCLUDED.comment_count,
    share_count = EXCLUDED.share_count,
    collect_count = EXCLUDED.collect_count,
    play_count = EXCLUDED.play_count,
    is_deleted = EXCLUDED.is_deleted,
    is_private = EXCLUDED.is_private,
    raw_path = EXCLUDED.raw_path,
    raw_sha256 = EXCLUDED.raw_sha256,
    fetched_at = now(),
    run_id = EXCLUDED.run_id;

INSERT INTO run (
    run_id, account_id, status, started_at, finished_at,
    v5_version, worker_version, protocol_version, irb_reference, notes
)
VALUES (
    'pilot-20261030-01',
    'MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c',
    'running',
    now(),
    NULL,
    'v5.1.7',
    NULL,
    '1.0',
    NULL,
    'Stage 1 video list: 765 unique, 730 target author, 35 other author; IRB reference pending'
)
ON CONFLICT (run_id) DO UPDATE SET
    status = EXCLUDED.status,
    notes = EXCLUDED.notes;

COMMIT;
