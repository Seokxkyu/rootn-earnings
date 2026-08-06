"""OpenAI 임베딩 클라이언트 (답변 생성은 Grok, 임베딩만 OpenAI).

xAI는 임베딩 모델을 제공하지 않아 임베딩만 OpenAI text-embedding-3-small을 쓴다.
OPENAI_API_KEY가 없으면 사용 불가(호출부에서 폴백 처리).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

MODEL = "text-embedding-3-small"
DIM = 1536
ENDPOINT = "https://api.openai.com/v1/embeddings"
BATCH = 128
MAX_ATTEMPTS = 4


def available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _post(texts: list[str], key: str) -> list[list[float]]:
    body = json.dumps({"model": MODEL, "input": texts}).encode()
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            # index 순서 보장 위해 정렬
            items = sorted(data["data"], key=lambda x: x["index"])
            return [it["embedding"] for it in items]
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"임베딩 실패: {last}")


def embed(texts: list[str]) -> list[list[float]]:
    """텍스트 목록을 임베딩 벡터로. 배치로 나눠 호출."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 없습니다.")
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        out.extend(_post(texts[i : i + BATCH], key))
    return out


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
