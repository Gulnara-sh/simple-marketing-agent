"""MCP server: lets Claude answer questions about marketing data.

Claude sees 3 tools:
  get_channel_metrics  - spend, orders, revenue, ROAS, CPA per channel for a period
  check_data_quality   - known problems in the data
  run_sql              - any SELECT on the clean tables (read-only)

Reliability rules, in short:
  * ROAS and CPA are calculated HERE, Claude never does the math itself
  * every answer includes warnings about data problems in the requested period
  * the database is opened read-only, so the agent cannot change or delete anything
"""
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB = Path(__file__).parent / "marketing.db"

mcp = FastMCP(
    "simple-marketing",
    instructions=(
        "You answer questions about marketing performance (Google Ads, Meta Ads, CRM). "
        "Use get_channel_metrics for spend/revenue/ROAS/CPA. Never calculate ROAS yourself. "
        "If a tool returns warnings, always mention them in your answer. "
        "If data for something does not exist, say so instead of guessing."
    ),
)


def query(sql, params=()):
    # mode=ro -> read-only: INSERT / UPDATE / DELETE / DROP are refused by SQLite itself
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def missing_spend_days(date_from, date_to, channel=None):
    """Days where an ad platform sent no data (e.g. connector outage)."""
    rows = query("""
        SELECT c.channel, d.date
        FROM (SELECT DISTINCT date FROM daily_channel WHERE date BETWEEN ? AND ?) d
        CROSS JOIN (SELECT DISTINCT channel FROM clean_ad_spend) c
        WHERE NOT EXISTS (SELECT 1 FROM clean_ad_spend s
                          WHERE s.date = d.date AND s.channel = c.channel)
        ORDER BY 1, 2""", (date_from, date_to))
    rows = [r for r in rows if channel is None or r["channel"] == channel]
    return [f"{r['channel']} has no spend data for {r['date']}: spend is understated and "
            f"ROAS overstated for this period." for r in rows]


@mcp.tool()
def get_channel_metrics(date_from: str = "2026-09-01", date_to: str = "2026-09-30",
                        channel: str | None = None) -> dict:
    """Spend, clicks, orders, revenue, ROAS and CPA per channel between two dates
    (YYYY-MM-DD, inclusive). Channels: google_ads, meta_ads, email, direct.
    Attribution: last click (orders are credited to the utm_source of the order)."""
    known = [r["channel"] for r in query("SELECT DISTINCT channel FROM daily_channel")]
    if channel and channel not in known:
        return {"error": f"Unknown channel '{channel}'. Available channels: {known}. "
                         f"There is no data for other channels."}
    rows = query(f"""
        SELECT channel,
               ROUND(SUM(spend_usd), 2)                                  AS spend_usd,
               SUM(clicks)                                               AS clicks,
               SUM(orders)                                               AS orders,
               ROUND(SUM(revenue_usd), 2)                                AS revenue_usd,
               ROUND(SUM(revenue_usd) / NULLIF(SUM(spend_usd), 0), 2)    AS roas,
               ROUND(NULLIF(SUM(spend_usd), 0) / NULLIF(SUM(orders), 0), 2) AS cpa
        FROM daily_channel
        WHERE date BETWEEN ? AND ? {"AND channel = ?" if channel else ""}
        GROUP BY channel ORDER BY spend_usd DESC""",
        (date_from, date_to, channel) if channel else (date_from, date_to))
    if not rows:
        return {"error": "No data for this period. Data covers 2026-09-01 .. 2026-09-30."}
    return {"period": f"{date_from} .. {date_to}", "attribution": "last click",
            "rows": rows, "warnings": missing_spend_days(date_from, date_to, channel)}


@mcp.tool()
def check_data_quality() -> dict:
    """Known data problems: missing days per ad platform and orders with an unknown source."""
    unknown = query("SELECT COUNT(*) AS n FROM clean_orders WHERE channel = 'other'")[0]["n"]
    problems = missing_spend_days("2026-09-01", "2026-09-30")
    if unknown:
        problems.append(f"{unknown} orders have an unrecognised utm_source.")
    return {"problems": problems or ["No known problems."]}


@mcp.tool()
def run_sql(sql: str) -> dict:
    """Run one SELECT query for questions the other tools can't answer.
    Tables: daily_channel(date, channel, spend_usd, clicks, orders, revenue_usd),
    clean_ad_spend(date, channel, campaign, spend_usd, clicks),
    clean_orders(order_id, date, channel, revenue_usd). Max 100 rows."""
    if not sql.strip().lower().startswith(("select", "with")):
        return {"error": "Only SELECT queries are allowed."}
    try:
        return {"rows": query(sql)[:100]}
    except sqlite3.Error as e:
        return {"error": f"SQL error: {e}"}


if __name__ == "__main__":
    mcp.run()
