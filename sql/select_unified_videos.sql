-- Select 10 new videos for pilot-unified-20261031-01.
-- 5 high_comment + 5 time_spread; exclude the 40 videos used by the two prior pilots.
-- Source metadata: video_snapshot run pilot-video-20261031-01.
BEGIN;
CREATE TEMP TABLE selected AS
WITH target AS (
    SELECT * FROM video_snapshot
    WHERE run_id='pilot-video-20261031-01'
      AND is_target_author AND comment_count>=1
      AND NOT is_deleted AND NOT is_private
      AND aweme_id NOT IN ('6878231006265003272', '6878647880840662285', '7044405043864358181', '7045222256401779998', '7046569627224182024', '7054106189193284871', '7114886226313841934', '7118550497988054285', '7119897729882475812', '7205128912832171320', '7210712875151723832', '7284593870111870247', '7285230504196984098', '7334674312995114240', '7385426860106190132', '7399219567072906534', '7464057971715198258', '7466043529555479846', '7475170747116162341', '7483476437522025738', '7489025231130987803', '7489755277537873161', '7490749435035634995', '7491217420569349413', '7497470532830383386', '7539720925924396351', '7554277792838651155', '7555457713829711146', '7556063549564734756', '7572040672217333163', '7576484819334827638', '7579131290542150591', '7582098582921350463', '7589971274282093866', '7632939298895150441', '7633323977272272787', '7651914150247932777', '7681660984184153322', '7694221425457240211', '7698673836661124022')
),
top AS (
    SELECT aweme_id, 'high_comment'::text AS selection_reason,
           row_number() OVER (ORDER BY comment_count DESC, digg_count DESC, aweme_id) AS rank_in_group
    FROM target ORDER BY comment_count DESC, digg_count DESC, aweme_id LIMIT 5
),
rest AS (
    SELECT t.* FROM target t LEFT JOIN top USING (aweme_id) WHERE top.aweme_id IS NULL
),
numbered AS (
    SELECT r.*, row_number() OVER (ORDER BY created_at ASC NULLS LAST, aweme_id) AS rn,
           count(*) OVER () AS n
    FROM rest r
),
time5 AS (
    SELECT aweme_id, 'time_spread'::text AS selection_reason,
           row_number() OVER (ORDER BY rn) AS rank_in_group
    FROM numbered
    WHERE rn IN (
        SELECT DISTINCT (1 + round(i*(n-1)/4.0))::int
        FROM numbered, generate_series(0,4) AS i
    )
)
SELECT v.aweme_id, v.created_at, v.comment_count, v.digg_count, v.duration_ms,
       v.caption, s.selection_reason, s.rank_in_group, v.web_url, v.kind,
       v.recommend_count, v.media_size_bytes, v.author_certification
FROM (SELECT * FROM top UNION ALL SELECT * FROM time5) s
JOIN video_snapshot v ON v.run_id='pilot-video-20261031-01' AND v.aweme_id=s.aweme_id;
\copy (SELECT * FROM selected ORDER BY selection_reason, rank_in_group) TO STDOUT WITH (FORMAT csv, HEADER true, NULL '')
COMMIT;
