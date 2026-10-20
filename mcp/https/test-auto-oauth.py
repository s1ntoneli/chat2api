"""Root-only, plain HTTP OAuth acceptance test. Never follows ChatGPT callbacks."""
import argparse
import base64
import hashlib
import html.parser
import http.client
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

CONFIG = Path('/opt/chatgpt-mcp/private-connection.json')
TOKENS = Path('/opt/chatgpt-mcp/auto-oauth-test-tokens.json')
REDIRECT = 'https://chatgpt.com/connector_platform_oauth_redirect'


class TestFailure(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class LocalHTTPSHandler(urllib.request.HTTPSHandler):
    """Keep HTTPS URL/cookie semantics while routing to staging loopback HTTP."""

    def __init__(self, mcp_port):
        super().__init__()
        self.mcp_port = mcp_port

    def https_open(self, request):
        path = urllib.parse.urlsplit(request.full_url).path
        port = 19091 if path.startswith('/auth/') else self.mcp_port

        def connection(_logical_host, timeout=30, **kwargs):
            return http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)

        return self.do_open(connection, request)


class HiddenFields(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'input' and values.get('type') == 'hidden' and values.get('name'):
            self.fields[values['name']] = values.get('value', '')


def require(condition):
    if not condition:
        raise TestFailure()


def save_tokens(record):
    # Atomic replacement; reject symlink destinations and preserve root-only access.
    require(not TOKENS.is_symlink())
    temp = TOKENS.with_name(TOKENS.name + '.' + secrets.token_hex(6))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, TOKENS)
    finally:
        if temp.exists():
            temp.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh-only', action='store_true')
    parser.add_argument('--negative-pkce', action='store_true')
    parser.add_argument('--cimd-client', nargs='?', const='https://chatgpt.com/oauth/client.json',
                        choices=['https://chatgpt.com/oauth/client.json'],
                        help='Test the real ChatGPT CIMD flow through callback only; OpenAI holds its signing key.')
    parser.add_argument('--local-port', type=int, help='Stage MCP over loopback HTTP; Authelia uses port 19091.')
    args = parser.parse_args()
    require(args.local_port is None or 1 <= args.local_port <= 65535)
    require(not (args.refresh_only and args.negative_pkce))
    require(not args.cimd_client or not (args.refresh_only or args.negative_pkce))
    require(os.geteuid() == 0)
    cfg = json.loads(CONFIG.read_text())
    resource = cfg['mcp_url']
    origin = resource.rsplit('/', 1)[0]
    issuer = origin + '/auth'
    origin_parts = urllib.parse.urlsplit(origin)
    require(origin_parts.scheme == 'https')
    cookies = http.cookiejar.CookieJar()
    handlers = [urllib.request.HTTPCookieProcessor(cookies), NoRedirect()]
    if args.local_port:
        # Ignore environment HTTPS proxies only for explicit staging loopback mode.
        handlers.extend([urllib.request.ProxyHandler({}), LocalHTTPSHandler(args.local_port)])
    opener = urllib.request.build_opener(*handlers)
    stage = 'start'
    results = {}

    def request(url, data=None, form=False):
        parsed = urllib.parse.urlsplit(url)
        # All requests stay on our server; callbacks to chatgpt.com are parsed only.
        require(parsed.scheme == 'https' and parsed.netloc == origin_parts.netloc)
        headers = {'User-Agent': 'ChatGPT-MCP-OAuth-Acceptance/1.0', 'Accept': 'application/json,text/html'}
        if args.local_port:
            headers.update({'Host': origin_parts.netloc, 'X-Forwarded-Proto': 'https',
                            'X-Forwarded-Host': origin_parts.netloc})
        if data is not None:
            headers['Content-Type'] = ('application/x-www-form-urlencoded' if form else 'application/json')
            data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
        try:
            response = opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=45)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read().decode()
            status = response.code
            headers_out = response.headers
        print(json.dumps({'stage': stage, 'http_status': status}), flush=True)
        return status, headers_out, body

    def location(headers):
        target = headers.get('Location')
        require(bool(target))
        return urllib.parse.urljoin(origin, target)

    def refresh(record):
        nonlocal stage
        stage = 'refresh'
        tokens = record['tokens']
        status, _, body = request(origin + '/token', {
            'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token'],
            'client_id': record['client_id'], 'resource': resource,
        }, form=True)
        require(status == 200)
        updated = json.loads(body)
        require(bool(updated.get('access_token')))
        require(updated.get('token_type', '').lower() == 'bearer')
        # A standards-compliant server may retain the previous refresh token.
        if not updated.get('refresh_token'):
            updated['refresh_token'] = tokens['refresh_token']
        record['tokens'] = updated
        save_tokens(record)
        results['refresh'] = True

    try:
        if args.refresh_only:
            stage = 'load_saved_tokens'
            info = TOKENS.lstat()
            require(not TOKENS.is_symlink() and info.st_uid == 0 and info.st_mode & 0o077 == 0)
            record = json.loads(TOKENS.read_text())
            require(record['resource'] == resource)
            refresh(record)
            results['refresh_after_restart'] = True
        else:
            stage = 'protected_resource_metadata'
            status, _, body = request(origin + '/.well-known/oauth-protected-resource/mcp')
            require(status == 200)
            metadata = json.loads(body)
            require(metadata.get('resource') == resource)
            require(origin in metadata.get('authorization_servers', []) or origin + '/' in metadata.get('authorization_servers', []))
            stage = 'authorization_metadata'
            status, _, body = request(origin + '/.well-known/oauth-authorization-server')
            require(status == 200)
            metadata = json.loads(body)
            require(metadata.get('registration_endpoint') == origin + '/register')
            require(metadata.get('client_id_metadata_document_supported') is True)
            require('none' in metadata.get('token_endpoint_auth_methods_supported', []))
            results['dcr_and_cimd_advertised'] = True

            if args.cimd_client:
                # Its public document was verified independently. The server must
                # fetch and validate it; no substitute document or key is used.
                client_id = args.cimd_client
            else:
                stage = 'dynamic_registration'
                status, _, body = request(origin + '/register', {
                    'client_name': 'HTTP acceptance test', 'redirect_uris': [REDIRECT],
                    'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
                    'scope': 'openid offline_access', 'token_endpoint_auth_method': 'none',
                    'application_type': 'web',
                })
                require(status in (200, 201))
                registered = json.loads(body)
                client_id = registered['client_id']
                require(bool(client_id) and client_id != cfg['client_id'])
                require(registered.get('client_secret') is None)
                require(registered.get('token_endpoint_auth_method') == 'none')
                results['public_dcr_without_secret'] = True

            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            state = secrets.token_urlsafe(24)
            auth_params = dict(client_id=client_id, redirect_uri=REDIRECT, response_type='code',
                               scope='openid offline_access', resource=resource, state=state,
                               code_challenge=challenge, code_challenge_method='S256')
            stage = 'proxy_authorization'
            status, headers, _ = request(origin + '/authorize?' + urllib.parse.urlencode(auth_params))
            require(status in (302, 303, 307))
            consent_url = location(headers)
            require(urllib.parse.urlsplit(consent_url).path == '/consent')
            stage = 'proxy_consent_page'
            status, _, body = request(consent_url)
            require(status == 200)
            fields = HiddenFields()
            fields.feed(body)
            require(bool(fields.fields.get('txn_id')) and bool(fields.fields.get('csrf_token')))
            fields.fields['action'] = 'approve'
            stage = 'proxy_consent_approval'
            status, headers, _ = request(consent_url, fields.fields, form=True)
            require(status in (302, 303))
            upstream_auth_url = location(headers)
            upstream_params = urllib.parse.parse_qs(urllib.parse.urlsplit(upstream_auth_url).query)
            require(upstream_params.get('client_id') == [cfg['client_id']])
            require(upstream_params.get('redirect_uri') == [origin + '/oauth/callback'])
            require(upstream_params.get('code_challenge_method') == ['S256'])
            require(upstream_params.get('code_challenge') != [challenge])
            results['proxy_consent_and_separate_upstream_pkce'] = True

            stage = 'authelia_initial_authorization'
            status, _, _ = request(upstream_auth_url)
            require(status in (302, 303))
            stage = 'authelia_login'
            status, _, _ = request(issuer + '/api/firstfactor', dict(
                username=cfg['username'], password=cfg['password'], keepMeLoggedIn=False,
                targetURL=upstream_auth_url, requestMethod='GET'))
            require(status == 200)
            stage = 'authelia_authorization'
            status, headers, _ = request(upstream_auth_url)
            require(status in (302, 303))
            flow_id = urllib.parse.parse_qs(urllib.parse.urlsplit(location(headers)).query)['flow_id'][0]
            stage = 'authelia_consent_metadata'
            status, _, body = request(issuer + '/api/oidc/consent?' + urllib.parse.urlencode({'flow_id': flow_id}))
            require(status == 200)
            consent = json.loads(body)['data']
            stage = 'authelia_consent_approval'
            status, _, body = request(issuer + '/api/oidc/consent', dict(
                flow_id=flow_id, client_id=cfg['client_id'], consent=True, pre_configure=False,
                claims=consent.get('claims') or []))
            require(status == 200)
            resume_url = json.loads(body)['data']['redirect_uri']
            stage = 'authelia_resume'
            status, headers, _ = request(resume_url)
            require(status in (302, 303))
            callback = location(headers)
            callback_parts = urllib.parse.urlsplit(callback)
            require(callback_parts.path == '/oauth/callback')
            require(urllib.parse.parse_qs(callback_parts.query).get('iss') == [issuer])
            stage = 'proxy_upstream_callback'
            status, headers, _ = request(callback)
            require(status in (302, 303))
            downstream_callback = location(headers)
            downstream_parts = urllib.parse.urlsplit(downstream_callback)
            require(downstream_parts.scheme + '://' + downstream_parts.netloc + downstream_parts.path == REDIRECT)
            query = urllib.parse.parse_qs(downstream_parts.query)
            require(query.get('state') == [state])
            require(query.get('iss') in ([origin], [origin + '/']))
            require(bool(query.get('code')))
            results['upstream_login_callback_and_state'] = True

            if args.cimd_client:
                # The official document selects private_key_jwt. Only ChatGPT
                # can sign its client assertion. Check unauthenticated exchange
                # fails closed, and never persist this unused authorization code.
                results['cimd_authorization_callback'] = True
                stage = 'cimd_missing_client_assertion'
                status, _, body = request(origin + '/token', dict(
                    grant_type='authorization_code', code=query['code'][0], client_id=client_id,
                    redirect_uri=REDIRECT, resource=resource, code_verifier=verifier), form=True)
                require(status == 401)
                require(json.loads(body).get('error') == 'invalid_client')
                results['private_key_jwt_required'] = True
                results['cimd_token_exchange_tested'] = False
                results['requires_chatgpt_private_key_for_final_exchange'] = True
                print(json.dumps({'success': True, **results}), flush=True)
                return 0

            stage = 'wrong_pkce' if args.negative_pkce else 'client_pkce_exchange'
            status, _, body = request(origin + '/token', dict(
                grant_type='authorization_code', code=query['code'][0], client_id=client_id,
                redirect_uri=REDIRECT, resource=resource,
                code_verifier=secrets.token_urlsafe(48) if args.negative_pkce else verifier), form=True)
            if args.negative_pkce:
                require(status in (400, 401))
                require(json.loads(body).get('error') == 'invalid_grant')
                results['wrong_pkce_rejected'] = True
            else:
                require(status == 200)
                tokens = json.loads(body)
                require(bool(tokens.get('access_token')) and bool(tokens.get('refresh_token')))
                require(tokens.get('token_type', '').lower() == 'bearer')
                record = {'client_id': client_id, 'resource': resource, 'tokens': tokens}
                save_tokens(record)
                results['client_pkce_exchange'] = True
                refresh(record)
        print(json.dumps({'success': True, **results}), flush=True)
        return 0
    except Exception:
        # HTTP bodies, exception messages, URLs, codes and tokens are never printed.
        print(json.dumps({'success': False, 'failed_stage': stage, **results}), flush=True)
        return 1


if __name__ == '__main__':
    os.umask(0o077)
    try:
        sys.exit(main())
    except Exception:
        print(json.dumps({'success': False, 'failed_stage': 'configuration'}), flush=True)
        sys.exit(1)
