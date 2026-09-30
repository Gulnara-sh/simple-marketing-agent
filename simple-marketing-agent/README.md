# Simple Marketing Agent

A small analytics pipeline with an AI agent on top: three raw CSV exports are cleaned with SQL into a SQLite database, and an **MCP server** lets Claude answer questions about spend, revenue, ROAS and CPA, reliably and without being able to change the data.

```
data/*.csv  ──►  build.py + transform.sql  ──►  marketing.db  ──►  server.py (MCP)  ──►  Claude
                 (load, clean, check)                              (3 tools)
```

## Files

| File | Contents |
|---|---|
| `data/google_ads.csv` | Google Ads daily spend and clicks, in USD |
| `data/meta_ads.csv` | Meta (Facebook / Instagram) daily spend and clicks, in EUR |
| `data/crm_orders.csv` | CRM orders: traffic source (`utm_source`) and revenue |
| `transform.sql` | all data cleaning, 3 commented steps |
| `build.py` | loads the CSVs, runs `transform.sql`, runs data-quality checks |
| `server.py` | MCP server for Claude, 3 tools |
| `test.py` | 12 checks that the agent's answers are correct and safe |

## Quick start

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python build.py      # build the database
python test.py       # expect "12 of 12 checks passed"
```

## Connect to Claude

**Claude Desktop:** add to `~/Library/Application Support/Claude/claude_desktop_config.json` and restart the app:
```json
{
  "mcpServers": {
    "simple-marketing": {
      "command": "/ABSOLUTE/PATH/simple-marketing-agent/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/simple-marketing-agent/server.py"]
    }
  }
}
```

**Claude Code:**
```bash
claude mcp add simple-marketing -- /ABSOLUTE/PATH/.venv/bin/python /ABSOLUTE/PATH/server.py
```

Try asking:
- *What was ROAS by channel in September?*
- *Which channel has the lowest CPA?*
- *Are there any data problems?*
- *What was our TikTok ROAS?* (there is no TikTok data; Claude should say so)

---

## How it works

### 1. Raw data with real-world problems

Five problems that come up constantly with marketing data are built into the sample:

| Problem | Where | Fix in `transform.sql` |
|---|---|---|
| **A.** Meta re-sends the same rows | `meta_ads.csv`, Sep 28–30 | `SELECT DISTINCT` |
| **B.** Meta spend is in EUR, Google in USD | `meta_ads.csv` | convert at 1.10 |
| **C.** `utm_source` is typed by hand: `Google`, `google `, `fb`, `adwords` | `crm_orders.csv` | `LOWER(TRIM(...))` + `CASE` mapping |
| **D.** The CRM records some orders twice | `crm_orders.csv` | `GROUP BY order_id` |
| **E.** Google sent no data for Sep 14 | `google_ads.csv` | can't be fixed: a check detects it and the agent warns about it |

### 2. Transformation (`transform.sql`)

1. **`clean_ad_spend`**: spend from both platforms in one table, in USD, no duplicates.
2. **`clean_orders`**: deduplicated orders with a clean channel (`google_ads`, `meta_ads`, `email`, `direct`).
3. **`daily_channel`**: the final table, one row per day × channel with spend, clicks, orders and revenue. This is what the agent reads.

### 3. Data-quality checks (`build.py`)

Each check is a SQL query that returns the **bad** rows: empty result means `OK`, otherwise `WARN`.
Expected output: 3 × OK and 1 × WARN (the Sep 14 gap).

### 4. MCP server (`server.py`)

| Tool | What it does |
|---|---|
| `get_channel_metrics` | spend, clicks, orders, revenue, ROAS, CPA per channel for a period, plus warnings |
| `check_data_quality` | known data problems |
| `run_sql` | any `SELECT` for questions the other tools can't answer |

**What makes the agent reliable:**
1. **The server calculates metrics, not the model.** ROAS and CPA are defined once in SQL, so answers are consistent and testable. ROAS is `SUM(revenue) / SUM(spend)`, not an average of daily ratios.
2. **Answers carry their own warnings.** If the requested period contains a data gap, the response says so, and only when it's relevant (a question about Meta doesn't get a warning about Google).
3. **No made-up numbers.** Asking about a channel that doesn't exist returns an error listing the available channels.
4. **Read-only.** The database is opened with `mode=ro`, so SQLite itself rejects `INSERT`, `UPDATE`, `DELETE` and `DROP`, even if the agent tries.

### 5. Tests (`test.py`)

12 checks in 4 groups:
1. **Correct numbers**: the agent's figures match an independent calculation from the raw CSVs in plain Python (no shared SQL).
2. **Warnings**: the Sep 14 gap is reported; clean periods and unrelated channels get no false warnings.
3. **Honesty**: a question about TikTok returns an error, not a number.
4. **Safety**: `DELETE` and `DROP` are blocked and the data is intact afterwards.

## What the data shows (September 2026, last-click)

| Channel | Spend | Orders | Revenue | ROAS | CPA |
|---|---:|---:|---:|---:|---:|
| Google Ads | $21,755 | 464 | $70,992 | 3.26 | $46.89 |
| Meta Ads | $15,167 | 492 | $60,662 | 4.00 | $30.83 |
| Email | — | 63 | $6,249 | — | — |
| Direct | — | 69 | $6,550 | — | — |

Meta looks more efficient, but Google's figures are missing Sep 14 spend, so Google's ROAS is slightly overstated. This is exactly the kind of caveat the agent is built to surface.

## Simplifications and next steps

| Here | In production |
|---|---|
| fixed EUR→USD rate | daily FX rates table |
| last-click attribution by `utm_source` | several models (first-touch, linear, position-based) compared |
| synthetic data | real connectors |
| SQLite | ClickHouse / BigQuery / Snowflake; the SQL ports with minor changes |
| `build.py` run by hand | scheduled job with an alert on failed checks |
| local MCP server | remote MCP server with authentication |
