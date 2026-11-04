BEGIN;
CREATE TEMP TABLE codec_import (run_id text, aweme_id text, codec text);
\copy codec_import FROM '/tmp/pilot-unified-20261031-01/media_codec.csv' WITH (FORMAT csv, HEADER true, NULL '')
UPDATE media_download m SET codec=i.codec, updated_at=now()
FROM codec_import i
WHERE m.run_id=i.run_id AND m.aweme_id=i.aweme_id;
UPDATE video_snapshot v SET video_codec=i.codec
FROM codec_import i
WHERE v.run_id=i.run_id AND v.aweme_id=i.aweme_id;
COMMIT;
