-- Add actual downloaded-file fields to run-scoped video snapshots.
BEGIN;

ALTER TABLE video_snapshot
    ADD COLUMN IF NOT EXISTS video_file_path text,
    ADD COLUMN IF NOT EXISTS video_sha256 text,
    ADD COLUMN IF NOT EXISTS video_variant text,
    ADD COLUMN IF NOT EXISTS video_bytes bigint,
    ADD COLUMN IF NOT EXISTS video_width integer,
    ADD COLUMN IF NOT EXISTS video_height integer,
    ADD COLUMN IF NOT EXISTS video_format text,
    ADD COLUMN IF NOT EXISTS video_duration_ms integer,
    ADD COLUMN IF NOT EXISTS downloaded_at timestamptz;

COMMIT;
