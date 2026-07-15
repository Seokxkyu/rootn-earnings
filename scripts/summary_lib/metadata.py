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


# 회사명 라인은 대개 법인 접미사로 끝난다. 헤더 상단에서 이 패턴 라인을 회사명으로 본다.
COMPANY_SUFFIX_RE = re.compile(
    r".*\b(?:Inc|Incorporated|Corporation|Corp|Co|Company|Ltd|Limited|Group|"
    r"Holdings|Holding|PLC|LLC|LP|AG|SE|Trust|Bancorp|Partners|Technologies|Systems)\.?$",
    re.I,
)


def extract_company(text: str) -> str:
    """헤더에서 회사명을 추출한다.

    회사명은 transcript 상단에 있으나 티커와의 순서가 파일마다 다르다
    ('Sansan, Inc. TSE:4443' vs 티커가 먼저 오고 회사명이 뒷줄). 그래서 위치가 아니라
    '법인 접미사(Inc/Corp/Co/Ltd/Group 등)로 끝나는 첫 헤더 라인'을 회사명으로 쓰고,
    같은 줄에 붙은 거래소 티커는 제거한다. 못 찾으면 빈 문자열(제목은 티커만 사용).
    """
    for raw in [norm(line) for line in text[:4000].splitlines()][:12]:
        if not raw or raw.upper() in {"CONSENSUS", "TRANSCRIPTS", "ACTUAL", "SURPRISE"}:
            continue
        line = EXCHANGE_TICKER_RE.sub("", raw).strip().rstrip(",").strip()
        if line and COMPANY_SUFFIX_RE.match(line):
            return line
    return ""


def title_label(text: str, filename_stem: str = "") -> str:
    """요약 제목용 식별자 '회사명 (티커)'.

    회사명은 파일명(회사명_Earnings Call_날짜_언어)에서 우선 취한다 — 우리가 저장할 때
    만든 형식이라 헤더 파싱보다 안정적이다(헤더는 회사명이 여러 줄로 쪼개지기도 한다).
    파일명이 없으면 헤더에서 추출한다. 티커는 항상 헤더에서 뽑는다.
    """
    ticker = extract_ticker(text)
    company = norm(filename_stem.split("_")[0]) if filename_stem else ""
    if not company:
        company = extract_company(text)
    if company and ticker not in ("", "확인 불가"):
        return f"{company} ({ticker})"
    return company or (ticker if ticker != "확인 불가" else "확인 불가")


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
