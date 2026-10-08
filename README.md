# Personal Finance Behavior Dashboard — backend

## AI-generated setup guide

This first milestone uses Flask and Plaid Sandbox to connect one simulated
institution and fetch fake transactions. No frontend, database, authentication,
manual transactions, or behavioral calculations are included yet.

### Files

- `app.py`: HTTP routes, input validation, CORS, and safe error responses.
- `plaid_service.py`: official Plaid SDK calls and one in-memory access token.
- `requirements.txt`: Python packages; no npm packages are needed.
- `.env.example`: empty credential fields and local configuration defaults.
- `.gitignore`: excludes `.env`, virtual environments, and Python caches.
- `test_backend.py`: offline tests using mocked Plaid responses.

### Run locally

Requires Python 3.10 or newer. From the repository directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally to enter your Plaid client ID and **Sandbox** secret. Keep
`PLAID_ENV=sandbox`. Never paste credentials into chat or commit `.env`.
Environment variables override `.env`; restart after changing settings.

```sh
python app.py
```

Server: `http://127.0.0.1:3001`. It can start without credentials, but Plaid
endpoints return `503 PLAID_NOT_CONFIGURED` until credentials are supplied.
The permitted frontend origin defaults to `http://localhost:5173`.

### Token flow

Backend creates link token → frontend opens Plaid Link → Link returns public
token → backend exchanges public token → backend keeps access token in memory.
The backend never returns the access token. Restarting disconnects the demo
account. A new exchange replaces the previous connected institution.

For backend-only tests, the Sandbox public-token endpoint bypasses Link.
See [Plaid Quickstart](https://plaid.com/docs/quickstart/) and
[Sandbox API](https://plaid.com/docs/api/sandbox/).

### Test each endpoint

1. Check server health; expect `200`, `environment: sandbox` and
   `plaid_configured: true` after setting credentials:

```sh
curl -s http://127.0.0.1:3001/api/health
```

2. Create a link token; expect `link_token` and `expiration`:

```sh
curl -s -X POST http://127.0.0.1:3001/api/plaid/link-token
```

3. Create a test public token. This creates a fake Sandbox institution:

```sh
curl -s -X POST http://127.0.0.1:3001/api/plaid/sandbox-public-token
```

4. Copy that response's public token into the following JSON. Expect
   `{"connected": true}`. Tokens are temporary; use a fresh token if necessary:

```sh
curl -s -X POST http://127.0.0.1:3001/api/plaid/exchange-token \
  -H 'Content-Type: application/json' \
  -d '{"public_token":"PASTE_SANDBOX_PUBLIC_TOKEN_HERE"}'
```

5. Retrieve the last 90 days of fake transactions:

```sh
curl -s http://127.0.0.1:3001/api/transactions
```

Optional: append `?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` inside a quoted
URL. Dates must be valid and ordered. If Plaid returns `PRODUCT_NOT_READY`,
wait briefly and retry. All pages are fetched; transactions are not saved.
Plaid amounts are positive for money leaving an account and negative for money
entering it. Keep currency and pending status when later computing summaries.

This milestone uses `/transactions/get` for date-range snapshots. Plaid
recommends `/transactions/sync` for new integrations; consider it when adding
stored transaction updates. See the
[Transactions API](https://plaid.com/docs/api/products/transactions/).

### Offline verification

```sh
python -m unittest -v test_backend
git check-ignore .env
```

Mocked tests cover missing credentials, invalid requests, pagination, Sandbox
enforcement, and token privacy. Run the curl sequence to verify actual Sandbox
connectivity; passing offline tests alone does not verify credentials.

### Scope and secrets

Credentials come from `os.environ` after `python-dotenv` loads `.env`. Plaid's
host is fixed to Sandbox, and other environments are rejected. No secrets are
hardcoded. The SDK uses `certifi`'s trusted root certificates to verify HTTPS,
including on macOS Python installations without a system certificate bundle.
There is one shared demo account per process, so this milestone is
for local testing. Before Render deployment, configure environment variables
and a production HTTP server; multiple workers would have separate token state.

### Render deployment

Create a Python **Web Service** connected to this repository:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120`
- Health check path: `/api/health`
- Environment variables: `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV=sandbox`,
  and `FRONTEND_ORIGIN` set to your deployed frontend's exact origin (no trailing
  slash). Enter credentials in Render, never in the repository.
- Let Render supply `PORT`; do not copy the local `PORT=3001` setting.

Gunicorn imports `app:app`, so the local Flask development server is not started.
Use one worker and one instance while the token remains in memory. All visitors
share the same Sandbox connection; another exchange replaces it. Restarts,
redeployments, and service spin-down clear it. Reconnect afterward. CORS controls
browser access; it is not authentication for these public demo endpoints.

After deployment, repeat the five endpoint tests above using the Render URL.
The health endpoint checks that the process is running; it does not check Plaid
availability or prove credentials are valid. No deployment has been performed
by this setup guide.

See [Render's Flask guide](https://render.com/docs/deploy-flask) and
[port requirements](https://render.com/docs/web-services#port-binding).

This guide and initial code were generated with Codex. Add your own project
description and learning notes, and maintain a separate prompt log for your
class submission.
