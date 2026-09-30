-- ============================================================
-- Turns 3 raw tables into 1 clean table the agent reads.
--   raw_google_ads, raw_meta_ads, raw_crm_orders   (loaded from CSV)
--        -> clean_ad_spend, clean_orders
--        -> daily_channel   (date x channel: spend, orders, revenue)
-- ============================================================


-- STEP 1. Ad spend from both platforms in one table, in USD.
-- Problem A: Meta sometimes sends the same row twice -> SELECT DISTINCT.
-- Problem B: Meta spend is in EUR -> multiply by the rate (fixed 1.10 for simplicity).
DROP TABLE IF EXISTS clean_ad_spend;
CREATE TABLE clean_ad_spend AS
SELECT date, 'google_ads' AS channel, campaign,
       CAST(spend_usd AS REAL)          AS spend_usd,
       CAST(clicks AS INTEGER)          AS clicks
FROM raw_google_ads
UNION ALL
SELECT date, 'meta_ads' AS channel, campaign,
       ROUND(CAST(spend_eur AS REAL) * 1.10, 2) AS spend_usd,
       CAST(clicks AS INTEGER)
FROM (SELECT DISTINCT * FROM raw_meta_ads);


-- STEP 2. Orders from the CRM with a clean channel name.
-- Problem C: utm_source is typed by hand: 'Google', 'google ', 'fb', 'adwords'...
--            -> LOWER + TRIM, then map to a channel with CASE.
-- Problem D: the CRM sometimes records the same order twice -> GROUP BY order_id.
DROP TABLE IF EXISTS clean_orders;
CREATE TABLE clean_orders AS
SELECT order_id,
       MIN(order_date) AS date,
       CASE LOWER(TRIM(MIN(utm_source)))
            WHEN 'google'     THEN 'google_ads'
            WHEN 'adwords'    THEN 'google_ads'
            WHEN 'facebook'   THEN 'meta_ads'
            WHEN 'fb'         THEN 'meta_ads'
            WHEN 'instagram'  THEN 'meta_ads'
            WHEN 'newsletter' THEN 'email'
            WHEN ''           THEN 'direct'
            ELSE 'other'
       END AS channel,
       CAST(MIN(revenue_usd) AS REAL) AS revenue_usd
FROM raw_crm_orders
GROUP BY order_id;


-- STEP 3. The final table: one row per day per channel.
-- Spend comes from the ad platforms, orders and revenue from the CRM.
-- The FULL list of (date, channel) pairs is built first so a day with
-- orders but no spend (or the other way round) is not lost.
DROP TABLE IF EXISTS daily_channel;
CREATE TABLE daily_channel AS
WITH spend AS (
    SELECT date, channel, SUM(spend_usd) AS spend_usd, SUM(clicks) AS clicks
    FROM clean_ad_spend GROUP BY date, channel
),
sales AS (
    SELECT date, channel, COUNT(*) AS orders, SUM(revenue_usd) AS revenue_usd
    FROM clean_orders GROUP BY date, channel
),
all_pairs AS (
    SELECT date, channel FROM spend
    UNION
    SELECT date, channel FROM sales
)
SELECT p.date,
       p.channel,
       ROUND(COALESCE(s.spend_usd, 0), 2)   AS spend_usd,
       COALESCE(s.clicks, 0)                AS clicks,
       COALESCE(o.orders, 0)                AS orders,
       ROUND(COALESCE(o.revenue_usd, 0), 2) AS revenue_usd
FROM all_pairs p
LEFT JOIN spend s ON s.date = p.date AND s.channel = p.channel
LEFT JOIN sales o ON o.date = p.date AND o.channel = p.channel;
