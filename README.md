# PulseWard: Django + Firebase telemetry monitor (no SQL database)

This refactor removes SQLite and the Django ORM entirely. **No PostgreSQL, SQLite,
Redis, migrations, or writable local storage is required.** Live patient readings
still come from **Firebase Realtime Database**, an external database that the IoT
device already writes to.

## Architecture

```text
IoT sensor -> Firebase Realtime Database (/patient)
                             |
                             v
              Django /api/live/ (read-only REST)
                             |
                             v
              Authenticated dashboard (browser)
                 |                    |
             BPM/temp cards      ECG plot + recent history

Login: env username/password -> signed session cookie (no Django User table)
```

## Firebase input contract

The app reads **one** JSON object, at `/patient`:

```json
{
  "patient": {
    "BPM": 71,
    "ECG": 1895,
    "Temperature": 85,
    "Timestamp": 33695
  }
}
```

`FIREBASE_DATABASE_URL` defaults to the URL configured in the original project.
BPM is labeled in BPM; the project **does not assume** calibrated engineering
units for ECG, Temperature, or Timestamp.

## What changed

- Removed `db.sqlite3`, `VitalSnapshot` model, migrations, Django admin, and
  `create_default_user` (all depended on SQL tables).
- Replaced Django `User` authentication with `DASHBOARD_USERNAME` and
  `DASHBOARD_PASSWORD` configured as environment variables.
- Sessions use Django **signed-cookie** backend, not database sessions.
- Live API fetches values from Firebase but never writes readings to SQLite.
- BPM/temperature history and ECG samples are retained **in the current browser
  tab only**. Refreshing or closing the page clears the displayed history.
- Server-Sent Events remain optional (`ENABLE_SSE=True`) for hosts that support
  long-running streams. The default Vercel-friendly mode fetches new snapshots
  every `POLL_INTERVAL_MS` (2000ms by default).

## Run locally

Create a Python 3.12 virtual environment and run:

```bash
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env, set DJANGO_DEBUG=True, a strong DJANGO_SECRET_KEY,
# DASHBOARD_USERNAME and DASHBOARD_PASSWORD.
python manage.py runserver
```

Windows users can replace `cp .env.example .env` with `copy .env.example .env`.
Open http://127.0.0.1:8000 and log in using your chosen environment credentials.

There is no default doctor/Hospital@123 login in the distributed files.
**Do not run `migrate` or `createsuperuser`; neither is needed or supported.**

## Deploy to Vercel

See [DEPLOYMENT.md](DEPLOYMENT.md). Vercel supports Django projects with
`manage.py` and `WSGI_APPLICATION` without a custom legacy `vercel.json`.
Configure the environment variables in Vercel, redeploy, then open `/login/`.

## Security and clinical limitations

- Do not check `.env`, private keys, or service-account JSON into Git. None
  are included in the distributed project ZIP.
- Restrict Firebase read rules in production; supplying only a public
  Firebase URL does **not** make Firebase data private.
- Login limits access to the Django dashboard, not an independently
  publicly readable Firebase database.
- The signed cookie is readable but tamper-resistant, so the session contains
  only a credentials-bound identifier. Changing dashboard credentials revokes
  sessions by making that identifier invalid. Logging out clears the browser
  session, but previously copied signed cookies may remain replayable until
  expiration or credentials rotation.
- This is single-user environment-based authentication, with **no** per-user
  access control, server-side session revocation, login rate limiting, durable
  history, audit trail, or alerting. Do not treat it as production-ready for
  clinical decision-making or regulated patient information without adding
  an appropriate identity provider, security controls, and compliant storage.
- Actual ECG waveform fidelity depends entirely on incoming hardware samples:
  the graph does not synthesize beats or smooth over missing samples.

## Tests

```bash
python manage.py test
python manage.py check
```

Set the environment variables described above before running Django commands.
# husnain
# husnain
"# husnain" 
