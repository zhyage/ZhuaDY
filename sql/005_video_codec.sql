BEGIN;
ALTER TABLE media_download ADD COLUMN IF NOT EXISTS codec text;
ALTER TABLE video_snapshot ADD COLUMN IF NOT EXISTS video_codec text;
COMMIT;
