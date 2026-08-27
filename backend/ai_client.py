from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Protocol
from urllib.parse import quote

import httpx


PROVIDER_RUNTIME_METADATA_KEY = "_adhyantra_provider_runtime"


class AIProviderError(RuntimeError):
    def __init__(self, message: str, *, provider_metadata: Dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.provider_metadata = dict(provider_metadata or {})


class AIProvider(Protocol):
    provider_name: str
    model_name: str

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        ...


@dataclass
class OpenAICompatibleProvider:
    provider_name: str
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float = 30.0
    supports_json_response_format: bool = True

    @property
    def model_name(self) -> str:
        return self.model

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.supports_json_response_format:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        endpoint = self.base_url.rstrip("/") + "/chat/completions"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIProviderError(f"{self.provider_name} request failed: {_safe_http_error_summary(exc)}") from exc

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Provider returned empty content.")
            return _parse_json_text(content)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"{self.provider_name} response parsing failed: {exc}") from exc


@dataclass
class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, model: str, base_url: str, timeout_seconds: float = 30.0) -> None:
        super().__init__(
            provider_name="openai",
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )


@dataclass
class GroqProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, model: str, base_url: str, timeout_seconds: float = 30.0) -> None:
        super().__init__(
            provider_name="groq",
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )


@dataclass
class MistralProvider(OpenAICompatibleProvider):
    """OpenAI-compatible Mistral path for explicit QA/testing only."""

    def __init__(self, api_key: str, model: str, base_url: str, timeout_seconds: float = 30.0) -> None:
        super().__init__(
            provider_name="mistral",
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )


@dataclass
class GeminiProvider:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float = 30.0
    provider_name: str = "gemini"

    @property
    def model_name(self) -> str:
        return self.model

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        model_path = _gemini_model_path(self.model)
        endpoint = f"{self.base_url.rstrip('/')}/{model_path}:generateContent?key={self.api_key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "candidateCount": 1,
                "responseMimeType": "application/json",
            },
        }
        headers = {"Content-Type": "application/json"}

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIProviderError(f"gemini request failed: {type(exc).__name__}") from exc

        try:
            body = response.json()
            content = _extract_gemini_text(body)
            if not content.strip():
                raise ValueError("Provider returned empty content.")
            return _parse_json_text(content)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"gemini response parsing failed: {exc}") from exc


@dataclass
class ProviderRouter:
    providers: list[AIProvider]
    provider_name: str = "router"
    model_name: str = ""
    configured_provider_chain: list[str] | None = None
    unavailable_provider_reasons: list[str] | None = None
    last_provider_name: str | None = None
    last_model_name: str | None = None
    last_attempted_provider_names: list[str] | None = None
    last_fallback_used: bool = False
    last_fallback_reason: str | None = None

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        errors: list[str] = list(self.unavailable_provider_reasons or [])
        attempted: list[str] = []
        configured_chain = list(self.configured_provider_chain or [])
        self.last_provider_name = None
        self.last_model_name = None
        self.last_fallback_used = False
        self.last_fallback_reason = None
        self.last_attempted_provider_names = configured_chain or attempted

        for provider in self.providers:
            provider_name = str(getattr(provider, "provider_name", provider.__class__.__name__) or "").strip() or "unknown"
            attempted.append(provider_name)
            try:
                payload = provider.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
            except AIProviderError as exc:
                errors.append(f"{provider_name}: {exc}")
                continue

            self.last_provider_name = provider_name
            self.last_model_name = str(getattr(provider, "model_name", "") or "").strip() or None
            self.last_fallback_used = bool(errors)
            self.last_fallback_reason = "; ".join(errors) if errors else None
            self.last_attempted_provider_names = configured_chain or attempted
            return _with_provider_metadata(
                payload,
                {
                    "provider_name": self.last_provider_name,
                    "model_name": self.last_model_name,
                    "attempted_provider_chain": list(self.last_attempted_provider_names or []),
                    "provider_fallback_used": self.last_fallback_used,
                    "provider_fallback_reason": self.last_fallback_reason,
                },
            )

        self.last_fallback_used = bool(errors)
        self.last_fallback_reason = "; ".join(errors) if errors else "No configured live AI provider was available."
        self.last_attempted_provider_names = configured_chain or attempted
        raise AIProviderError(
            f"All configured live AI providers failed. {self.last_fallback_reason}",
            provider_metadata={
                "provider_name": "mock",
                "model_name": None,
                "attempted_provider_chain": list(self.last_attempted_provider_names or []),
                "provider_fallback_used": self.last_fallback_used,
                "provider_fallback_reason": self.last_fallback_reason,
            },
        )


def _parse_json_text(content: str) -> Dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Provider JSON root must be an object.")
    return parsed


def _gemini_model_path(model: str) -> str:
    cleaned_model = str(model or "").strip().strip("/")
    if not cleaned_model:
        cleaned_model = "gemini-2.5-flash"
    if cleaned_model.startswith("models/"):
        return quote(cleaned_model, safe="/")
    return f"models/{quote(cleaned_model, safe='')}"


def _extract_gemini_text(body: Dict[str, Any]) -> str:
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        prompt_feedback = body.get("promptFeedback")
        raise ValueError(f"Gemini returned no candidates. promptFeedback={_safe_json_fragment(prompt_feedback)}")

    first_candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    finish_reason = str(first_candidate.get("finishReason") or "").strip()
    content = first_candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ValueError(f"Gemini returned no text parts. finishReason={finish_reason or 'unknown'}")

    text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
    if not text.strip():
        raise ValueError(f"Gemini returned empty text. finishReason={finish_reason or 'unknown'}")
    return text


def _safe_json_fragment(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)[:300]
    except (TypeError, ValueError):
        return type(value).__name__


def _safe_http_error_summary(exc: httpx.HTTPError) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code:
        return f"HTTP {status_code}"
    return type(exc).__name__


def _with_provider_metadata(payload: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    normalized_payload = dict(payload)
    normalized_payload[PROVIDER_RUNTIME_METADATA_KEY] = dict(metadata)
    return normalized_payload
