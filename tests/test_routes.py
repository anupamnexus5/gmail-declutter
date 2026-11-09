import time
from urllib.parse import parse_qs, urlparse
import pytest
from fastapi.testclient import TestClient
from app.main import app, sessions, Session


@pytest.fixture
def client():
    sessions.clear()
    with TestClient(app) as client:
        yield client
    sessions.clear()


def test_dashboard_and_demo(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'Clearpost' in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/api/demo').json()['demo'] is True


def test_missing_credentials_show_setup(client, monkeypatch):
    monkeypatch.delenv('GOOGLE_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOOGLE_CLIENT_SECRET', raising=False)
    assert client.get('/api/status').json()['configured'] is False
    assert client.get('/auth/google', follow_redirects=False).headers['location'] == '/?notice=setup'


def test_oauth_state_pkce_and_replay(client, monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'test-client')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'secret')
    response = client.get('/auth/google', follow_redirects=False)
    params = parse_qs(urlparse(response.headers['location']).query)
    assert params['code_challenge_method'] == ['S256']
    assert 'secret' not in response.headers['location']
    assert 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/auth/callback?state=wrong&code=test').status_code == 400
    state = params['state'][0]
    assert client.get('/auth/callback', params={'state': state, 'error': 'access_denied'}, follow_redirects=False).status_code == 303
    assert client.get('/auth/callback', params={'state': state, 'code': 'test'}).status_code == 400


def test_scan_requires_origin_and_connection(client):
    assert client.post('/api/scan').status_code == 403
    assert client.post('/api/scan', headers={'origin': 'http://127.0.0.1:8765'}).status_code == 401


def test_expired_tokens_are_removed(client):
    sessions['expired'] = Session(expires=time.time()-1, token='private')
    client.cookies.set('clearpost_session', 'expired')
    assert client.get('/api/status').json()['connected'] is False
    assert 'expired' not in sessions


def test_disconnect_clears_token(client):
    sessions['connected'] = Session(expires=time.time()+100, token='private')
    client.cookies.set('clearpost_session', 'connected')
    response = client.post('/api/disconnect', headers={'origin': 'http://127.0.0.1:8765'})
    assert response.status_code == 200
    assert not sessions


def test_unknown_host_is_rejected(client):
    assert client.get('/', headers={'host': 'untrusted.example'}).status_code == 400
