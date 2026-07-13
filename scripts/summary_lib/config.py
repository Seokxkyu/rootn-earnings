from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
TRANSCRIPTS_DIR = ROOT / "transcripts"
RUNS_DIR = ROOT / "output" / "collection_runs"
SUMMARY_ROOT = ROOT / "output" / "summaries" / "grok"
LOG_DIR = ROOT / "logs"
LATEST_BATCH_PATH = SUMMARY_ROOT / "latest_batch.json"


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class GrokSettings:
    api_key: str
    model: str = "grok-4.5"
    base_url: str = "https://api.x.ai/v1"
    timeout_sec: int = 600
    store: bool = False

    @classmethod
    def from_env(cls) -> "GrokSettings":
        api_key = os.getenv("XAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Set XAI_API_KEY in .env or the environment first.")
        return cls(
            api_key=api_key,
            model=os.getenv("XAI_MODEL", "grok-4.5").strip() or "grok-4.5",
            base_url=os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/"),
        )


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    chat_id: str
    message_limit: int = 3900

    @classmethod
    def from_env(cls) -> "TelegramSettings":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first.")
        return cls(bot_token=token, chat_id=chat_id)

    @classmethod
    def alert_from_env(cls) -> "TelegramSettings":
        """장애 알림 전용 봇 설정. ALERT_BOT_TOKEN이 없으면 기본 요약 봇으로 폴백한다.
        ALERT_CHAT_ID가 없으면 요약과 동일한 TELEGRAM_CHAT_ID로 보낸다."""
        token = os.getenv("ALERT_BOT_TOKEN", "").strip()
        if not token:
            return cls.from_env()
        chat_id = os.getenv("ALERT_CHAT_ID", "").strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not chat_id:
            raise RuntimeError("Set ALERT_CHAT_ID or TELEGRAM_CHAT_ID in .env first.")
        return cls(bot_token=token, chat_id=chat_id)
