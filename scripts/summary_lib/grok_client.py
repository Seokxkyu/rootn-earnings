from __future__ import annotations

import json
import logging
import time

import requests

from .config import GrokSettings

log = logging.getLogger("summary")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GrokError(RuntimeError):
    pass


def extract_response_text(data: dict) -> str:
    texts = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text", "")
                if text:
                    texts.append(text)
    return "\n".join(texts).strip()


def call_grok(
    settings: GrokSettings,
    *,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    max_attempts: int = 3,
) -> str:
    """Grok responses API 호출. 일시 오류(429/5xx/타임아웃)는 백오프 후 재시도한다."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                f"{settings.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {settings.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.model,
                    "input": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_output_tokens": max_output_tokens,
                    "store": settings.store,
                },
                timeout=settings.timeout_sec,
            )
            if response.status_code in RETRYABLE_STATUS:
                raise GrokError(f"Grok API returned {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
            data = response.json()
            text = extract_response_text(data)
            if not text:
                raise GrokError(
                    "No text output found in Grok response: "
                    + json.dumps(data, ensure_ascii=False)[:1000]
                )
            return text
        except (requests.RequestException, GrokError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            wait_sec = 5 * (3 ** (attempt - 1))
            log.warning(
                "Grok call failed (attempt %d/%d): %s. Retrying in %ds",
                attempt, max_attempts, exc, wait_sec,
            )
            time.sleep(wait_sec)

    raise GrokError(f"Grok call failed after {max_attempts} attempts: {last_error}")
