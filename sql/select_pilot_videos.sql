-- Select the 20 pilot videos from target-author videos:
--   * 10 highest comment_count (tie: digg_count, aweme_id)
--   * 10 time-spread from the remaining target videos (evenly spaced by created_at)
-- Output: CSV on stdout (aweme_id, created_at, comment_count, digg_count, duration_ms,
--         caption, selection_reason, rank_in_group)

WITH target AS (
    SELECT *
    FROM video
    WHERE is_target_author
      AND comment_count >= 1
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
           row_number() OVER (ORDER BY created_at ASC, aweme_id) AS rn,
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
       s.rank_in_group
FROM (
    SELECT * FROM top
    UNION ALL
    SELECT * FROM time10
) s
JOIN video v USING (aweme_id)
ORDER BY s.selection_reason, s.rank_in_group;
