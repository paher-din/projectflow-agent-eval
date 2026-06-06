import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import settings as app_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exception hierarchy — each failure mode maps to a distinct, clear error.
# ---------------------------------------------------------------------------


class LLMError(RuntimeError):
    """Base for all LLM client errors."""

    def __init__(self, message: str, *, provider: str = "", detail: str = ""):
        self.provider = provider
        self.detail = detail
        super().__init__(message)


class LLMConfigurationError(LLMError, ValueError):
    """Raised when provider settings are incomplete or unsupported."""


class LLMAuthError(LLMError):
    """Raised when the API key is missing, empty, or rejected by the provider."""


class LLMTimeoutError(LLMError):
    """Raised when the LLM request exceeds the configured timeout."""


class LLMConnectionError(LLMError):
    """Raised when the LLM endpoint is unreachable (network / DNS / refused)."""


class LLMResponseError(LLMError):
    """Raised when the provider returns an unexpected HTTP status or malformed body."""


# ---------------------------------------------------------------------------
# Protocol & settings
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    def complete(self, messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
        """Return the assistant message content."""


@dataclass(frozen=True)
class LLMClientSettings:
    provider: str = "mock"
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 30.0


# ---------------------------------------------------------------------------
# Mock client (offline / demo / tests)
# ---------------------------------------------------------------------------


class MockLLMClient:
    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or []
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
        self.calls += 1
        if not self.responses:
            return "{}"
        index = min(self.calls - 1, len(self.responses) - 1)
        return self.responses[index]


# ---------------------------------------------------------------------------
# OpenAI-compatible client (real provider)
# ---------------------------------------------------------------------------


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
    ):
        if not api_key or not api_key.strip():
            raise LLMAuthError(
                "LLM API key is required for OpenAI-compatible providers but was empty",
                provider="openai-compatible",
                detail="Set LLM_API_KEY in .env or pass api_key to build_llm_client()",
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._owns_http_client = http_client is None
        self._transport = transport
        self._http: httpx.Client | None = http_client

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                timeout=httpx.Timeout(self.timeout_seconds),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                transport=self._transport,
                trust_env=False,
            )
        return self._http

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.05,
            "max_tokens": max_tokens or 1800,
        }
        try:
            response = self._client().post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            # Raise for 4xx/5xx
            self._check_response(response)
            payload: dict[str, Any] = response.json()
        except httpx.TimeoutException:
            raise LLMTimeoutError(
                f"LLM request timed out after {self.timeout_seconds}s",
                provider="openai-compatible",
                detail=f"model={self.model} base_url={self.base_url}",
            )
        except httpx.HTTPStatusError as exc:
            self._raise_http_error(exc)
        except httpx.RequestError as exc:
            raise LLMConnectionError(
                f"Cannot reach LLM endpoint: {exc}",
                provider="openai-compatible",
                detail=f"Check LLM_BASE_URL and network. base_url={self.base_url}",
            ) from exc
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"LLM response was not valid JSON: {exc}",
                provider="openai-compatible",
                detail=f"model={self.model} base_url={self.base_url}",
            ) from exc

        # Validate response structure
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(
                f"LLM response missing expected structure: {exc}",
                provider="openai-compatible",
                detail=f"response keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}",
            )
        return content

    def close(self) -> None:
        """Close the underlying HTTP client, releasing pooled connections."""
        if self._owns_http_client and self._http is not None:
            self._http.close()

    # ------------------------------------------------------------------
    # Error translation helpers
    # ------------------------------------------------------------------

    def _check_response(self, response: httpx.Response) -> None:
        """Check for HTTP errors (the httpx way — called before .json())."""
        if response.status_code < 400:
            return
        exc = httpx.HTTPStatusError(
            f"HTTP {response.status_code}",
            request=response.request,
            response=response,
        )
        self._raise_http_error(exc)

    def _raise_http_error(self, exc: httpx.HTTPStatusError) -> None:
        """Translate HTTP status codes into specific LLM errors."""
        status = exc.response.status_code
        if status == 401:
            raise LLMAuthError(
                "LLM API key was rejected (HTTP 401 Unauthorized)",
                provider="openai-compatible",
                detail="Verify LLM_API_KEY is correct.",
            ) from exc
        if status == 403:
            raise LLMAuthError(
                "LLM API key lacks permission (HTTP 403 Forbidden)",
                provider="openai-compatible",
                detail="Check API key scopes and provider account access.",
            ) from exc
        if status == 404:
            raise LLMConfigurationError(
                f"LLM model or endpoint not found (HTTP 404): model={self.model}",
                provider="openai-compatible",
                detail="Verify LLM_MODEL and LLM_BASE_URL.",
            ) from exc
        if status == 429:
            raise LLMError(
                "LLM rate limit exceeded (HTTP 429)",
                provider="openai-compatible",
                detail="Retry after a delay or reduce request volume.",
            ) from exc
        if status >= 500:
            raise LLMConnectionError(
                f"LLM provider server error (HTTP {status})",
                provider="openai-compatible",
                detail="Provider may be temporarily unavailable.",
            ) from exc
        raise LLMResponseError(
            f"Unexpected HTTP {status} from LLM provider",
            provider="openai-compatible",
            detail="Provider returned an unexpected HTTP status.",
        ) from exc


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_llm_client(settings: LLMClientSettings | None = None) -> LLMClient:
    selected = settings or LLMClientSettings(
        provider=app_settings.llm_provider,
        api_key=app_settings.llm_api_key.get_secret_value() if app_settings.llm_api_key else None,
        base_url=app_settings.llm_base_url,
        model=app_settings.llm_model,
        timeout_seconds=app_settings.llm_timeout_seconds,
    )
    provider = selected.provider.lower()
    if provider == "mock":
        return MockLLMClient()
    if provider in {"openai", "openai-compatible"}:
        if not selected.api_key:
            raise LLMAuthError(
                "LLM_API_KEY is required for OpenAI-compatible providers but was not set",
                provider=provider,
                detail="Set LLM_API_KEY in .env or pass api_key to build_llm_client()",
            )
        return OpenAICompatibleLLMClient(
            api_key=selected.api_key,
            base_url=selected.base_url,
            model=selected.model,
            timeout_seconds=selected.timeout_seconds,
        )
    raise LLMConfigurationError(
        f"Unsupported LLM provider: {selected.provider!r}",
        provider=selected.provider,
        detail="Supported providers: mock, openai, openai-compatible",
    )


def build_agent_llm_client() -> LLMClient:
    """Build the real Agent client with the Agent generation timeout.

    Diagnostics intentionally keep using LLM_TIMEOUT_SECONDS so connectivity
    checks stay fast. Agent generation gets its own longer default because
    structured planning responses are slower than a dry-run health check.
    """
    return build_llm_client(
        LLMClientSettings(
            provider=app_settings.llm_provider,
            api_key=app_settings.llm_api_key.get_secret_value() if app_settings.llm_api_key else None,
            base_url=app_settings.llm_base_url,
            model=app_settings.llm_model,
            timeout_seconds=app_settings.llm_agent_timeout_seconds,
        )
    )
