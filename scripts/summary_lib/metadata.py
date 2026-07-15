from __future__ import annotations

import re
from pathlib import Path

from .transcript_io import norm

# CapIQ transcript 상단에 나오는 거래소 접두 티커.
# 미국은 알파벳(NasdaqGS:PEP), 일본/아시아는 숫자(TSE:4443)이므로 티커는 영숫자 시작을 허용한다.
EXCHANGE_TICKER_RE = re.compile(
    r"\b(?:NYSE|NYSEAM|NasdaqGS|NasdaqGM|NasdaqCM|Nasdaq|AMEX|OTCPK|OTCQX|OTCQB|"
    r"TSX|TSXV|LSE|AIM|ENXTPA|ENXTAM|ENXTBR|XTRA|SWX|SEHK|TSE|TSEC|KOSE|KOSDAQ|ASX|BSE|NSEI)"
    r"\s*:\s*([A-Z0-9][A-Z0-9.]{0,7})\b"
)
FALLBACK_TICKER_RE = re.compile(r"\b[A-Z][A-Za-z]+[: ]([A-Z]{1,6})\b")


def extract_ticker(text: str) -> str:
    head = text[:4000]
    match = EXCHANGE_TICKER_RE.search(head) or EXCHANGE_TICKER_RE.search(text)
    if match:
        return match.group(1)
    match = FALLBACK_TICKER_RE.search(text)
    return match.group(1) if match else "확인 불가"


def extract_quarter(text: str) -> str:
    match = re.search(r"\b(FQ\d\s+\d{4}|Q\d\s+\d{4})\b", text)
    return match.group(1) if match else "확인 불가"


def extract_session(text: str) -> str:
    for line in text.splitlines()[:20]:
        lowered = line.lower()
        if "earnings call" in lowered or "conference call" in lowered:
            return norm(line)
    return "확인 불가"


def extract_metadata_block(display_path: Path, transcript_text: str) -> str:
    lines = [norm(line) for line in transcript_text.splitlines() if norm(line)]
    top_lines = lines[:25]
    consensus_lines: list[str] = []
    capture = False
    for line in top_lines:
        if "CONSENSUS" in line.upper() and "ACTUAL" in line.upper():
            capture = True
            consensus_lines.append(line)
            continue
        if capture:
            if len(consensus_lines) >= 8:
                break
            consensus_lines.append(line)
            if line.lower().startswith("currency:"):
                break

    metadata_lines = [
        f"File Name: {display_path.name}",
        f"Source Path: {display_path}",
        f"Ticker: {extract_ticker(transcript_text)}",
        f"Quarter: {extract_quarter(transcript_text)}",
        f"Session: {extract_session(transcript_text)}",
        "Top Header Lines:",
    ]
    metadata_lines.extend(f"- {line}" for line in top_lines[:10])
    if consensus_lines:
        metadata_lines.append("Consensus / Actual / Surprise Block:")
        metadata_lines.extend(f"- {line}" for line in consensus_lines)
    else:
        metadata_lines.append("Consensus / Actual / Surprise Block: 확인 불가")
    return "\n".join(metadata_lines)
