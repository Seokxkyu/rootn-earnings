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


def _roundrobin(*lists):
    """여러 리스트를 번갈아 하나씩 내보낸다."""
    from itertools import chain, zip_longest
    _sentinel = object()
    for item in chain.from_iterable(zip_longest(*lists, fillvalue=_sentinel)):
        if item is not _sentinel:
            yield item


# ── 임베딩 인덱스(선택) ────────────────────────────────────────────────
# index/ 가 있으면 의미 검색을 키워드 점수와 결합한다. 없으면 키워드만 쓴다.
_INDEX_CACHE: dict | None = None


def _load_index():
    """(chunks:list[dict], emb:np.ndarray) 반환. 없으면 None (캐시)."""
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE.get("data")
    _INDEX_CACHE = {}
    try:
        import json
        import numpy as np
        idx_dir = Path(__file__).resolve().parents[2] / "index"
        cpath, epath = idx_dir / "chunks.jsonl", idx_dir / "embeddings.npy"
        if not (cpath.exists() and epath.exists()):
            _INDEX_CACHE["data"] = None
            return None
        chunks = [json.loads(l) for l in cpath.read_text(encoding="utf-8").splitlines() if l.strip()]
        emb = np.load(epath)
        if len(chunks) != emb.shape[0]:
            _INDEX_CACHE["data"] = None
            return None
        _INDEX_CACHE["data"] = (chunks, emb)
        return _INDEX_CACHE["data"]
    except Exception:  # noqa: BLE001 - 인덱스 문제가 검색을 막지 않도록
        _INDEX_CACHE["data"] = None
        return None


def _embedding_ranked(docs: list[Doc], question: str, top_k: int) -> list[tuple[str, str]] | None:
    """임베딩 의미 검색. 인덱스·OPENAI 없으면 None(→키워드 폴백)."""
    data = _load_index()
    if data is None:
        return None
    from qa_lib import embeddings
    if not embeddings.available():
        return None
    chunks, emb = data
    import numpy as np
    # 대상 문서 필터: label(회사명+발표일)과 파일명(basename)으로 매칭.
    want_labels = {d.label for d in docs}
    want_basenames = {d.path.name for d in docs}
    rows = [i for i, c in enumerate(chunks)
            if c.get("label") in want_labels
            or Path(c.get("path", "")).name in want_basenames]
    if not rows:
        return None
    try:
        q = np.asarray(embeddings.embed_one(question), dtype="float32")
    except Exception:  # noqa: BLE001
        return None
    sub = emb[rows]
    sub_n = sub / (np.linalg.norm(sub, axis=1, keepdims=True) + 1e-8)
    qn = q / (np.linalg.norm(q) + 1e-8)
    sims = sub_n @ qn
    order = np.argsort(-sims)[:top_k]
    return [(chunks[rows[i]]["label"], chunks[rows[i]]["text"]) for i in order]


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
    # 1) 임베딩 의미 검색 (인덱스 있으면). 표현이 달라도 의미로 근거를 찾는다.
    emb_hits = _embedding_ranked(docs, question, top_k)

    # 2) 키워드 검색 (항상 수행 — 정확한 숫자·티커·고유명사에 강함).
    # 키워드는 'oil prices'처럼 구 단위로 오므로 단어로 쪼갠다.
    extra_tokens: list[str] = []
    for kw in (extra_terms or []):
        extra_tokens.extend(_terms(kw))
    terms = set(_terms(question) + extra_tokens)
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
    kw_hits = [(label, body) for _, label, body in scored[:top_k]]

    # 3) 하이브리드 병합: 임베딩·키워드 결과를 합치고 중복 제거. 임베딩을 우선
    # 배치하되 키워드 상위도 섞어, 의미·정확매칭 양쪽 강점을 살린다.
    if emb_hits:
        merged: list[tuple[str, str]] = []
        seen: set[str] = set()
        # 라운드로빈으로 번갈아 담아 한쪽으로 치우치지 않게.
        for pair in _roundrobin(emb_hits, kw_hits):
            key = pair[1][:80]
            if key not in seen:
                seen.add(key)
                merged.append(pair)
            if len(merged) >= top_k:
                break
        if merged:
            return merged

    if kw_hits:
        return kw_hits

    # 폴백: 최신 문서 앞부분.
    fallback: list[tuple[str, str]] = []
    for d in docs[:2]:
        try:
            text = load_transcript_text(d.path)
        except Exception:
            continue
        fallback.append((d.label, text[:CHUNK_CHARS]))
    return fallback
