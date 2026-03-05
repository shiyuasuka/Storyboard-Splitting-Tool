from __future__ import annotations

import json
import os
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


class LLMClientError(RuntimeError):
    pass


@dataclass
class LLMSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int
    temperature: float
    max_retries: int
    retry_base_seconds: float
    retry_max_seconds: float


class OpenAICompatibleLLMClient:
    def __init__(self) -> None:
        self.settings = self._load_settings()

    @staticmethod
    def _load_settings() -> LLMSettings:
        api_key = os.getenv("LLM_API_KEY", "").strip()
        if not api_key:
            raise LLMClientError("LLM_API_KEY is required when use_llm=true")

        return LLMSettings(
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
            timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "4")),
            retry_base_seconds=float(os.getenv("LLM_RETRY_BASE_SECONDS", "2.0")),
            retry_max_seconds=float(os.getenv("LLM_RETRY_MAX_SECONDS", "30.0")),
        )

    async def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        payload = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        resp = await self._post_with_retry(payload=payload, headers=headers)

        data = resp.json()
        content = self._extract_content(data)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMClientError(f"LLM did not return valid JSON: {e}") from e

        usage = data.get("usage") or {}
        if isinstance(parsed, dict):
            parsed["_usage"] = {
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            }
        return parsed

    async def _post_with_retry(self, payload: Dict[str, Any], headers: Dict[str, str]) -> httpx.Response:
        attempts = self.settings.max_retries + 1
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                    resp = await client.post(
                        f"{self.settings.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
            except httpx.HTTPError as e:
                last_error = f"transport error: {e}"
                if attempt >= attempts:
                    raise LLMClientError(f"LLM request failed after retries: {last_error}") from e
                await asyncio.sleep(self._compute_retry_sleep(attempt=attempt, retry_after_header=None))
                continue

            if resp.status_code < 400:
                return resp

            text = resp.text
            retryable = self._is_retryable(resp.status_code, text)
            last_error = f"{resp.status_code} {text}"
            if not retryable or attempt >= attempts:
                raise LLMClientError(f"LLM request failed: {last_error}")
            retry_after = resp.headers.get("Retry-After")
            await asyncio.sleep(self._compute_retry_sleep(attempt=attempt, retry_after_header=retry_after))

        raise LLMClientError(f"LLM request failed: {last_error}")

    @staticmethod
    def _is_retryable(status_code: int, body_text: str) -> bool:
        if status_code in {429, 500, 502, 503, 504}:
            return True
        if status_code == 403:
            hints = ["访问过于频繁", "rate limit", "too many requests", "quota", "频繁"]
            low = body_text.lower()
            return any(h in body_text or h in low for h in hints)
        return False

    def _compute_retry_sleep(self, attempt: int, retry_after_header: Optional[str]) -> float:
        if retry_after_header:
            try:
                retry_after = float(retry_after_header)
                if retry_after > 0:
                    return min(retry_after, self.settings.retry_max_seconds)
            except ValueError:
                pass
        base = self.settings.retry_base_seconds * (2 ** (attempt - 1))
        return min(base, self.settings.retry_max_seconds)

    @staticmethod
    def _extract_content(resp_json: Dict[str, Any]) -> str:
        choices = resp_json.get("choices") or []
        if not choices:
            raise LLMClientError("LLM response has no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "".join(parts)
        raise LLMClientError("Unsupported LLM response content format")
