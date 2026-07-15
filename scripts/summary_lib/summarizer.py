from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from . import prompts
from .config import ROOT, SUMMARY_ROOT, GrokSettings
from .grok_client import call_grok
from .metadata import (
    extract_metadata_block,
    extract_quarter,
    extract_session,
    extract_ticker,
    title_label,
)
from .transcript_io import load_transcript_text, norm, slugify

log = logging.getLogger("summary")


def split_text(text: str, max_chars: int) -> list[str]:
    text = norm(text)
    if len(text) <= max_chars:
        return [text]
    chunks = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + max_chars, len(text))
        if end < len(text):
            split_at = text.rfind(" ", cursor, end)
            if split_at > cursor + max_chars // 2:
                end = split_at
        chunks.append(text[cursor:end].strip())
        cursor = end
    return [chunk for chunk in chunks if chunk]


def summary_md_path(transcript_path: Path) -> Path:
    """요약 md 저장 경로. transcript의 날짜 폴더명을 그대로 따라간다.

    예: transcripts/2026-07-10/X.docx -> output/summaries/grok/2026-07-10/X.md
    """
    return SUMMARY_ROOT / transcript_path.parent.name / f"{slugify(transcript_path.stem)}.md"


def summarize_file(settings: GrokSettings, path: Path) -> dict:
    transcript_text = load_transcript_text(path)
    try:
        display_path = path.relative_to(ROOT)
    except ValueError:
        display_path = path

    metadata_block = extract_metadata_block(display_path, transcript_text)
    ticker = extract_ticker(transcript_text)
    title = title_label(transcript_text, path.stem)  # 제목용: 회사명 (티커)
    quarter = extract_quarter(transcript_text)
    session = extract_session(transcript_text)
    chunks = split_text(transcript_text, max_chars=prompts.CHUNK_CHAR_LIMIT)

    if len(chunks) <= 1:
        # 1-pass: 원문을 최종 프롬프트에 직접 투입한다. 청크 요약 단계를 생략해
        # 정보 손실·번역투 전파·맥락 단절을 피한다.
        log.info("  1-pass (원문 직접 투입, %d자)", len(transcript_text))
        final_source = transcript_text
    else:
        # multi-pass: 초장문만 청크별로 사실 추출 후 합쳐서 최종 요약한다.
        log.info("  multi-pass (%d청크)", len(chunks))
        chunk_summaries = []
        for chunk_idx, chunk in enumerate(chunks, start=1):
            log.info("  chunk %d/%d", chunk_idx, len(chunks))
            chunk_summary = call_grok(
                settings,
                system_prompt=prompts.CHUNK_SYSTEM_PROMPT,
                user_prompt="[METADATA]\n" + metadata_block + "\n\n[CHUNK]\n" + chunk,
                max_output_tokens=prompts.CHUNK_SUMMARY_MAX_OUTPUT_TOKENS,
            )
            chunk_summaries.append(f"### Chunk {chunk_idx}\n{chunk_summary}")
            time.sleep(prompts.REQUEST_PAUSE_SEC)
        final_source = "\n\n".join(chunk_summaries)

    final_prompt = prompts.FINAL_USER_PROMPT_TEMPLATE
    final_prompt = final_prompt.replace("{{TICKER}}", title)
    final_prompt = final_prompt.replace("{{QUARTER}}", quarter)
    final_prompt = final_prompt.replace("{{SESSION}}", session)
    final_prompt = final_prompt.replace("{{METADATA}}", metadata_block)
    final_prompt = final_prompt.replace("{{TRANSCRIPT}}", final_source)

    final_summary = call_grok(
        settings,
        system_prompt=prompts.FINAL_SYSTEM_PROMPT,
        user_prompt=final_prompt,
        max_output_tokens=prompts.FINAL_SUMMARY_MAX_OUTPUT_TOKENS,
    )

    md_path = summary_md_path(path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(final_summary, encoding="utf-8")

    return {
        "file_name": path.name,
        "source_file": str(display_path),
        "ticker": ticker,
        "quarter": quarter,
        "session": session,
        "model": settings.model,
        "source_characters": len(transcript_text),
        "chunk_count": len(chunks),
        "summary": final_summary,
        "summary_file": str(md_path.relative_to(ROOT)),
        "summarized_at": datetime.now().isoformat(),
    }


def summarize_files(
    settings: GrokSettings,
    paths: list[Path],
    *,
    force: bool = False,
) -> tuple[list[dict], list[Path]]:
    """파일들을 순차 요약한다. 요약 md가 이미 있으면 스킵한다(멱등성).

    Returns (새로 생성된 결과 목록, 스킵된 파일 목록).
    """
    results: list[dict] = []
    skipped: list[Path] = []
    for idx, path in enumerate(paths, start=1):
        md_path = summary_md_path(path)
        if md_path.exists() and not force:
            log.info("[%d/%d] Skipping (summary exists): %s", idx, len(paths), path.name)
            skipped.append(path)
            continue
        log.info("[%d/%d] Summarizing %s", idx, len(paths), path.name)
        results.append(summarize_file(settings, path))
        time.sleep(prompts.REQUEST_PAUSE_SEC)
    return results, skipped
