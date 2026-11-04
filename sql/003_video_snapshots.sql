-- V0/V1: run-scoped snapshots for repeated video metadata collection.
-- Rationale: the existing `account`/`video` tables are one row per account/video
-- and already hold pilot-20261030-01. Re-importing a later run into them would
-- overwrite the completed pilot. New runs therefore write snapshots keyed by
-- (run_id, aweme_id) / (run_id, account_id); old tables are untouched.

BEGIN;

CREATE TABLE IF NOT EXISTS account_snapshot (
    run_id              text NOT NULL,
    account_id          text NOT NULL,
    sec_uid             text,
    unique_id           text,
    nickname            text,
    signature           text,
    verified            boolean,
    follower_count      bigint,
    following_count     bigint,
    total_favorited     bigint,
    aweme_count         bigint,
    certification       text,
    favoriting_count    bigint,
    collected_at        timestamptz,
    raw_path            text,
    raw_sha256          text,
    fetched_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, account_id)
);

CREATE TABLE IF NOT EXISTS video_snapshot (
    run_id                  text NOT NULL,
    aweme_id                text NOT NULL,
    account_id              text NOT NULL,
    author_sec_uid          text,
    author_nickname         text,
    is_target_author        boolean,
    caption                 text,
    created_at              timestamptz,
    duration_ms             integer,
    digg_count              bigint,
    comment_count           bigint,
    share_count             bigint,
    collect_count           bigint,
    play_count              bigint,
    is_deleted              boolean,
    is_private              boolean,
    web_url                 text,
    kind                    text,
    tags                    jsonb,
    recommend_count         bigint,
    media_width             integer,
    media_height            integer,
    media_format            text,
    media_size_bytes        bigint,
    media_bitrate           bigint,
    author_certification    text,
    author_favoriting_count bigint,
    collected_at            timestamptz,
    raw_path                text,
    raw_sha256              text,
    fetched_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, aweme_id)
);

CREATE INDEX IF NOT EXISTS video_snapshot_account_idx
    ON video_snapshot (run_id, account_id, created_at DESC);

-- media_download was introduced empty in 002; key it by run as well.
ALTER TABLE media_download DROP CONSTRAINT IF EXISTS media_download_pkey;
ALTER TABLE media_download ADD PRIMARY KEY (run_id, aweme_id);

COMMIT;
