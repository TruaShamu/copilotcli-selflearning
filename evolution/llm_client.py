"""LLM client factory — supports OpenAI and Azure OpenAI.

Detects which backend to use from environment variables:
  - AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY → AzureOpenAI
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


def create_client():
    """Create the appropriate OpenAI client based on environment.

    Returns an AzureOpenAI client if AZURE_OPENAI_ENDPOINT and
    AZURE_OPENAI_API_KEY are set, otherwise a standard OpenAI client.
    """
    if is_azure():
        from openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
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
