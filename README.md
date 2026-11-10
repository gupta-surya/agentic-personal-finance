# agentic-personal-finance
Pulls data from Plaid to then securely analyze spend and improve budgeting. 

## Look at the charts locally

Two processes: the chart API and the web app. Both stay on your machine (127.0.0.1).

```
# 1. API: synthetic data, no setup (pin "today" to the sample data's range)
CHARTS_TODAY=2026-10-25 .venv/bin/uvicorn finance_agent.serve_charts:app --host 127.0.0.1 --port 8000

# 2. Web app, in another terminal
cd web && npm install && npm run dev      # open http://127.0.0.1:5173
```

The page header says **Synthetic data** or **Your data**.

### Your own data (Postgres)

The API reads one tenant from a **non-test** database, read-only: a connection is opened
per request and can't write. A database whose name ends in `_test` is refused (the test
suite drops its schema).

```
docker compose up -d
docker compose exec db createdb -U finance finance_dev
# apply the migrations to finance_dev, and load data with the ingest pipeline

CHARTS_DATABASE_URL=postgresql://finance:finance@127.0.0.1:5432/finance_dev \
CHARTS_TENANT_ID=demo-tenant \
  .venv/bin/uvicorn finance_agent.serve_charts:app --host 127.0.0.1 --port 8000
```

The API returns aggregates and category names only, never merchant text or line items.
An unreachable database gives a plain "The database is unavailable." (no connection
details). A tenant with no data draws empty charts, not an error.

## Use your own data (self-serve)

One cross-platform install (needs Docker for the local database; Ollama is optional
for categorizing new merchants). The CLI runs natively so it can reach your OS and a
host Ollama; Docker is managed for you for Postgres.

```
# If you already have uv (https://astral.sh/uv):
uv tool install git+https://github.com/gupta-surya/agentic-personal-finance.git
finance setup

# Or bootstrap uv + the tool in one line:
#   macOS / Linux
curl -LsSf https://raw.githubusercontent.com/gupta-surya/agentic-personal-finance/main/install/install.sh | sh
#   Windows (PowerShell)
irm https://raw.githubusercontent.com/gupta-surya/agentic-personal-finance/main/install/install.ps1 | iex
```

`finance setup` walks you through it: it checks Docker and Ollama, creates a private
local database, takes your SimpleFIN setup token (claimed once, then discarded), asks
which accounts are credit cards, and runs a first sync. Then:

```
finance sync      # pull new transactions, reconcile and categorize
finance status    # database / bank / last sync / model
finance review    # set a category for anything rules did not cover
```

Your transaction data never leaves your machine. The bank access URL is encrypted at
rest (AES-256-GCM) in a credentials table isolated from your data, with the key in a
0600 file outside the database; it is never logged, never in the environment, and never
in the repo. Set `FINANCE_TZ` (e.g. `America/New_York`) so transaction dates use your
local calendar; it defaults to UTC.
