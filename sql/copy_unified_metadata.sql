BEGIN;
INSERT INTO video_snapshot (run_id, aweme_id, account_id, author_sec_uid, author_nickname, is_target_author, caption, created_at, duration_ms, digg_count, comment_count, share_count, collect_count, play_count, is_deleted, is_private, web_url, kind, tags, recommend_count, media_width, media_height, media_format, media_size_bytes, media_bitrate, author_certification, author_favoriting_count, collected_at, raw_path, raw_sha256, fetched_at, video_file_path, video_sha256, video_variant, video_bytes, video_width, video_height, video_format, video_duration_ms, downloaded_at, video_codec)
SELECT 'pilot-unified-20261031-01', aweme_id, account_id, author_sec_uid, author_nickname, is_target_author, caption, created_at, duration_ms, digg_count, comment_count, share_count, collect_count, play_count, is_deleted, is_private, web_url, kind, tags, recommend_count, media_width, media_height, media_format, media_size_bytes, media_bitrate, author_certification, author_favoriting_count, collected_at, raw_path, raw_sha256, fetched_at, video_file_path, video_sha256, video_variant, video_bytes, video_width, video_height, video_format, video_duration_ms, downloaded_at, video_codec
FROM video_snapshot
WHERE run_id='pilot-video-20261031-01' AND aweme_id IN ('7533462706831133993', '7569431411968650091', '7494176428737514790', '7039932291698789646', '7582510947006663999', '6879028479745117454', '7135992071890029861', '7321627593684290850', '7520224993746144575', '7693573679142648403')
ON CONFLICT (run_id, aweme_id) DO NOTHING;
INSERT INTO account_snapshot (run_id, account_id, sec_uid, unique_id, nickname, signature, verified, follower_count, following_count, total_favorited, aweme_count, certification, favoriting_count, collected_at, raw_path, raw_sha256, fetched_at)
SELECT 'pilot-unified-20261031-01', account_id, sec_uid, unique_id, nickname, signature, verified, follower_count, following_count, total_favorited, aweme_count, certification, favoriting_count, collected_at, raw_path, raw_sha256, fetched_at
FROM account_snapshot
WHERE run_id='pilot-video-20261031-01'
ON CONFLICT (run_id, account_id) DO NOTHING;
INSERT INTO run (run_id, account_id, status, started_at, finished_at, v5_version, protocol_version, irb_reference, notes)
VALUES ('pilot-unified-20261031-01','MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c','running',now(),NULL,'5.1.7','1.0',NULL,
        'Unified 10-video round: video metadata copied from pilot-video-20261031-01; videos/comments/replies to follow; 1 deep + 9 shallow replies')
ON CONFLICT (run_id) DO UPDATE SET notes=EXCLUDED.notes, status='running';
COMMIT;
