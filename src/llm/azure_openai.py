"""Azure OpenAI endpoint and authentication helpers."""

import re
from functools import lru_cache
from typing import Any, Callable, Dict
from urllib.parse import urlsplit


AZURE_OPENAI_ENDPOINT_HINT = "https://<resource>.openai.azure.com"


def is_azure_openai_endpoint(base_url: str) -> bool:
    """Only send the process identity to an Azure OpenAI resource endpoint."""
    try:
        url = urlsplit(base_url)
        return (
            url.scheme == "https"
            and re.fullmatch(r"[a-z0-9-]+\.openai\.azure\.com", url.hostname or "") is not None
            and url.port in (None, 443)
            and "@" not in url.netloc
            and url.path in ("", "/")
            and not url.query
            and not url.fragment
        )
    except ValueError:
        return False


@lru_cache(maxsize=1)
def _get_azure_token_provider() -> Callable[[], str]:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    return get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )


def _get_azure_token() -> str:
    return _get_azure_token_provider()()


def azure_openai_auth_params(model: str, base_url: str, api_key: str) -> Dict[str, Callable[[], str]]:
    if model.startswith("azure/") and not api_key and is_azure_openai_endpoint(base_url):
        return {"azure_ad_token_provider": _get_azure_token}
    return {}


def normalize_azure_openai_token_limit(call_kwargs: Dict[str, Any], wire_model: str) -> None:
    """Use Azure Chat Completions' token cap without relying on LiteLLM's model catalog."""
    if wire_model.startswith("azure/") and "max_tokens" in call_kwargs:
        max_tokens = call_kwargs.pop("max_tokens")
        call_kwargs.setdefault("max_completion_tokens", max_tokens)
