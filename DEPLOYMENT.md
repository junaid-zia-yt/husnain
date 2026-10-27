# Deploy PulseWard on Vercel without SQLite/PostgreSQL

Vercel's Django support discovers `manage.py` and the WSGI/ASGI application.
There is no need for a legacy `/api` adapter or `vercel.json` rewrite on
modern Vercel deployments. Static files are collected using `STATIC_ROOT`.

## 1. Set Vercel environment variables

Vercel Dashboard -> Project -> Settings -> Environment Variables:

| Variable | Value / requirement |
| --- | --- |
| `DJANGO_DEBUG` | `False` (required for production security) |
| `DJANGO_SECRET_KEY` | New long random secret; consistent across deployments |
| `DJANGO_ALLOWED_HOSTS` | Exact Vercel deployment host, e.g. `example.vercel.app` (comma-separated if needed) |
| `DASHBOARD_USERNAME` | Your chosen login (no SQL User table) |
| `DASHBOARD_PASSWORD` | Strong, unique login password |
| `FIREBASE_DATABASE_URL` | Existing Firebase Realtime Database HTTPS URL |
| `FIREBASE_PATIENT_PATH` | `patient` |
| `POLL_INTERVAL_MS` | `2000` (or another interval >= 1000ms) |
| `ENABLE_SSE` | `False` on Vercel (recommended) |

For protected Firebase rules, set **one** of:

- `FIREBASE_SERVICE_ACCOUNT_JSON`: full service-account JSON (one environment
  variable, secret). Recommended when using a service account on Vercel.
- `FIREBASE_AUTH_TOKEN`: Firebase Realtime Database compatible auth token.

`FIREBASE_SERVICE_ACCOUNT_FILE` still works locally on hosts with persistent
secret files, but a local private-key filepath won't automatically exist in
Vercel's container. Restrict the service account to the minimum permissions.

**Never place credentials in a Git repository or a public/static directory.**

## 2. Deploy

Push the project root to your Vercel-connected Git repository. The files
`manage.py`, `requirements.txt`, `health_monitor/` and `static/` must be in
the configured Vercel root directory. Python 3.12 is selected by the
`.python-version` file. Redeploy after editing environment variables.

Open `https://YOUR-HOST/login/` and authenticate using the credentials you
configured. Your session is held in a secure, HTTP-only signed cookie, so
it works across serverless function instances.

## 3. Verify

1. GET `/` while logged out: redirects to `/login/`.
2. POST valid credentials on `/login/`: redirects to `/`.
3. GET `/api/live/` while logged in: returns `ok: true` with Firebase readings.
4. GET `/api/live/` logged out: returns HTTP 401 JSON.
5. No `migrate`, `createsuperuser` or SQL provisioning step is needed.

If Firebase requests return HTTP 503, validate the URL, security rules,
credentials, and `/patient` structure. No demo readings are substituted.

## Important tradeoffs

- Vercel serverless functions have execution duration limits, so the dashboard
  defaults to short Firebase REST polling rather than holding a permanent SSE
  connection. An optional SSE endpoint exists for suitable long-running hosts.
- Polling every 2 seconds is not a substitute for high-frequency ECG sampling.
- History is in browser memory only and disappears on refresh. There is no
  database-backed historical report or Django admin.
- Credential-based stateless login is appropriate only for a limited-scope
  prototype, not a clinical multi-user system: add proper IAM and audit logging
  for real hospital deployment.
