"""Single-process, loopback-only prototype; OAuth tokens stay in server memory."""
import hashlib
import base64
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.services import demo_scan, scan_promotions

BASE_URL = "http://127.0.0.1:8765"
REDIRECT_URI = f"{BASE_URL}/auth/callback"
STATIC = Path(__file__).parent / "static"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


@dataclass
class Session:
    expires: float
    state: str = ""
    verifier: str = ""
    token: str = ""


sessions: dict[str, Session] = {}
app = FastAPI(title="Clearpost", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def credentials() -> tuple[str, str]:
    return os.getenv("GOOGLE_CLIENT_ID", ""), os.getenv("GOOGLE_CLIENT_SECRET", "")


def current_session(request: Request) -> Session | None:
    now = time.time()
    for key in list(sessions):
        if sessions[key].expires <= now:
            sessions.pop(key, None)
    return sessions.get(request.cookies.get("clearpost_session", ""))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
async def status(request: Request) -> dict:
    session = current_session(request)
    return {"configured": all(credentials()), "connected": bool(session and session.token)}


@app.get("/auth/google")
async def authorize(request: Request) -> RedirectResponse:
    client_id, client_secret = credentials()
    if not client_id or not client_secret:
        return RedirectResponse("/?notice=setup", status_code=303)
    current_session(request)
    sessions.pop(request.cookies.get("clearpost_session", ""), None)
    session_id = secrets.token_urlsafe(32)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    sessions[session_id] = Session(expires=time.time() + 600, state=state, verifier=verifier)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT_URI, "response_type": "code",
        "scope": SCOPE, "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "access_type": "online", "prompt": "select_account",
    }), status_code=303)
    response.set_cookie("clearpost_session", session_id, httponly=True, samesite="lax", max_age=3600)
    return response


@app.get("/auth/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    session = current_session(request)
    if not session or not session.state or not secrets.compare_digest(state, session.state):
        raise HTTPException(400, "Invalid or expired sign-in. Please connect again.")
    session.state = ""  # Consume state even when Google reports a declined request.
    if error or not code:
        return RedirectResponse("/?notice=cancelled", status_code=303)
    client_id, client_secret = credentials()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": client_id, "client_secret": client_secret, "code": code,
                "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI,
                "code_verifier": session.verifier,
            })
            response.raise_for_status()
            data = response.json()
            session.token = data["access_token"]
            session.verifier = ""
            session.expires = time.time() + min(int(data.get("expires_in", 3600)), 3600) - 30
    except (httpx.HTTPError, ValueError, KeyError):
        return RedirectResponse("/?notice=failed", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.get("/api/demo")
async def demo() -> dict:
    return demo_scan()


def require_origin(request: Request) -> None:
    if request.headers.get("origin") != BASE_URL:
        raise HTTPException(403, "Open the app at http://127.0.0.1:8765.")


@app.post("/api/scan")
async def scan(request: Request) -> dict:
    require_origin(request)
    session = current_session(request)
    if not session or not session.token:
        raise HTTPException(401, "Connect Gmail to scan your promotions.")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            return await scan_promotions(client, session.token)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            session.token = ""
            raise HTTPException(401, "Your connection expired. Connect Gmail again.") from None
        raise HTTPException(502, "Gmail could not complete the scan. Check API access or retry shortly.") from None
    except httpx.RequestError:
        raise HTTPException(502, "Could not reach Gmail. Check your connection and retry.") from None


@app.post("/api/disconnect")
async def disconnect(request: Request) -> dict:
    require_origin(request)
    sessions.pop(request.cookies.get("clearpost_session", ""), None)
    return {"connected": False}
