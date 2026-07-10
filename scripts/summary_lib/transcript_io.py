from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .config import ROOT, RUNS_DIR, TRANSCRIPTS_DIR

log = logging.getLogger("summary")

SUPPORTED_SUFFIXES = {".docx", ".pdf"}


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def slugify(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*]", " ", value or "")
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value or "unknown"


def read_docx_text(path: Path) -> str:
    from docx import Document

    document = Document(path)
    lines = [norm(paragraph.text) for paragraph in document.paragraphs]
    return "\n".join(line for line in lines if line)


def read_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = [norm(page.extract_text() or "") for page in reader.pages]
    return "\n".join(part for part in parts if part)


def load_transcript_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx_text(path)
    if suffix == ".pdf":
        return read_pdf_text(path)
    raise ValueError(f"Unsupported transcript format: {path.suffix}")


def choose_transcript_files(input_dir: Path, format_preference: list[str]) -> list[Path]:
    """같은 이름의 docx/pdf가 함께 있으면 선호 형식 하나만 선택한다."""
    preference_rank = {fmt.lower(): i for i, fmt in enumerate(format_preference)}
    candidates = [
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    grouped: dict[str, list[Path]] = {}
    for path in candidates:
        grouped.setdefault(path.stem.casefold(), []).append(path)

    selected = [
        sorted(
            paths,
            key=lambda p: (preference_rank.get(p.suffix.lower().lstrip("."), 99), p.name.casefold()),
        )[0]
        for paths in grouped.values()
    ]
    return sorted(selected, key=lambda p: p.name.casefold())


def select_from_latest_run(latest_path: Path | None = None) -> list[Path]:
    """collector가 남긴 latest.json에서 이번 실행 신규 다운로드 파일만 선택한다."""
    latest_path = latest_path or (RUNS_DIR / "latest.json")
    if not latest_path.exists():
        log.warning("Latest collection run file not found: %s", latest_path)
        return []

    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    files: list[Path] = []
    for item in payload.get("downloads", []):
        rel = item.get("file", "")
        if not rel:
            continue
        path = (ROOT / rel).resolve()
        if path.exists():
            files.append(path)
        else:
            log.warning("File listed in latest.json is missing on disk: %s", rel)
    return files


def select_input_files(source: str, format_preference: list[str]) -> list[Path]:
    """source가 'latest'면 최근 수집분, 아니면 디렉터리 경로로 해석한다."""
    if source.strip().lower() == "latest":
        return select_from_latest_run()

    input_dir = Path(source)
    if not input_dir.is_absolute():
        input_dir = ROOT / input_dir
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input transcript directory not found: {input_dir}")
    return choose_transcript_files(input_dir, format_preference)
