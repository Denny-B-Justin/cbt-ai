"""Shared by ai/mai-chatgpt.py and ai/mai-claude.py: Azure sign-in for the World Bank mAI gateway, and schema clean-up."""

from __future__ import annotations

import copy
import os
import threading

from utils import constants as C

TIMEOUT_S = 180.0

_credential = None
_credential_key: tuple | None = None
_lock = threading.Lock()


def _azure_settings() -> tuple:
    return tuple((os.getenv(name) or "").strip()
                 for name in (C.ENV_AZURE_TENANT, C.ENV_AZURE_CLIENT_ID, C.ENV_AZURE_SECRET))


def is_configured(base_url_env: str = C.ENV_MAI_BASE_URL) -> bool:
    return all(_azure_settings()) and bool(base_url(base_url_env)) and bool(token_scope())


def base_url(env: str = C.ENV_MAI_BASE_URL) -> str:
    return (os.getenv(env) or "").strip()


def token_scope() -> str:
    return (os.getenv(C.ENV_MAI_TOKEN_SCOPE) or "").strip()


def model_name(default: str) -> str:
    return (os.getenv(C.ENV_MAI_LLM) or default).strip()


def headers() -> dict:
    return {"x-source-type": "interactive", "x-team-name": (os.getenv(C.ENV_MAI_TEAM) or "").strip()}


def access_token() -> str:
    """A bearer token for the gateway. azure-identity caches it and refreshes it shortly before it expires."""
    global _credential, _credential_key
    from azure.core.exceptions import ClientAuthenticationError
    from azure.identity import ClientSecretCredential

    from .types import AIConfigError

    settings = _azure_settings()
    with _lock:
        if _credential is None or _credential_key != settings:
            tenant, client_id, secret = settings
            _credential = ClientSecretCredential(tenant_id=tenant, client_id=client_id, client_secret=secret)
            _credential_key = settings
        credential = _credential
    try:
        return credential.get_token(token_scope()).token
    except ClientAuthenticationError as exc:
        raise AIConfigError("Azure sign-in for mAI failed: %s" % " ".join(str(exc).split())[:300]) from exc


def strict_schema(schema: dict) -> dict:
    """Copy of the schema with additionalProperties=false on every object, as strict structured output requires."""
    schema = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema
