"""transcript 아카이브 인덱스: 보유 기업 목록과 파일 조회.

manifest.csv를 단일 소스로 쓴다(회사명·발표일·파일경로). 파일이 실제 로컬에
있는 항목만 노출한다(Windows 시절 원장은 파일이 이 Mac에 없을 수 있음).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summary_lib.config import ROOT, TRANSCRIPTS_DIR  # noqa: E402

MANIFEST = TRANSCRIPTS_DIR / "manifest.csv"


def _norm_basename(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("&", " ")).strip().lower()


@lru_cache(maxsize=1)
def _local_by_basename() -> dict[str, Path]:
    """실제 디스크 파일을 정규화 파일명으로 인덱싱. manifest 경로가 어긋나도
    Q&A가 파일을 찾을 수 있게 하는 안전망(수집기 reconcile이 놓친 경우 대비)."""
    idx: dict[str, Path] = {}
    if TRANSCRIPTS_DIR.exists():
        for p in TRANSCRIPTS_DIR.rglob("*.docx"):
            idx.setdefault(_norm_basename(p.name), p)
    return idx


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
                # manifest 경로가 어긋난 경우 실제 파일을 파일명으로 찾는다.
                alt = _local_by_basename().get(_norm_basename(Path(rel).name))
                if not alt:
                    continue
                path = alt.resolve()
            docs.append(
                Doc(
                    company=(row.get("company") or "").strip(),
                    event=(row.get("event") or "").strip(),
                    event_date=(row.get("event_date") or "").strip(),
                    path=path,
                )
            )
    return docs


def all_companies() -> list[str]:
    """manifest에 있는 모든 회사명 (로컬 파일 유무와 무관).

    종목 인식은 이 목록으로 한다. 그래야 '파일이 없는 기업'과 '아예 모르는 기업'을
    구분해 안내할 수 있다."""
    if not MANIFEST.exists():
        return []
    seen: dict[str, None] = {}
    with MANIFEST.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("company") or "").strip()
            if name and name not in seen:
                seen[name] = None
    return list(seen.keys())


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
