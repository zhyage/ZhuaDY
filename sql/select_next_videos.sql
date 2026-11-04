-- Select 20 new videos for pilot-video-20261031-01.
-- Excludes the 20 videos already used in pilot-20261030-01.
-- 10 high-comment + 10 time-spread (same rule as sql/select_pilot_videos.sql).
-- Run:
--   docker exec dtk-postgres-1 psql -U dtk -d douyin_research -X -q -f /tmp/select_next_videos.sql
BEGIN;

CREATE TEMP TABLE selected AS
WITH target AS (
    SELECT *
    FROM video_snapshot
    WHERE run_id = 'pilot-video-20261031-01'
      AND is_target_author
      AND comment_count >= 1
      AND NOT is_deleted
      AND NOT is_private
      AND aweme_id NOT IN ('7491217420569349413', '7681660984184153322', '7572040672217333163', '7489755277537873161', '7114886226313841934', '7044405043864358181', '7334674312995114240', '7490749435035634995', '7576484819334827638', '7483476437522025738', '6878231006265003272', '7046569627224182024', '7119897729882475812', '7210712875151723832', '7285230504196984098', '7399219567072906534', '7466043529555479846', '7555457713829711146', '7633323977272272787', '7698673836661124022')
),
top AS (
    SELECT aweme_id,
           'high_comment'::text AS selection_reason,
           row_number() OVER (
               ORDER BY comment_count DESC, digg_count DESC, aweme_id
           ) AS rank_in_group
    FROM target
    ORDER BY comment_count DESC, digg_count DESC, aweme_id
    LIMIT 10
),
rest AS (
    SELECT t.*
    FROM target t
    LEFT JOIN top USING (aweme_id)
    WHERE top.aweme_id IS NULL
),
numbered AS (
    SELECT r.*,
           row_number() OVER (ORDER BY created_at ASC NULLS LAST, aweme_id) AS rn,
           count(*) OVER () AS n
    FROM rest r
),
time10 AS (
    SELECT aweme_id,
           'time_spread'::text AS selection_reason,
           row_number() OVER (ORDER BY rn) AS rank_in_group
    FROM numbered
    WHERE rn IN (
        SELECT DISTINCT (1 + round(i * (n - 1) / 9.0))::int
        FROM numbered, generate_series(0, 9) AS i
    )
)
SELECT v.aweme_id,
       v.created_at,
       v.comment_count,
       v.digg_count,
       v.duration_ms,
       v.caption,
       s.selection_reason,
       s.rank_in_group,
       v.web_url,
       v.kind,
       v.recommend_count,
       v.media_size_bytes,
       v.author_certification
FROM (
    SELECT * FROM top
    UNION ALL
    SELECT * FROM time10
) s
JOIN video_snapshot v
  ON v.run_id = 'pilot-video-20261031-01' AND v.aweme_id = s.aweme_id;

\copy (SELECT * FROM selected ORDER BY selection_reason, rank_in_group) TO STDOUT WITH (FORMAT csv, HEADER true, NULL '')

COMMIT;
