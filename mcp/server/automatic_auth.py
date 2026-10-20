"""Standards-based OAuth registration in the shared MCP server."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from http_auth import OIDCTokenVerifier


class UpstreamVerifier(TokenVerifier):
    def __init__(self, issuer, resource, client_id, jwks_url):
        super().__init__(required_scopes=['openid', 'offline_access'])
        self.delegate = OIDCTokenVerifier(issuer, resource, client_id, jwks_url)

    async def verify_token(self, token):
        validated = await self.delegate.verify_token(token)
        if validated is None:
            return None
        # Claims are exposed only after the existing strict signature/claim checks.
        claims = jwt.decode(token, options={'verify_signature': False})
        data = validated.model_dump()
        data['claims'] = claims
        data['subject'] = claims['sub']
        return AccessToken(**data)


def create_auth(public_url):
    cfg = json.loads(Path(os.getenv('AUTH_DIR', '/secrets'), 'proxy-auth.json').read_text())
    base = public_url.rsplit('/', 1)[0]
    issuer = os.environ['OIDC_ISSUER']
    return OAuthProxy(
        upstream_authorization_endpoint=issuer + '/api/oidc/authorization',
        upstream_token_endpoint=issuer + '/api/oidc/token',
        upstream_client_id=cfg['client_id'],
        upstream_client_secret=cfg['client_secret'],
        token_endpoint_auth_method='client_secret_post',
        token_verifier=UpstreamVerifier(issuer, public_url, cfg['client_id'], os.environ['OIDC_JWKS_URL']),
        base_url=base,
        redirect_path='/oauth/callback',
        allowed_client_redirect_uris=[
            'https://chatgpt.com/connector_platform_oauth_redirect',
            'https://chatgpt.com/connector/oauth/*',
        ],
        valid_scopes=['openid', 'offline_access'],
        extra_authorize_params={'scope': 'openid offline_access', 'resource': public_url},
        extra_token_params={'resource': public_url},
        jwt_signing_key=cfg['signing_key'].encode(),
        require_authorization_consent=True,
        enable_cimd=True,
    )
