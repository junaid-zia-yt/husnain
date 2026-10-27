# Firebase Realtime Database (the only telemetry source)

Your application **does not** need SQLite or PostgreSQL. It still requires
Firebase Realtime Database because that is where the IoT device sends values.

## Expected structure

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

The Firebase field names are case-sensitive.

## Development with public read rules

If Firebase rules allow unauthenticated reads to `/patient`, you only need
`FIREBASE_DATABASE_URL`. Public Firebase reads should **not** be used for
private patient data, even when the Django dashboard has a password.

## Protected production database

In Firebase Console -> Project settings -> Service accounts, generate a
service-account key and store it as a private environment variable.

- On Vercel: set `FIREBASE_SERVICE_ACCOUNT_JSON` to the JSON key content.
- Locally: store the JSON file outside the project and set
  `FIREBASE_SERVICE_ACCOUNT_FILE` to its absolute path.

Never commit the key. Configure restrictive Firebase security rules and least
privilege. The Django API reads `/patient` directly using Firebase's REST API.
The dashboard polls snapshots every 2 seconds by default; the optional SSE
endpoint is off by default and may not be suitable for serverless hosting.

Firebase stores the *current source readings*. PulseWard does not write a
second copy of them or save historical telemetry anywhere.
