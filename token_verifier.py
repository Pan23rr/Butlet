import logging
from typing import Any

import httpx2

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url

logger = logging.getLogger(__name__)


class IntrospectionTokenVerifier(TokenVerifier):
    """Token verifier that uses OAuth 2.0 Token Introspection (RFC 7662)."""

    def __init__(
        self,
        introspection_endpoint: str,
        server_url: str,
        client_id: str,
        client_secret: str,
    ):
        self.introspection_endpoint = introspection_endpoint
        self.server_url = server_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.resource_url = resource_url_from_server_url(server_url)

        self.normalized_resource_url = self.resource_url.rstrip("/")

        self.introspection_audience = self.client_id


    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token via introspection endpoint."""
        if not self.introspection_endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            return None


        timeout = httpx2.Timeout(10.0, connect=5.0)
        limits = httpx2.Limits(max_connections=10, max_keepalive_connections=5)

        async with httpx2.AsyncClient(
            timeout=timeout,
            limits=limits,
            verify=True,
        ) as client:
            try:
                form_data = {
                    "token": token,
                }

                headers = {"Content-Type": "application/x-www-form-urlencoded"}

                response = await client.post(
                    self.introspection_endpoint,
                    data=form_data,
                    headers=headers,
                    auth=(self.client_id, self.client_secret),

                )

                if response.status_code != 200:
                    logger.error(
                        "Token introspection failed: status=%s body=%s",
                        response.status_code,
                        response.text,
                    )
                    return None

                data: dict[str, Any] = response.json()

                logger.debug("Token introspection response: %s", data)

                if not data.get("active", False):
                    logger.warning("Token is inactive")
                    return None

                if not self._validate_resource(data):
                    logger.warning(
                        "Token audience does not match MCP resource. "
                        "aud=%r expected_resource=%r introspection_client=%r",
                        data.get("aud"),
                        self.resource_url,
                        self.client_id,
                    )
                    return None

                scopes = (
                    data.get("scope", "").split()
                    if data.get("scope")
                    else []
                )

                return AccessToken(
                    token=token,

                    client_id=data.get("client_id", "unknown"),

                    scopes=scopes,

                    expires_at=data.get("exp"),
                    resource=self.resource_url,

                    subject=data.get("sub"),

                    claims=data,
                )

            except Exception:
                logger.exception("Token introspection failed")
                return None

    def _validate_resource(self, token_data: dict[str, Any]) -> bool:
        """Validate token was issued for this resource server.

        Rules:
        - Reject if 'aud' missing.
        - Accept if any audience entry matches the derived resource URL.
        - Supports string or list forms per JWT spec.
        """
        if not self.server_url or not self.resource_url:
            return False

        aud: list[str] | str | None = token_data.get("aud")
        if isinstance(aud, list):
            return any(self._is_valid_resource(a) for a in aud)
        if isinstance(aud, str):
            return self._is_valid_resource(aud)
        return False

    def _is_valid_resource(self, audience: str) -> bool:


        if not audience:
            return False

        normalized_audience = audience.rstrip("/")

        if normalized_audience == self.normalized_resource_url:
            return True

        if audience == self.introspection_audience:
            return True

        return False