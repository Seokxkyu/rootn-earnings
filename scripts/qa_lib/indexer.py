"""transcript 청크 임베딩 인덱스 구축·갱신 (증분).

저장물(파일 2개, DB 없음):
  index/chunks.jsonl   각 줄 = {doc_key, label, company, path, chunk_id, text}
  index/embeddings.npy  (N, 1536) float32 — chunks.jsonl 순서와 1:1

증분: 이미 인덱싱한 (path, mtime)은 건너뛴다. 새 transcript만 임베딩한다.
답변 생성은 Grok, 임베딩만 OpenAI(qa_lib.embeddings).

Usage:
  python -m qa_lib.indexer          # 신규분 인덱싱
  python scripts/qa_lib/indexer.py  # 동일
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summary_lib.config import ROOT, LOG_DIR  # noqa: E402
from summary_lib.transcript_io import load_transcript_text  # noqa: E402
from qa_lib import corpus, embeddings  # noqa: E402
from qa_lib.retriever import _chunks  # noqa: E402

log = logging.getLogger("qa_index")

INDEX_DIR = ROOT / "index"
CHUNKS_PATH = INDEX_DIR / "chunks.jsonl"
EMB_PATH = INDEX_DIR / "embeddings.npy"
STATE_PATH = INDEX_DIR / "indexed_files.json"  # {rel_path: mtime}


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def build(verbose: bool = True) -> int:
    """신규·변경 transcript를 임베딩해 인덱스에 추가. 추가한 청크 수 반환."""
    if not embeddings.available():
        log.info("OPENAI_API_KEY 없음 — 인덱싱 생략(키워드 검색만 동작).")
        return 0

    import numpy as np

    INDEX_DIR.mkdir(exist_ok=True)
    state = _load_state()
    docs = corpus.load_docs()

    new_chunks: list[dict] = []
    new_texts: list[str] = []
    for d in docs:
        rel = str(d.path.relative_to(ROOT)) if d.path.is_relative_to(ROOT) else str(d.path)
        try:
            mtime = d.path.stat().st_mtime
        except OSError:
            continue
        if state.get(rel) == mtime:
            continue  # 이미 인덱싱됨(변경 없음)
        try:
            text = load_transcript_text(d.path)
        except Exception as exc:  # noqa: BLE001
            log.warning("본문 로드 실패 %s: %s", d.path.name, exc)
            continue
        for i, ch in enumerate(_chunks(text)):
            new_chunks.append(
                {
                    "doc_key": f"{d.company}|{d.event_date}",
                    "label": d.label,
                    "company": d.company,
                    "path": rel,
                    "chunk_id": i,
                    "text": ch,
                }
            )
            new_texts.append(ch)
        state[rel] = mtime

    if not new_texts:
        if verbose:
            log.info("인덱싱할 신규 transcript 없음.")
        return 0

    log.info("임베딩 생성: 신규 청크 %d개", len(new_texts))
    vecs = np.asarray(embeddings.embed(new_texts), dtype="float32")

    # 기존 인덱스에 append
    if EMB_PATH.exists() and CHUNKS_PATH.exists():
        old = np.load(EMB_PATH)
        vecs = np.vstack([old, vecs])
        mode = "a"
    else:
        mode = "w"
    np.save(EMB_PATH, vecs)
    with CHUNKS_PATH.open(mode, encoding="utf-8") as fh:
        for c in new_chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    log.info("인덱스 갱신 완료: 총 벡터 %d개", vecs.shape[0])
    return len(new_chunks)


def main() -> int:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "qa_index.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    from summary_lib.config import load_env_file

    load_env_file()
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
