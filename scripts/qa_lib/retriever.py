"""대상 기업 transcript에서 질문 관련 청크를 검색.

MVP는 임베딩 없이 키워드 점수(용어 빈도 + 근접) 기반. 한 기업당 transcript가
소수(보통 1~수 개)라 전량 스캔해도 즉답. 규모가 커지면 임베딩으로 교체 가능.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summary_lib.transcript_io import load_transcript_text  # noqa: E402
from qa_lib.corpus import Doc  # noqa: E402

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200
STOP = set("the a an of to in on for and or is are was were be as at by with that this it".split())


def _chunks(text: str) -> list[str]:
    text = re.sub(r"\s+\n", "\n", text)
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + CHUNK_CHARS])
        i += CHUNK_CHARS - CHUNK_OVERLAP
    return out


def _terms(q: str) -> list[str]:
    toks = re.findall(r"[A-Za-z가-힣0-9]+", q.lower())
    return [t for t in toks if t not in STOP and len(t) > 1]


def _score(chunk: str, terms: list[str]) -> int:
    low = chunk.lower()
    return sum(low.count(t) for t in terms)


def _idf_weights(entries: list[tuple[str, str, str]], terms: set[str]) -> dict[str, float]:
    """희소한 용어에 큰 가중치. 회사명처럼 모든 청크에 나오는 흔한 말이 점수를
    지배해 정작 결정적인 문구('total revenue')를 밀어내는 것을 막는다."""
    n = len(entries)
    weights: dict[str, float] = {}
    for t in terms:
        df = sum(1 for _, _, low in entries if t in low)
        weights[t] = math.log(1 + n / df) if df else 0.0
    return weights


def search(
    docs: list[Doc],
    question: str,
    top_k: int = 5,
    extra_terms: list[str] | None = None,
) -> list[tuple[str, str]]:
    """대상 기업 문서들에서 상위 청크 반환: [(출처라벨, 청크본문), ...].

    extra_terms는 한→영 변환 등 LLM이 뽑은 검색어(영어 transcript 매칭용).
    질문 용어가 하나도 안 걸리면 각 문서 앞부분(개요)을 폴백으로 준다.
    """
    terms = set(_terms(question) + [t.lower() for t in (extra_terms or [])])
    entries: list[tuple[str, str, str]] = []  # (label, 원문청크, 소문자청크)
    for d in docs:
        try:
            text = load_transcript_text(d.path)
        except Exception:
            continue
        for ch in _chunks(text):
            entries.append((d.label, ch, ch.lower()))

    scored: list[tuple[float, str, str]] = []
    if entries and terms:
        weights = _idf_weights(entries, terms)
        for label, ch, low in entries:
            s = sum(low.count(t) * weights[t] for t in terms if weights[t])
            if s > 0:
                scored.append((s, label, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return [(label, body) for _, label, body in scored[:top_k]]

    # 폴백: 최신 문서 앞부분.
    fallback: list[tuple[str, str]] = []
    for d in docs[:2]:
        try:
            text = load_transcript_text(d.path)
        except Exception:
            continue
        fallback.append((d.label, text[:CHUNK_CHARS]))
    return fallback
