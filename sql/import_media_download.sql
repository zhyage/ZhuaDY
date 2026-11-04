-- Import V3/V4 download results for pilot-video-20261031-01.
-- Run inside dtk-postgres-1 after copying media_download.csv to
-- /tmp/pilot-video-20261031-01/media_download.csv.

BEGIN;

CREATE TEMP TABLE media_download_import (
    run_id text,
    aweme_id text,
    status text,
    variant text,
    file_path text,
    bytes text,
    sha256 text,
    width text,
    height text,
    format text,
    duration_ms text,
    bitrate text,
    attempts text,
    error text,
    started_at text,
    finished_at text
);

\copy media_download_import FROM '/tmp/pilot-video-20261031-01/media_download.csv' WITH (FORMAT csv, HEADER true, NULL '')

INSERT INTO media_download (
    run_id, aweme_id, status, variant, file_path, bytes, sha256,
    width, height, format, duration_ms, bitrate, attempts, error,
    started_at, finished_at
)
SELECT
    run_id,
    aweme_id,
    status,
    NULLIF(variant, ''),
    NULLIF(file_path, ''),
    NULLIF(bytes, '')::bigint,
    NULLIF(sha256, ''),
    NULLIF(width, '')::integer,
    NULLIF(height, '')::integer,
    NULLIF(format, ''),
    NULLIF(duration_ms, '')::integer,
    NULLIF(bitrate, '')::bigint,
    COALESCE(NULLIF(attempts, '')::integer, 0),
    NULLIF(error, ''),
    NULLIF(started_at, '')::timestamptz,
    NULLIF(finished_at, '')::timestamptz
FROM media_download_import
ON CONFLICT (run_id, aweme_id) DO UPDATE SET
    status = EXCLUDED.status,
    variant = EXCLUDED.variant,
    file_path = EXCLUDED.file_path,
    bytes = EXCLUDED.bytes,
    sha256 = EXCLUDED.sha256,
    width = EXCLUDED.width,
    height = EXCLUDED.height,
    format = EXCLUDED.format,
    duration_ms = EXCLUDED.duration_ms,
    bitrate = EXCLUDED.bitrate,
    attempts = EXCLUDED.attempts,
    error = EXCLUDED.error,
    started_at = EXCLUDED.started_at,
    finished_at = EXCLUDED.finished_at,
    updated_at = now();

UPDATE video_snapshot v
SET video_file_path = m.file_path,
    video_sha256 = m.sha256,
    video_variant = m.variant,
    video_bytes = m.bytes,
    video_width = m.width,
    video_height = m.height,
    video_format = m.format,
    video_duration_ms = m.duration_ms,
    downloaded_at = m.finished_at
FROM media_download m
WHERE v.run_id = m.run_id
  AND v.aweme_id = m.aweme_id
  AND m.status = 'success';

UPDATE run
SET notes = notes || '; V3 smoke: 3/3 downloaded; media_download + video_snapshot updated'
WHERE run_id = 'pilot-video-20261031-01';

COMMIT;
