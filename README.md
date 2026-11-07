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
