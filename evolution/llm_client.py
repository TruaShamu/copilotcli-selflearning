"""LLM client factory — supports OpenAI, Azure OpenAI, and OpenAI-compatible endpoints.

Detects which backend to use from environment variables:
  - AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY → Azure OpenAI
    - If endpoint contains /v1/ or AZURE_OPENAI_COMPAT=1, uses standard
      OpenAI client with base_url (for OAI-compatible Azure endpoints)
    - Otherwise uses AzureOpenAI client (for standard deployment-based API)
  - Otherwise → standard OpenAI (uses OPENAI_API_KEY)

Usage:
    from .llm_client import create_client, resolve_model

    client = create_client()
    model = resolve_model("openai/gpt-4.1")
"""

from __future__ import annotations

import os


def is_azure() -> bool:
    """Check if Azure OpenAI credentials are configured."""
    return bool(
        os.environ.get("AZURE_OPENAI_ENDPOINT")
        and os.environ.get("AZURE_OPENAI_API_KEY")
    )


def _is_compat_mode() -> bool:
    """Check if the Azure endpoint uses OpenAI-compatible /v1/ routing."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    return (
        "/v1" in endpoint
        or os.environ.get("AZURE_OPENAI_COMPAT", "").strip() == "1"
    )


def create_client():
    """Create the appropriate OpenAI client based on environment.

    Three modes:
    1. Azure + compat (/v1/ in URL): standard OpenAI client with base_url
    2. Azure standard: AzureOpenAI client (deployment-based routing)
    3. No Azure env vars: standard OpenAI client (uses OPENAI_API_KEY)
    """
    if is_azure():
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        api_key = os.environ["AZURE_OPENAI_API_KEY"]

        if _is_compat_mode():
            from openai import OpenAI

            # Ensure base_url ends with /v1 for the OpenAI SDK
            base_url = endpoint.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = base_url + "/v1" if not base_url.endswith("/openai") else base_url + "/v1"
            return OpenAI(base_url=base_url, api_key=api_key)
        else:
            from openai import AzureOpenAI

            return AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-07-18"),
            )
    else:
        from openai import OpenAI

        return OpenAI()


def resolve_model(model_spec: str) -> str:
    """Resolve a model specifier to the name to pass to the API.

    For standard OpenAI: strips the "openai/" prefix.
        "openai/gpt-4.1" → "gpt-4.1"

    For Azure OpenAI: uses AZURE_OPENAI_MODEL env var if set
    (since Azure uses deployment names, not model names),
    otherwise strips prefix as a best-effort fallback.
    """
    if is_azure():
        override = os.environ.get("AZURE_OPENAI_MODEL")
        if override:
            return override
    # Strip provider prefix
    if "/" in model_spec:
        return model_spec.split("/", 1)[1]
    return model_spec
