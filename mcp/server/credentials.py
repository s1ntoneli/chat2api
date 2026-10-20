import base64
import fcntl
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path

AUTH_DIR = Path(os.getenv('AUTH_DIR', '/secrets'))
AUTH_FILE = AUTH_DIR / 'auth.json'


def expiry(token):
    try:
        return int(json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))['exp'])
    except (ValueError, KeyError, IndexError):
        return 0


def credentials(force=False):
    with (AUTH_DIR / 'auth.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            raw = json.loads(AUTH_FILE.read_text())
            data = raw.get('tokens', raw)
        except (OSError, ValueError):
            raise RuntimeError('AUTH_REQUIRED: install the account credential file on the Linux server.') from None
        token = data.get('access_token', '')
        expires = expiry(token)
        if not force and token and expires > time.time() + 600:
            return data
        refresh = data.get('refresh_token')
        if not refresh:
            if token and expires > time.time() + 60:
                return data
            raise RuntimeError('AUTH_EXPIRED: re-authenticate or update the credential file.')
        body = json.dumps({'grant_type': 'refresh_token', 'refresh_token': refresh,
                           'client_id': data.get('client_id', 'app_EMoamEEZ73f0CkXaXp7hrann')}).encode()
        req = urllib.request.Request('https://auth.openai.com/oauth/token', data=body,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                updated = json.load(response)
        except Exception:
            raise RuntimeError('AUTH_REFRESH_FAILED: account login must be checked; no message was sent.') from None
        if not updated.get('access_token'):
            raise RuntimeError('AUTH_REFRESH_FAILED: no new access token received.')
        data = {**data, **{k: v for k, v in updated.items()
                         if k in ('access_token', 'refresh_token', 'id_token') and v}}
        fd, tmp = tempfile.mkstemp(dir=AUTH_DIR, prefix='.auth-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, AUTH_FILE)
            directory = os.open(AUTH_DIR, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return data


if __name__ == '__main__':
    data = credentials(force='--force' in __import__('sys').argv)
    print(json.dumps({'ok': True, 'expires_in_seconds': expiry(data['access_token']) - int(time.time()),
                      'refresh_enabled': bool(data.get('refresh_token'))}))
