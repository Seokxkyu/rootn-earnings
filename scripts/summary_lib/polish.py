"""요약문 교정 패스 — 직역투·중국어식 한자어·영어 잔존 표현만 다듬는다.

생성 단계 프롬프트에 금지 예시를 아무리 넣어도 새 직역 표현이 계속 나온다.
요약을 다 쓴 뒤 '국문 리서치 편집자' 역할로 표현만 고친다. 숫자·서식이 바뀌면
위험하므로 (1) 코드가 만든 헤드라인 줄은 가려서 보내고 (2) 교정 전후 숫자가
하나라도 다르면 교정본을 버리고 원본을 쓴다.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from .config import GrokSettings
from .grok_client import call_grok

log = logging.getLogger("summary")

POLISH_SYSTEM = """너는 한국 증권사 리서치센터의 편집자다. 애널리스트가 쓴 실적 요약의 '표현'만 다듬는다.

고칠 것:
1. 영어 직역투 → 한국 애널리스트가 실제로 쓰는 표현
   예: 성장 내구성→성장 지속성, 구조적 순풍→구조적 성장 요인,
   기울기를 가르다→속도를 좌우하다, 단위경제→건당·이용자당 수익성, 레버/핵심 레버→문맥에 맞게 '성장 동력'(매출을 키우는 요인) 또는 '개선 수단'(비용·마진을 조정하는 수단),
   판매 표면→판매 채널, 가시성이 낮다→예측이 어렵다(문맥상 자연스러울 때), 프레임→기준·틀,
   볼륨에 연동→물량에 연동, 비피크→유휴 시간대, ~하는 데 있어서→~에서, ~에 의해 견인되다→~가 이끌다,
   컴퓨트→연산 자원(또는 컴퓨팅), 서빙/서빙비→추론 서비스/추론 비용, 규모화→확대, 스케일→규모·확대,
   서피스(surface)→문맥에 맞게 '앱'·'광고 지면'·'접점'(판매 채널로 옮기지 말 것), 티어→등급, 코어→핵심
2. 중국어식 한자어 → 우리말 표현
   예: 근기→단기적으로, 동비→YoY, 환비→QoQ, 견인력→성장 동력, 제고하다→높이다
3. 한국어 문장 속 영어 일반 단어 → 우리말 (EPS·capex·HBM·GPU·AI·ARPU처럼 업계가 영어로 쓰는 약어·고유명사·제품명은 그대로 둔다)
   예: monetization→수익화, ramp→증산, visibility→가시성, upside→상승 여지, headwind→부담 요인
4. 어색한 명사 나열·번역체 피동문 → 자연스러운 문장
5. 억지 직역 → 원어로 되돌리기. 업계에서 굳어진 우리말이 없는 개념을 글자 그대로 옮겨 뜻이 흐려진 경우,
   번역하지 말고 원어(영어)를 그대로 쓴다. 회사 고유의 전략·제품·조직 용어도 원어를 유지한다.
   예: 대형 돌파→major breakthrough, 개인 슈퍼인텔리전스→personal superintelligence,
   제품-시장 적합성→PMF(product-market fit)
6. 국내 업계·언론에서 한글 음차로 굳어진 신조어는 음차를 쓴다(억지 번역도, 영어 원문도 아닌 통용 표기).
   예: 에이전트 상거래/agentic commerce→에이전틱 커머스, physical AI→피지컬 AI, neocloud→네오클라우드
   단, 우리말이 따로 있는 일반 단어의 음차(헤드윈드·볼륨·리질리언스 등)는 여전히 우리말로 고친다.
   영어 수식어·분사를 소리 나는 대로 옮긴 음차(핸드브레디드·블렌디드·펀디드 등)는 쓰지 않는다: 우리말이 있으면 우리말
   (블렌디드 ASP→평균 ASP, 펀디드 계정→입금 계좌, 에쿼티 조달·희석→지분 조달·희석, 깊이 임베디드된 관계→밀착된 관계),
   없으면 원어(hand-breaded chicken). 단 반도체 세그먼트명 '임베디드'처럼 굳은 업계 용어는 유지.
7. 단위는 약어로 쓴다(엑사바이트→EB, 테라바이트→TB, 기가와트→GW). 스토리지·반도체 세그먼트 용어는 원어
   (nearline, HAMR, ePMR, HBM, NAND).
8. 표기는 글로벌 셀사이드 방식으로 통일한다: 전년 대비→YoY, 전분기 대비→QoQ, 분기 Q3·반기 H1/H2,
   마진·비율 변화 bp, 금액 $B·$M. 이 변환은 코드가 따로 하므로, 너는 이미 그렇게 쓰인 표기를 되돌리지만 않으면 된다.

판단 기준: '한국 증권사 애널리스트가 실제로 쓰는 말인가'. 쓰는 우리말이 있으면 우리말,
국내에서 음차로 통용되면 음차, 업계가 영어로 부르거나 옮기면 어색해지면 원어. 애매하면 원어를 택한다.

절대 바꾸지 말 것:
- 모든 숫자·%·통화기호·단위·날짜·분기 표기(FQ4 2026 등)·티커·회사명·제품명
- <b>...</b> 태그 위치와 개수(Markdown ** 사용 금지), 줄 앞 글머리 기호('-' 등), 줄 구성, 섹션 제목, bullet 개수와 순서, '[[KEEP_n]]' 자리표시자
- 내용(사실)은 더하거나 빼지 않는다. 표현만 바꾼다.

출력: 다듬은 전체 텍스트만. 설명·머리말 없이."""

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> Counter:
    return Counter(n.replace(",", "") for n in _NUM_RE.findall(text))


def _is_protected(line: str) -> bool:
    s = line.strip()
    return s.startswith(("▲", "▼", "━", "◆")) or " 가이던스 <b>" in s


def polish_summary(settings: GrokSettings, summary: str) -> str:
    """직역투를 다듬은 요약을 반환. 검증 실패·오류 시 원본을 그대로 반환한다."""
    lines = summary.split("\n")
    kept: dict[str, str] = {}
    masked = []
    for i, line in enumerate(lines):
        # 제목 줄과 코드가 만든 헤드라인 숫자 줄은 교정 대상에서 뺀다.
        if i == 0 or _is_protected(line):
            key = f"[[KEEP_{len(kept)}]]"
            kept[key] = line
            masked.append(key)
        else:
            masked.append(line)
    masked_text = "\n".join(masked)

    try:
        out = call_grok(
            settings,
            system_prompt=POLISH_SYSTEM,
            user_prompt=masked_text,
            max_output_tokens=5000,
        ).strip()
    except Exception as exc:  # noqa: BLE001 - 교정 실패가 전송을 막지 않도록
        log.warning("교정 패스 실패, 원본 사용: %s", exc)
        return summary

    if any(k not in out for k in kept):
        log.warning("교정 패스가 보호 줄을 훼손 — 원본 사용")
        return summary
    if _numbers(out) != _numbers(masked_text):
        log.warning("교정 패스가 숫자를 바꿈 — 원본 사용")
        return summary
    if [ln[:1] for ln in out.split("\n") if ln.strip()] != [ln[:1] for ln in masked_text.split("\n") if ln.strip()]:
        log.warning("교정 패스가 줄 구성·글머리 기호를 바꿈 — 원본 사용")
        return summary
    if "**" in out and "**" not in masked_text:
        log.warning("교정 패스가 Markdown을 넣음 — 원본 사용")
        return summary
    if out.count("<b>") != masked_text.count("<b>"):
        log.warning("교정 패스가 굵게 태그를 바꿈 — 원본 사용")
        return summary

    for k, v in kept.items():
        out = out.replace(k, v)
    return out
