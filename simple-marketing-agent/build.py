"""Build the database and check data quality.

    python build.py

1. loads the 3 CSV files from data/ into marketing.db (SQLite)
2. runs transform.sql
3. runs data-quality checks and prints what it found
"""
import csv
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "marketing.db"

# name of check -> SQL that returns the PROBLEM rows (empty result = all good)
CHECKS = {
    "no duplicate ad rows": """
        SELECT date, channel, campaign, COUNT(*) FROM clean_ad_spend
        GROUP BY 1, 2, 3 HAVING COUNT(*) > 1""",
    "no duplicate orders": """
        SELECT order_id FROM clean_orders GROUP BY 1 HAVING COUNT(*) > 1""",
    "every utm_source mapped to a known channel": """
        SELECT order_id, channel FROM clean_orders WHERE channel = 'other'""",
    "no missing days of ad spend": """
        SELECT channel, date AS missing_day FROM (
            SELECT DISTINCT o.date, a.channel
            FROM clean_orders o CROSS JOIN (SELECT DISTINCT channel FROM clean_ad_spend) a
        ) d
        WHERE NOT EXISTS (SELECT 1 FROM clean_ad_spend s
                          WHERE s.date = d.date AND s.channel = d.channel)""",
}


def load_csv(con, file_name, table):
    with open(HERE / "data" / file_name) as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} ({', '.join(header)})")
    con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(header))})", data)
    print(f"  loaded {file_name:18s} -> {table:16s} {len(data):5d} rows")


def run_checks(con):
    problems = []
    for name, sql in CHECKS.items():
        rows = con.execute(sql).fetchall()
        if rows:
            problems.append({"check": name, "rows": len(rows), "examples": rows[:3]})
            print(f"  WARN  {name}: {len(rows)} problem row(s), e.g. {rows[:3]}")
        else:
            print(f"  OK    {name}")
    return problems


def main():
    con = sqlite3.connect(DB)
    print("1. Loading raw data")
    load_csv(con, "google_ads.csv", "raw_google_ads")
    load_csv(con, "meta_ads.csv", "raw_meta_ads")
    load_csv(con, "crm_orders.csv", "raw_crm_orders")

    print("2. Transforming (transform.sql)")
    con.executescript((HERE / "transform.sql").read_text())
    n = con.execute("SELECT COUNT(*) FROM daily_channel").fetchone()[0]
    print(f"  daily_channel: {n} rows")

    print("3. Data-quality checks")
    run_checks(con)
    con.commit()
    con.close()
    print(f"\nDone -> {DB.name}")


if __name__ == "__main__":
    main()
