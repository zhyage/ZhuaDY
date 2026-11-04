-- Import V1 video metadata for pilot-video-20261031-01 into run-scoped snapshots.
-- Old `account`/`video` rows from pilot-20261030-01 are NOT touched.
-- Run inside dtk-postgres-1 after copying CSVs to /tmp/multi-20261104-01/.

BEGIN;

CREATE TEMP TABLE account_snapshot_import (
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
    certification text,
    favoriting_count text,
    collected_at text,
    raw_path text,
    raw_sha256 text,
    run_id text
);

\copy account_snapshot_import FROM '/tmp/multi-20261104-01/account.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO account_snapshot (
    run_id, account_id, sec_uid, unique_id, nickname, signature, verified,
    follower_count, following_count, total_favorited, aweme_count,
    certification, favoriting_count, collected_at, raw_path, raw_sha256, fetched_at
)
SELECT
    run_id,
    account_id,
    NULLIF(sec_uid, ''),
    NULLIF(unique_id, ''),
    NULLIF(nickname, ''),
    NULLIF(signature, ''),
    NULLIF(verified, '')::boolean,
    NULLIF(follower_count, '')::bigint,
    NULLIF(following_count, '')::bigint,
    NULLIF(total_favorited, '')::bigint,
    NULLIF(aweme_count, '')::bigint,
    NULLIF(certification, ''),
    NULLIF(favoriting_count, '')::bigint,
    NULLIF(collected_at, '')::timestamptz,
    NULLIF(raw_path, ''),
    NULLIF(raw_sha256, ''),
    COALESCE(NULLIF(collected_at, '')::timestamptz, now())
FROM account_snapshot_import
ON CONFLICT (run_id, account_id) DO UPDATE SET
    sec_uid = EXCLUDED.sec_uid,
    unique_id = EXCLUDED.unique_id,
    nickname = EXCLUDED.nickname,
    signature = EXCLUDED.signature,
    verified = EXCLUDED.verified,
    follower_count = EXCLUDED.follower_count,
    following_count = EXCLUDED.following_count,
    total_favorited = EXCLUDED.total_favorited,
    aweme_count = EXCLUDED.aweme_count,
    certification = EXCLUDED.certification,
    favoriting_count = EXCLUDED.favoriting_count,
    collected_at = EXCLUDED.collected_at,
    raw_path = EXCLUDED.raw_path,
    raw_sha256 = EXCLUDED.raw_sha256,
    fetched_at = now();

CREATE TEMP TABLE video_snapshot_import (
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
    web_url text,
    kind text,
    tags text,
    recommend_count text,
    media_width text,
    media_height text,
    media_format text,
    media_size_bytes text,
    media_bitrate text,
    author_certification text,
    author_favoriting_count text,
    collected_at text,
    raw_path text,
    raw_sha256 text,
    run_id text
);

\copy video_snapshot_import FROM '/tmp/multi-20261104-01/videos.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO video_snapshot (
    run_id, aweme_id, account_id, author_sec_uid, author_nickname,
    is_target_author, caption, created_at, duration_ms, digg_count,
    comment_count, share_count, collect_count, play_count, is_deleted,
    is_private, web_url, kind, tags, recommend_count, media_width,
    media_height, media_format, media_size_bytes, media_bitrate,
    author_certification, author_favoriting_count, collected_at,
    raw_path, raw_sha256, fetched_at
)
SELECT
    run_id,
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
    NULLIF(web_url, ''),
    NULLIF(kind, ''),
    NULLIF(tags, '')::jsonb,
    NULLIF(recommend_count, '')::bigint,
    NULLIF(media_width, '')::integer,
    NULLIF(media_height, '')::integer,
    NULLIF(media_format, ''),
    NULLIF(media_size_bytes, '')::bigint,
    NULLIF(media_bitrate, '')::bigint,
    NULLIF(author_certification, ''),
    NULLIF(author_favoriting_count, '')::bigint,
    NULLIF(collected_at, '')::timestamptz,
    NULLIF(raw_path, ''),
    NULLIF(raw_sha256, ''),
    COALESCE(NULLIF(collected_at, '')::timestamptz, now())
FROM video_snapshot_import
ON CONFLICT (run_id, aweme_id) DO UPDATE SET
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
    web_url = EXCLUDED.web_url,
    kind = EXCLUDED.kind,
    tags = EXCLUDED.tags,
    recommend_count = EXCLUDED.recommend_count,
    media_width = EXCLUDED.media_width,
    media_height = EXCLUDED.media_height,
    media_format = EXCLUDED.media_format,
    media_size_bytes = EXCLUDED.media_size_bytes,
    media_bitrate = EXCLUDED.media_bitrate,
    author_certification = EXCLUDED.author_certification,
    author_favoriting_count = EXCLUDED.author_favoriting_count,
    collected_at = EXCLUDED.collected_at,
    raw_path = EXCLUDED.raw_path,
    raw_sha256 = EXCLUDED.raw_sha256,
    fetched_at = now();

INSERT INTO run (
    run_id, account_id, status, started_at, finished_at, v5_version,
    protocol_version, irb_reference, notes
)
VALUES (
    'multi-20261104-01',
    'multi-account',
    'running', now(), NULL, '5.1.7', '1.0', NULL,
    'Multi-account sample: 3 accounts x 10 random videos with comments; 1 deep + 9 shallow per account; videos/comments/replies pending'
)
ON CONFLICT (run_id) DO UPDATE SET
    status = EXCLUDED.status,
    notes = EXCLUDED.notes;

COMMIT;
