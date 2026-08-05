"""Q&A용 LLM 호출 (Grok). 종목 인식과 답변 생성 두 가지.

기존 summary_lib.grok_client / GrokSettings를 재사용한다. LLM 교체 시 이 파일만
바꾸면 되도록 봇·검색 로직과 분리한다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summary_lib.config import GrokSettings  # noqa: E402
from summary_lib.grok_client import call_grok  # noqa: E402

log = logging.getLogger("qa_bot")


RESOLVE_SYSTEM = (
    "너는 사용자 질문이 어느 상장 기업(들)에 관한 것인지 판별하는 분류기다. "
    "반드시 '보유 기업 목록'에 있는 회사명 중에서만 고른다. 비교 질문이면 여러 개를 "
    "골라도 된다(최대 4개, 쉼표로 구분해 한 줄로). "
    "질문이 목록의 어느 기업과도 무관하거나 특정할 수 없으면 정확히 NONE 이라고만 답한다. "
    "설명 없이 회사명(들) 한 줄 또는 NONE 만 출력한다."
)


def resolve_companies(settings: GrokSettings, question: str, companies: list[str]) -> list[str]:
    """질문에서 대상 기업(들)을 고른다. 목록에 없으면 빈 리스트. 최대 4개.

    먼저 코드로 명백한 매칭(회사명 토큰이 질문에 그대로 등장)을 전부 수집하고,
    하나도 없을 때만 LLM에 목록을 후보로 주고 고르게 한다(닫힌 목록이라 환각 차단).
    """
    q = question.strip()
    if not companies:
        return []
    # 1) 코드 즉시 매칭: 질문에 이름이 그대로 들어있는 회사를 전부 수집.
    lowered = q.lower()
    matched: list[str] = []
    for name in companies:
        core = re.split(r",|\bInc\b|\bCorp|\bCorporation|\bCo\b|\bLtd|\bplc|\bHoldings|\bGroup",
                        name)[0].strip().lower()
        if core and len(core) >= 3 and core in lowered:
            matched.append(name)

    # 2) LLM 판별을 항상 병행해 합친다. 코드 매칭만 믿고 조기 반환하면
    #    티커·통칭으로 지칭된 나머지 기업(예: 'AMD랑 arm 비교'의 AMD)을 놓친다.
    listing = "\n".join(f"- {c}" for c in companies)
    prompt = f"[보유 기업 목록]\n{listing}\n\n[사용자 질문]\n{q}\n\n[정답: 회사명(들) 또는 NONE]"
    try:
        answer = call_grok(
            settings,
            system_prompt=RESOLVE_SYSTEM,
            user_prompt=prompt,
            max_output_tokens=120,
        ).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("종목 인식 LLM 실패: %s", exc)
        return matched[:4]
    llm_picked: list[str] = []
    if answer and answer.upper() != "NONE":
        # 회사명에 쉼표가 포함되므로(예: 'Advanced Micro Devices, Inc.') 쉼표 분리는
        # 불가. 대신 목록의 각 회사명이 LLM 답변 문자열에 등장하는지로 매칭한다.
        low = answer.lower()
        llm_picked = [c for c in companies if c.lower() in low]
        if not llm_picked:
            log.warning("종목 인식 결과가 목록과 불일치: %r", answer)
    # 코드 매칭 + LLM 판별 합집합 (순서 유지, 중복 제거).
    combined = matched + [c for c in llm_picked if c not in matched]
    return combined[:4]


KEYWORD_SYSTEM = (
    "너는 검색어 추출기다. 사용자 질문을 영어 어닝콜 transcript에서 찾기 위한 "
    "핵심 검색어를 뽑는다. 한국어 질문이면 영어로 번역한 핵심 명사·고유명사를 낸다. "
    "제품명·세그먼트·재무용어 위주로 3~8개, 쉼표로만 구분해 한 줄로 출력한다. "
    "예: 'iPhone, Services, revenue, gross margin, China'."
)


def extract_keywords(settings: GrokSettings, question: str) -> list[str]:
    """질문에서 영어 transcript 검색용 키워드를 뽑는다(한→영 포함). 실패 시 빈 리스트."""
    try:
        raw = call_grok(
            settings,
            system_prompt=KEYWORD_SYSTEM,
            user_prompt=question.strip(),
            max_output_tokens=60,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("키워드 추출 실패: %s", exc)
        return []
    return [t.strip() for t in re.split(r"[,\n]", raw) if t.strip()]


ANSWER_SYSTEM = (
    "너는 어닝콜 transcript를 근거로 투자자 질문에 답하는 리서치 어시스턴트다. "
    "규칙:\n"
    "- 제공된 transcript 발췌(근거)에 있는 내용만으로 답한다. 추측·외부지식 금지.\n"
    "- 근거에 없으면 '제공된 transcript에서 확인되지 않습니다'라고 명시한다.\n"
    "- 숫자·발언을 인용할 때 어느 분기/발표일 자료인지 밝힌다.\n"
    "- 한국어로 간결하게. 핵심부터. 필요시 bullet.\n"
    "- 표(마크다운 테이블) 금지. 텔레그램에서 렌더되지 않는다. 여러 기업을 비교할 때는 "
    "항목을 소제목으로 두고 그 아래에 '회사명: 값' 형태 bullet으로 쓴다.\n"
    "- <br> 같은 HTML 태그를 쓰지 않는다. 줄바꿈은 실제 줄바꿈으로 한다."
)


def answer_question(
    settings: GrokSettings,
    question: str,
    company: str,
    contexts: list[tuple[str, str]],
) -> str:
    """근거(발췌) 기반 답변 생성. contexts = [(출처라벨, 본문청크), ...].

    company는 복수 기업이면 'A, B' 형태 문자열. 비교 질문도 같은 경로로 처리된다.
    """
    if not contexts:
        return f"{company} 관련 transcript는 있으나 질문과 맞는 근거를 찾지 못했습니다."
    joined = "\n\n".join(f"[근거 {i+1} · {label}]\n{body}" for i, (label, body) in enumerate(contexts))
    prompt = (
        f"[대상 기업]\n{company}\n\n"
        f"[transcript 발췌]\n{joined}\n\n"
        f"[질문]\n{question.strip()}\n\n"
        f"[답변]"
    )
    return call_grok(
        settings,
        system_prompt=ANSWER_SYSTEM,
        user_prompt=prompt,
        max_output_tokens=1200,
    ).strip()
