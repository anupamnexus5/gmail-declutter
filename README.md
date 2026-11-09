# Clearpost

A separate, local Gmail subscription-discovery app. FastAPI + plain HTML/CSS/JavaScript.

## First increment

- Responsive dashboard with explicitly labeled fictional demo data.
- Google OAuth authorization code flow with state and PKCE.
- Read-only scan of up to 100 promotional messages from the last 90 days.
- Groups by List-Id, falling back to sender. Counts describe only scanned messages.
- Shows advertised unsubscribe support. No unsubscribe requests, email sending, archive, or deletion yet.
- Tokens live only in server memory and expire within one hour. Restarting disconnects all sessions.

SQLite is deferred until we need durable action history; there is no persistent email data yet.

## Run

Use Python 3.11 or later:

```bash
cd /home/kaneki/Downloads/gmail-declutter
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --no-access-log
```

Open http://127.0.0.1:8765. Demo mode works without Google credentials.
Use the exact address above, not localhost. Run one worker only. Access logs are disabled to avoid recording OAuth callback authorization codes.

## Connect Gmail

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the Gmail API in APIs & Services.
3. Configure Google Auth Platform branding and audience. For a personal Gmail account, use External, keep it in Testing, and add your own Gmail address as a test user.
4. Add the `https://www.googleapis.com/auth/gmail.readonly` scope under Data Access.
5. Create an OAuth client with application type **Web application**. Set its authorized redirect URI to exactly `http://127.0.0.1:8765/auth/callback`.
6. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the terminal environment before starting the server. `.env.example` documents their names; the app does not automatically read `.env` files. Do not commit or share credentials.
7. Restart, click Connect Gmail, approve access, then Scan promotions.

Gmail's readonly scope permits reading messages, but this app only requests metadata headers. It is used because the narrower metadata scope does not support the Gmail search query used here. No message body is requested.

Local disconnect forgets the token; it does not revoke Google's grant. Remove the app in your [Google account connections](https://myaccount.google.com/connections) to revoke access. Reconnect when the short-lived token expires. No refresh token is requested or stored.

## Tests

```bash
python -m pytest
```

Tests use mocked Gmail responses, not your mailbox. Live OAuth requires your configured Google client and consent and is not covered by these tests.

## Next increment

Implement explicit subscription selection and standards-compliant unsubscribe requests, including validation of untrusted destination URLs, request results, retries, and SQLite action history. An advertised one-click header alone is not proof of a trustworthy sender or a successful unsubscribe.

This prototype is for loopback personal use. Public deployment requires a separate review of authentication, durable encrypted token storage, OAuth verification, and deployment security.

## References

- [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Message search](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)
- [Message metadata](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get)
- [OAuth web server flow](https://developers.google.com/identity/protocols/oauth2/web-server)
