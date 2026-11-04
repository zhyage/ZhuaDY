-- V0: add video metadata + video download columns.
-- Non-destructive: all new columns are nullable; existing pilot rows stay NULL.
-- Run inside dtk-postgres-1:
--   psql -U dtk -d douyin_research -f /tmp/002_video_media.sql

BEGIN;

ALTER TABLE account
    ADD COLUMN IF NOT EXISTS certification text,
    ADD COLUMN IF NOT EXISTS favoriting_count bigint,
    ADD COLUMN IF NOT EXISTS collected_at timestamptz;

ALTER TABLE video
    ADD COLUMN IF NOT EXISTS web_url text,
    ADD COLUMN IF NOT EXISTS kind text,
    ADD COLUMN IF NOT EXISTS tags jsonb,
    ADD COLUMN IF NOT EXISTS recommend_count bigint,
    ADD COLUMN IF NOT EXISTS media_width integer,
    ADD COLUMN IF NOT EXISTS media_height integer,
    ADD COLUMN IF NOT EXISTS media_format text,
    ADD COLUMN IF NOT EXISTS media_size_bytes bigint,
    ADD COLUMN IF NOT EXISTS media_bitrate bigint,
    ADD COLUMN IF NOT EXISTS author_certification text,
    ADD COLUMN IF NOT EXISTS author_favoriting_count bigint,
    ADD COLUMN IF NOT EXISTS collected_at timestamptz,
    ADD COLUMN IF NOT EXISTS video_file_path text,
    ADD COLUMN IF NOT EXISTS video_sha256 text,
    ADD COLUMN IF NOT EXISTS downloaded_at timestamptz;

CREATE TABLE IF NOT EXISTS media_download (
    aweme_id        text PRIMARY KEY,
    run_id          text NOT NULL,
    status          text NOT NULL DEFAULT 'pending',
    variant         text,
    file_path       text,
    bytes           bigint,
    sha256          text,
    width           integer,
    height          integer,
    format          text,
    duration_ms     integer,
    bitrate         bigint,
    attempts        integer NOT NULL DEFAULT 0,
    error           text,
    started_at      timestamptz,
    finished_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS media_download_run_status_idx
    ON media_download (run_id, status);

COMMIT;
