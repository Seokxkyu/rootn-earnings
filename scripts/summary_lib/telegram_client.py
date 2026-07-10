from __future__ import annotations

import html
import logging
import time

import requests

from .config import TelegramSettings

log = logging.getLogger("summary")

TELEGRAM_API_BASE_URL = "https://api.telegram.org"


def split_telegram_message(text: str, limit: int) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    parts = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + limit, len(text))
        if end < len(text):
            split_at = text.rfind("\n\n", cursor, end)
            if split_at <= cursor + limit // 2:
                split_at = text.rfind("\n", cursor, end)
            if split_at <= cursor + limit // 2:
                split_at = end
            end = split_at
        parts.append(text[cursor:end].strip())
        cursor = end
    return [part for part in parts if part]


def sanitize_telegram_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    return escaped.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def split_existing_title(body: str) -> tuple[str, str]:
    lines = body.strip().splitlines()
    if lines and lines[0].startswith("<b>") and lines[0].endswith("</b>"):
        title = lines[0].removeprefix("<b>").removesuffix("</b>").strip()
        rest = "\n".join(lines[1:]).strip()
        return title, rest
    return "", body.strip()


def build_telegram_messages(
    summary_results: list[dict],
    *,
    message_limit: int = 3900,
    max_summaries: int | None = None,
) -> list[str]:
    selected = summary_results[:max_summaries] if max_summaries else summary_results
    messages = []
    for result in selected:
        body = result.get("summary", "").strip()
        title, body_without_title = split_existing_title(body)
        title = title or f"{result.get('ticker', 'UNKNOWN')} | {result.get('session', 'Unknown session')}"
        header = f"<b>{title}</b>"
        full_message = f"{header}\n{body_without_title}".strip()
        if len(full_message) <= message_limit:
            messages.append(sanitize_telegram_html(full_message))
            continue
        body_limit = max(1000, message_limit - len(header) - 80)
        chunks = split_telegram_message(body_without_title, limit=body_limit)
        for part_idx, chunk in enumerate(chunks, start=1):
            messages.append(
                sanitize_telegram_html(f"{header}\nPart {part_idx}/{len(chunks)}\n\n{chunk}".strip())
            )
    return messages


def telegram_api(settings: TelegramSettings, method: str, payload: dict | None = None, timeout_sec: int = 60) -> dict:
    response = requests.post(
        f"{TELEGRAM_API_BASE_URL}/bot{settings.bot_token}/{method}",
        json=payload or {},
        timeout=timeout_sec,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Telegram API error {response.status_code}: {response.text}")
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API returned ok=false: {data}")
    return data


def send_messages(
    settings: TelegramSettings,
    messages: list[str],
    *,
    pause_sec: float = 1.0,
    max_attempts: int = 3,
) -> int:
    """모든 메시지를 순차 전송한다. 429는 retry_after를 존중해 재시도한다."""
    sent = 0
    for idx, message in enumerate(messages, start=1):
        for attempt in range(1, max_attempts + 1):
            try:
                telegram_api(
                    settings,
                    "sendMessage",
                    {
                        "chat_id": settings.chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                sent += 1
                log.info("Sent Telegram message %d/%d (%d chars)", idx, len(messages), len(message))
                break
            except RuntimeError as exc:
                if attempt >= max_attempts:
                    raise
                wait_sec = 5 * attempt
                if "429" in str(exc):
                    wait_sec = 35
                log.warning(
                    "Telegram send failed (message %d, attempt %d/%d): %s. Retrying in %ds",
                    idx, attempt, max_attempts, exc, wait_sec,
                )
                time.sleep(wait_sec)
        time.sleep(pause_sec)
    return sent
