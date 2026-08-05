"""transcript 아카이브 인덱스: 보유 기업 목록과 파일 조회.

manifest.csv를 단일 소스로 쓴다(회사명·발표일·파일경로). 파일이 실제 로컬에
있는 항목만 노출한다(Windows 시절 원장은 파일이 이 Mac에 없을 수 있음).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summary_lib.config import ROOT, TRANSCRIPTS_DIR  # noqa: E402

MANIFEST = TRANSCRIPTS_DIR / "manifest.csv"


@dataclass(frozen=True)
class Doc:
    company: str          # manifest 회사명 (예: "NVIDIA Corporation")
    event: str            # 이벤트 전체 문자열
    event_date: str       # YYYY-MM-DD
    path: Path            # 로컬 transcript 파일 절대경로

    @property
    def label(self) -> str:
        return f"{self.company} ({self.event_date})"


def load_docs() -> list[Doc]:
    """manifest에서 로컬에 실제 존재하는 transcript만 로드."""
    if not MANIFEST.exists():
        return []
    docs: list[Doc] = []
    with MANIFEST.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rel = (row.get("file") or "").strip().replace("\\", "/")
            if not rel:
                continue
            path = (ROOT / rel).resolve()
            if not path.exists():
                continue
            docs.append(
                Doc(
                    company=(row.get("company") or "").strip(),
                    event=(row.get("event") or "").strip(),
                    event_date=(row.get("event_date") or "").strip(),
                    path=path,
                )
            )
    return docs


def company_list(docs: list[Doc]) -> list[str]:
    """중복 제거한 보유 기업명 목록 (종목 인식 후보로 LLM에 제공)."""
    seen: dict[str, None] = {}
    for d in docs:
        if d.company and d.company not in seen:
            seen[d.company] = None
    return list(seen.keys())


def docs_for_company(docs: list[Doc], company: str) -> list[Doc]:
    """특정 회사의 transcript를 최신 발표일 우선으로 반환."""
    matched = [d for d in docs if d.company == company]
    return sorted(matched, key=lambda d: d.event_date, reverse=True)
