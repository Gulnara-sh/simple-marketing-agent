"""Checks that the agent's tools give correct and safe answers.

    python test.py

Each test prints OK or FAIL. The "correct numbers" are recalculated here
straight from the CSV files, independently of transform.sql.
"""
import csv
from pathlib import Path

import server

DATA = Path(__file__).parent / "data"
results = []


def check(name, condition):
    results.append(condition)
    print(f"  {'OK  ' if condition else 'FAIL'}  {name}")


def read(file_name):
    with open(DATA / file_name) as f:
        return list(csv.DictReader(f))


# --- expected numbers, computed from raw CSV with plain Python ---
google_spend = sum(float(r["spend_usd"]) for r in read("google_ads.csv"))
meta_unique = {tuple(r.values()) for r in read("meta_ads.csv")}          # drop duplicate rows
meta_spend = sum(float(r[2]) * 1.10 for r in meta_unique)                # EUR -> USD
orders = {r["order_id"]: r for r in read("crm_orders.csv")}              # drop duplicate orders
total_revenue = sum(float(r["revenue_usd"]) for r in orders.values())

res = server.get_channel_metrics()
by_channel = {r["channel"]: r for r in res["rows"]}

print("1. Numbers match the raw data")
check("Google spend", abs(by_channel["google_ads"]["spend_usd"] - google_spend) < 0.01)
check("Meta spend (duplicates removed, EUR -> USD)",
      abs(by_channel["meta_ads"]["spend_usd"] - meta_spend) < 0.05)   # a few cents of rounding
check("Total revenue (duplicate orders removed)",
      abs(sum(r["revenue_usd"] for r in res["rows"]) - total_revenue) < 0.05)
g = by_channel["google_ads"]
check("ROAS = revenue / spend", abs(g["roas"] - g["revenue_usd"] / g["spend_usd"]) < 0.01)

print("2. Data problems are reported")
check("Sep 14 Google gap is in the warnings",
      any("2026-09-14" in w for w in res["warnings"]))
clean = server.get_channel_metrics("2026-09-01", "2026-09-10")
check("No false warning for a clean period", clean["warnings"] == [])
meta_only = server.get_channel_metrics(channel="meta_ads")
check("No Google warning when asking only about Meta", meta_only["warnings"] == [])

print("3. Honest about missing data")
check("Unknown channel (TikTok) -> error, not a made-up number",
      "error" in server.get_channel_metrics(channel="tiktok"))

print("4. The agent cannot change the data")
for bad in ["DELETE FROM daily_channel",
            "DROP TABLE clean_orders",
            "WITH x AS (SELECT 1) DELETE FROM daily_channel"]:
    check(f"blocked: {bad}", "error" in server.run_sql(bad))
check("data still there after the attempts",
      server.run_sql("SELECT COUNT(*) AS n FROM daily_channel")["rows"][0]["n"] > 0)

print(f"\n{sum(results)} of {len(results)} checks passed")
raise SystemExit(0 if all(results) else 1)
