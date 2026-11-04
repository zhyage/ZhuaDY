-- Pilot research schema for douyin_research.
-- Apply inside the douyin_research database:
--   docker exec -i dtk-postgres-1 psql -U <user> -d douyin_research < sql/001_pilot_schema.sql
--
-- Design notes:
--   * comment.text is retained for research; direct identifiers (nickname/avatar/
--     signature/uid/sec_uid) are NOT stored here.
--   * comment_raw keeps the full raw JSON for pilot re-analysis; access must be
--     restricted at the DB/role level.
--   * is_thread_author is reserved for a later phase; NULL means "not computed".

BEGIN;

CREATE TABLE IF NOT EXISTS run (
    run_id              text PRIMARY KEY,
    account_id          text NOT NULL,
    status              text NOT NULL DEFAULT 'running',
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    v5_version          text,
    worker_version      text,
    protocol_version    text,
    irb_reference       text,
    notes               text
);

CREATE TABLE IF NOT EXISTS account (
    account_id          text PRIMARY KEY,
    sec_uid             text NOT NULL UNIQUE,
    unique_id           text,
    nickname            text,
    signature           text,
    verified            boolean,
    follower_count      bigint,
    following_count     bigint,
    total_favorited     bigint,
    aweme_count         bigint,
    raw_path            text,
    raw_sha256          text,
    fetched_at          timestamptz NOT NULL DEFAULT now(),
    run_id              text
);

CREATE TABLE IF NOT EXISTS video (
    aweme_id            text PRIMARY KEY,
    account_id          text NOT NULL REFERENCES account(account_id),
    author_sec_uid      text,
    author_nickname     text,
    is_target_author    boolean,
    caption             text,
    created_at          timestamptz,
    duration_ms         integer,
    digg_count          bigint,
    comment_count       bigint,
    share_count         bigint,
    collect_count       bigint,
    play_count          bigint,
    is_deleted          boolean,
    is_private          boolean,
    raw_path            text,
    raw_sha256          text,
    fetched_at          timestamptz NOT NULL DEFAULT now(),
    run_id              text
);

CREATE TABLE IF NOT EXISTS comment (
    comment_id              text PRIMARY KEY,
    aweme_id                text NOT NULL,
    thread_root_id          text,
    reply_to_comment_id     text,
    depth                   integer,
    is_orphan               boolean NOT NULL DEFAULT false,
    text                    text NOT NULL,
    created_at              timestamptz,
    digg_count              bigint,
    reply_count             bigint,
    is_pinned               boolean,
    is_author_liked         boolean,
    ip_province             text,
    is_author               boolean,
    is_thread_author        boolean,
    author_hash             text,
    hash_version            text NOT NULL DEFAULT 'v1',
    label_text              text,
    label_texts             jsonb,
    is_creator_label        boolean,
    source                  text NOT NULL,
    raw_sha256              text,
    raw_page                text,
    fetched_at              timestamptz NOT NULL DEFAULT now(),
    run_id                  text
);

CREATE TABLE IF NOT EXISTS comment_raw (
    comment_id          text PRIMARY KEY,
    raw_json            jsonb NOT NULL,
    raw_sha256          text,
    fetched_at          timestamptz NOT NULL DEFAULT now(),
    run_id              text
);

CREATE TABLE IF NOT EXISTS comment_fetch_state (
    run_id              text NOT NULL,
    aweme_id            text NOT NULL,
    thread_id           text NOT NULL,
    cursor              text,
    pages_done          integer NOT NULL DEFAULT 0,
    has_more            boolean,
    expected_total      integer,
    fetched             integer NOT NULL DEFAULT 0,
    unique_count        integer NOT NULL DEFAULT 0,
    duplicates          integer NOT NULL DEFAULT 0,
    coverage            double precision,
    stop_reason         text,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, aweme_id, thread_id)
);

CREATE TABLE IF NOT EXISTS quality_metric (
    run_id              text NOT NULL,
    aweme_id            text NOT NULL,
    thread_id           text NOT NULL DEFAULT '__video__',
    expected_total      integer,
    fetched             integer,
    unique_count        integer,
    duplicates          integer,
    orphan_edges        integer,
    depth3              integer,
    coverage            double precision,
    stop_reason         text,
    computed_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, aweme_id, thread_id)
);

CREATE TABLE IF NOT EXISTS worker_job (
    job_id              text PRIMARY KEY,
    run_id              text NOT NULL,
    aweme_id            text NOT NULL,
    threads             jsonb NOT NULL,
    status              text NOT NULL DEFAULT 'pending',
    attempt             integer NOT NULL DEFAULT 0,
    lease_until         timestamptz,
    result_path         text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_video_account_created
    ON video (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comment_aweme
    ON comment (aweme_id);
CREATE INDEX IF NOT EXISTS idx_comment_thread_root
    ON comment (thread_root_id);
CREATE INDEX IF NOT EXISTS idx_comment_reply_to
    ON comment (reply_to_comment_id);
CREATE INDEX IF NOT EXISTS idx_comment_author_hash
    ON comment (author_hash);
CREATE INDEX IF NOT EXISTS idx_comment_created_at
    ON comment (created_at);
CREATE INDEX IF NOT EXISTS idx_comment_fetch_state_run
    ON comment_fetch_state (run_id, aweme_id);
CREATE INDEX IF NOT EXISTS idx_quality_run
    ON quality_metric (run_id, aweme_id);

COMMENT ON TABLE comment IS
    'Analysis layer: text retained; direct identifiers are hashed/removed.';
COMMENT ON TABLE comment_raw IS
    'Restricted raw JSON for pilot re-analysis; do not export/share.';
COMMENT ON COLUMN comment.author_hash IS
    'HMAC-SHA256(salt, "douyin:" + user.sec_uid); same user -> same hash.';
COMMENT ON COLUMN comment.is_thread_author IS
    'Reserved for later phase: root comment author replied. NULL = not computed.';
COMMENT ON COLUMN comment.is_author IS
    'Video author replied (compare user.sec_uid to video author sec_uid).';
COMMENT ON COLUMN comment.depth IS
    '2 = direct reply to root; 3+ = reply to reply; NULL = orphan/unknown.';

-- Idempotent upgrades for an already-created pilot DB.
ALTER TABLE video ADD COLUMN IF NOT EXISTS author_sec_uid text;
ALTER TABLE video ADD COLUMN IF NOT EXISTS author_nickname text;
ALTER TABLE video ADD COLUMN IF NOT EXISTS is_target_author boolean;
ALTER TABLE comment ADD COLUMN IF NOT EXISTS reply_count bigint;
ALTER TABLE comment ADD COLUMN IF NOT EXISTS is_pinned boolean;
ALTER TABLE comment ADD COLUMN IF NOT EXISTS is_author_liked boolean;
ALTER TABLE comment_fetch_state DROP CONSTRAINT IF EXISTS comment_fetch_state_pkey;
ALTER TABLE comment_fetch_state ADD PRIMARY KEY (run_id, aweme_id, thread_id);

COMMIT;
