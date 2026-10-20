import asyncio
from urllib.parse import urlsplit

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken


class OIDCTokenVerifier:
    """Validate resource-specific Authelia access JWTs. Never accept upstream ChatGPT tokens."""

    def __init__(self, issuer, resource, client_id, jwks_url):
        self.issuer = issuer
        self.resource = resource
        self.client_id = client_id
        self.keys = PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5,
                                headers={'X-Forwarded-Proto': 'https',
                                         'X-Forwarded-Host': urlsplit(issuer).netloc})

    def _verify(self, token):
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') != 'RS256' or header.get('typ', '').lower() != 'at+jwt':
                return None
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=['RS256'], audience=self.resource,
                                issuer=self.issuer, options={'require': ['exp', 'iat', 'sub', 'aud', 'iss']}, leeway=10)
            if claims.get('client_id') != self.client_id:
                return None
            scopes = claims.get('scope', claims.get('scp', []))
            scopes = scopes.split() if isinstance(scopes, str) else scopes
            if not isinstance(scopes, list) or 'openid' not in scopes:
                return None
            return AccessToken(token=token, client_id=self.client_id, scopes=scopes,
                               expires_at=claims['exp'], resource=self.resource)
        except Exception:
            # Invalid, expired, wrong-audience and unresolvable tokens all fail closed.
            return None

    async def verify_token(self, token):
        return await asyncio.to_thread(self._verify, token)
