"""요약 프롬프트와 튜닝 파라미터.

요약 스타일을 바꾸려면 이 파일만 수정하면 된다.
telegram_summary.ipynb Cell 4(프롬프트 입력)와 동일한 내용이다.

영어/번역 규칙은 화이트리스트(닫힌 목록)가 아니라 '판정 테스트 + 카테고리'로
설계했다. 섹터마다 다른 용어를 목록으로 커버할 수 없기 때문에, 단어마다
"한국 애널리스트가 한국어로 말할 때 그 단어를 실제로 영어로 발음하는가"를
판정하게 하고, 기본값은 한국어로 둔다. LANGUAGE_RULE_EN / LANGUAGE_RULE_KO를
청크·최종 프롬프트에 동일하게 삽입한다.
"""

# 영어/번역 판정 규칙 (영문) — 청크·최종 SYSTEM 프롬프트에 공통 삽입
LANGUAGE_RULE_EN = """Language and terminology (apply to every term):
- Write natural Korean that reads like a Korean equity analyst's own note, not a translated transcript.
- Default to Korean. Keep a term in English ONLY if a Korean equity analyst would actually pronounce it in English while speaking Korean. When unsure, use Korean.
- This test, not a fixed list, decides each term. It scales across sectors: a semiconductor analyst says "HBM", a SaaS analyst says "ARR", a bank analyst says "NIM" in English, so those stay; but ordinary words with a natural Korean equivalent are translated even if the transcript used English.
- Keep in English: financial metric acronyms and established loanwords with no natural Korean equivalent (e.g. EPS, EBITDA, ROIC, FCF, RASM, CASM, capex, guidance, mix, and sector-standard acronyms).
- Translate to Korean (illustrative, not exhaustive — apply the same judgment to all analogous terms):
  - common nouns: cargo->화물, capacity->공급, volume->물량, inventory->재고, demand->수요
  - descriptive/metaphorical business English: headwind->역풍/부담 요인, tailwind->순풍, pricing power->가격 결정력, resilience->회복력, staffing->인력, footprint->사업 기반
  - quantity/degree words: double-digit->두 자릿수, single-digit->한 자릿수, non-fuel->비연료, implicit->내재적, modest->완만한, sticky->경직적, breakeven->손익분기
  - timing/trend phrases: close-in->임박 예약, booking curve->예약 추이, exit rate->분기말 수준, forward->향후
- The transcript is in English, so most sentences contain English words. Translate every such word by default; do NOT leave a raw English word (e.g. "non-fuel", "implicit") sitting in a Korean sentence, and do NOT transliterate it into Hangul (e.g. 헤드윈드, 카고, 볼륨, 더블디짓, 논퓨얼, 리질리언스, 스태핑). English stays ONLY for terms that pass the pronunciation test above."""

# 영어/번역 판정 규칙 (국문) — 최종 USER 프롬프트에 삽입
LANGUAGE_RULE_KO = """[언어·용어 규칙 — 모든 용어에 적용]
- 번역투 없이, 한국 애널리스트가 직접 쓴 코멘트처럼 자연스러운 한국어로 쓴다.
- 기본값은 한국어다. 영어를 그대로 두는 것은 "한국 애널리스트가 한국어로 말할 때 그 단어를 실제로 영어로 발음하는 경우"에만 허용한다. 애매하면 한국어를 쓴다.
- 고정 목록이 아니라 이 판정 기준으로 단어마다 결정한다. 섹터별로 알아서 확장된다: 반도체는 "HBM", SaaS는 "ARR", 은행은 "NIM"을 영어로 말하므로 유지하되, 자연스러운 한국어가 있는 일반 단어는 원문이 영어여도 한국어로 옮긴다.
- 영어 유지: 재무지표 약어와 자연스러운 한국어 대응어가 없는 표준 용어 (예: EPS, EBITDA, ROIC, FCF, RASM, CASM, capex, guidance, mix, 섹터 표준 약어).
- 한국어로 번역 (예시일 뿐, 유사 용어 전반에 같은 판단 적용):
  - 일반 명사: cargo→화물, capacity→공급, volume→물량, inventory→재고, demand→수요
  - 서술·비유 표현: headwind→역풍/부담 요인, tailwind→순풍, pricing power→가격 결정력, resilience→회복력, staffing→인력, footprint→사업 기반
  - 수량·정도 표현: double-digit→두 자릿수, single-digit→한 자릿수, non-fuel→비연료, implicit→내재적, modest→완만한, sticky→경직적, breakeven→손익분기
  - 시점·추세 표현: close-in→임박 예약, booking curve→예약 추이, exit rate→분기말 수준, forward→향후
- 원문이 영어이므로 대부분 문장에 영어 단어가 들어 있다. 기본적으로 모두 한국어로 옮긴다. 영어 단어를 한국어 문장에 그대로 두거나(예: "non-fuel", "implicit") 한글로 음차하지 않는다(예: 헤드윈드, 카고, 볼륨, 더블디짓, 논퓨얼, 리질리언스, 스태핑). 영어는 위 발음 테스트를 통과하는 용어만 남긴다."""

CHUNK_SYSTEM_PROMPT = """You are an equity research analyst extracting facts from one chunk of an earnings call transcript.

Use only the chunk and provided metadata.
Do not use external knowledge or fill gaps.

Extract only:
- Actual results and KPIs
- Consensus / actual / surprise comparisons when explicitly shown
- Guidance and changes in guidance or tone
- Important Q&A topics
- Risks, unresolved issues, and cases where management avoids quantification

Rules:
- Preserve numeric values, periods, currencies, and measurement units (e.g. $, %, bp, gallons). "Units" means measurement units, not source-language wording.
- Distinguish actuals, guidance, targets, and expectations.
- If information is unclear or missing, say so.
- Output concise Korean bullet points only.
- No investment recommendation.

{LANGUAGE_RULE_EN}"""

FINAL_SYSTEM_PROMPT = """You are an equity research analyst writing an earnings-call summary for other analysts.

Grounding (the core rule — never violate):
- Use ONLY the provided transcript and metadata. Do not use external knowledge, do not infer stock-price reactions, and do not invent missing numbers or facts. If something is unclear, conflicting, undisclosed, or only partially answered, say so.

Analytical discipline:
- Distinguish actuals, guidance, targets, and expectations; never call something a surprise without a valid comparison point.
- Preserve numeric values, periods, currencies, and measurement units exactly (e.g. $, %, bp). "Units" means measurement units, not source-language wording.
- Keep information density high: preserve the specific drivers, segment/region detail, and figures a professional analyst would want. Do not give an investment recommendation.

{LANGUAGE_RULE_EN}"""

FINAL_USER_PROMPT_TEMPLATE = """아래 earnings call transcript와 metadata를 바탕으로 실적발표 요약을 작성한다.

{LANGUAGE_RULE_KO}

[출력 형식]
- 문장은 완결된 서술체로 쓴다(개조식 단어 나열 금지). 섹션별 형식은 다음을 따른다: '핵심 실적 vs 컨센서스'·'특이사항 & 핵심 KPI'·'가이던스 및 변경사항'은 간결한 수치·개조식 bullet, '경영진 핵심 메시지'·'서프라이즈 포인트'는 완결 문장으로 된 bullet, 'Q&A 답변'·'핵심 리스크'는 서술 문단.
- 분량은 Telegram 단일 메시지에 들어가도록 공백 포함 3,500자 이내로 쓴다(권장 3,200자). 넘칠 것 같으면 덜 중요한 세부부터 덜어내되 핵심 투자 근거는 유지한다.
- 같은 숫자를 여러 섹션에서 반복하지 않는다. 개별 KPI 수치는 '특이사항 & 핵심 KPI' 섹션에서만 나열하고, 경영진 메시지·서프라이즈에서는 흐름과 해석 위주로 쓴다.
- 문단은 짧게 끊는다. 섹션 제목과 Q&A 질문 제목만 <b>...</b>로 감싼다(그 외 HTML 태그·Markdown table 금지). 예: <b>📊 핵심 실적 vs 컨센서스</b>
- 영어 직역 번역투를 금지한다. 한국 애널리스트가 실제로 쓰는 자연스러운 용어로 옮긴다. 예:
  · 'durability' 직역 "성장 내구성" 금지 → "성장 지속성/지속력"
  · 'structural tailwind' 직역 "구조적 순풍" 금지 → "구조적 성장 요인/우호적 업황"
  · 'surface' 직역 "판매 표면/거래 표면/초기 표면" 금지 → "채널/고객 접점"
  · 'lever' 직역 "본원 레버/핵심 레버" 금지 → "성장 동력/수익성 개선 수단"
  · "볼륨에 연동" 금지 → "물량(Q)에 연동"
  같은 원리로, 영어 단어를 낯설게 직역한 표현 대신 국문 리서치 관용 표현을 쓴다.
- 별도 서론 없이 아래 섹션 순서대로 바로 출력한다.

<b>{{TICKER}} | {{SESSION}}</b>

<b>📊 핵심 실적 vs 컨센서스</b>
컨센서스 비교가 가능한 핵심 실적만 아래 형식으로 작성:
- EPS: {{actual}} vs 컨센 {{consensus}} ({{beat/miss/flat}} {{차이}})
- 매출: {{actual}} vs 컨센 {{consensus}} ({{beat/miss/flat}} {{차이}})
- 영업이익: {{actual}} vs 컨센 {{consensus}} ({{beat/miss/flat}} {{차이}})
영업이익, EBITDA, margin 등은 actual과 consensus가 모두 있을 때만 같은 형식으로 추가한다.

규칙:
- Metadata에 있을 때만 consensus 사용
- Actual과 Consensus가 모두 있을 때만 beat/miss 판단
- YoY / QoQ는 transcript에 있을 때만 사용
- GAAP / Non-GAAP 구분
- 컨센서스 비교가 불가능한 사업부/볼륨/마진/가격/채널 내용은 이 섹션에 쓰지 말고 아래 '특이사항 & 핵심 KPI'에 쓴다
- 컨센서스가 없는 항목은 이 섹션에서 생략한다

<b>💬 경영진 핵심 메시지</b>
핵심 메시지를 3~4개 bullet로 정리한다. 각 bullet은 완결된 문장으로, 전체 실적 흐름, 강했던·약했던 사업부·지역·제품, 수요·가격·물량·믹스·마진, 다음 분기 또는 하반기 핵심 변수 중 중요한 것을 담는다. 개별 KPI 수치를 나열하지 말고 흐름과 해석 위주로 쓴다.

<b>⚡ 서프라이즈 포인트</b>
2~3개를 bullet로 정리한다. 각 bullet은 완결된 문장으로 왜 서프라이즈인지 드러나게 쓴다. 비교 기준이 없으면 surprise라고 쓰지 마라.

<b>🧾 특이사항 & 핵심 KPI</b>
중요 수치 3~5개를 bullet로 나열한다. 각 항목은 기간·단위를 함께 쓰고 완결된 구로 쓴다.

<b>🧭 가이던스 및 변경사항</b>
transcript에 실질적인 guidance·outlook·tone 변화가 있을 때만 출력하고, 없으면 생략한다.
핵심은 '기존 대비 무엇이 바뀌었나'다. 변경 항목당 bullet 1개, 3~4개 이내로 정리한다. 각 bullet은 '항목: 변경 내용 (성격)' 형태의 간결한 개조식으로 쓴다. 성격은 상향 / 하향 / 신규 제시 / 재확인 / 범위 축소 / 범위 확대 / 철회 / 정성적 변경 중 명시한다. 예: '3Q 매출 가이던스: $9.3~9.4B 신규 제시 (YoY +50~52%, 컨센 $9.02B 상회)'. 신규 제시·상향·하향·범위 조정된 항목을 위주로 쓰고, 변경 없이 재확인된 항목은 마지막 bullet 하나로 묶어 압축한다. 모든 세부 수치를 나열하지 말고 투자 판단을 바꾸는 변경에 집중한다.

<b>❓ Q&A 요약</b>
투자 중요도가 높은 질문을 최대 5개 선택하고, 각 문항은 질문·답변 핵심·투자 관점을 짧은 서술 문장으로 정리한다. 핵심 실적/KPI의 숫자를 반복하지 말고 새 투자 판단 정보를 우선한다(가이던스 달성 전제, 상·하방 요인, 경영진 확신도; 수요의 질·회복 시점·채널/지역/제품별 변화; 마진·비용·경쟁·규제 등 리스크와 실행 과제). 수치는 Q&A에서 새로 공개되거나 해석상 중요할 때만 포함한다.

<b>Q1. {{질문 주제}}</b>
- 질문: (한 문장)
- 답변 핵심: (서술 문장으로)
- 투자 관점: (서술 문장으로)

<b>⚠️ 핵심 리스크</b>
Transcript에서 확인되는 리스크 2~3개를 각각 한 문장으로 쓴다.

추가 규칙:
- percentage와 percentage point를 구분한다.
- 부정적 내용과 미해결 이슈를 누락하지 않는다.

[METADATA]
{{METADATA}}

[TRANSCRIPT]
{{TRANSCRIPT}}"""

# 공통 언어 규칙 블록을 각 프롬프트에 삽입 (모듈 로드 시 1회).
# {{TICKER}} 등 이중 중괄호 플레이스홀더는 건드리지 않는다.
CHUNK_SYSTEM_PROMPT = CHUNK_SYSTEM_PROMPT.replace("{LANGUAGE_RULE_EN}", LANGUAGE_RULE_EN)
FINAL_SYSTEM_PROMPT = FINAL_SYSTEM_PROMPT.replace("{LANGUAGE_RULE_EN}", LANGUAGE_RULE_EN)
FINAL_USER_PROMPT_TEMPLATE = FINAL_USER_PROMPT_TEMPLATE.replace("{LANGUAGE_RULE_KO}", LANGUAGE_RULE_KO)

# transcript가 이 길이 이하면 청크 요약 단계를 건너뛰고 원문을 최종 프롬프트에
# 직접 투입한다(1-pass). grok-4.5 컨텍스트가 충분하므로 정보 손실·번역투 전파·맥락
# 단절을 막기 위해 기본은 1-pass. 이 값을 넘는 초장문만 청크로 분할(multi-pass)한다.
CHUNK_CHAR_LIMIT = 100000
CHUNK_SUMMARY_MAX_OUTPUT_TOKENS = 800
# 서술체는 개조식보다 길어 2200 토큰에서 잘렸다. 3,200자 안팎(권장)을 온전히 담도록 상향.
FINAL_SUMMARY_MAX_OUTPUT_TOKENS = 5000
REQUEST_PAUSE_SEC = 1.0
FILE_FORMAT_PREFERENCE = ["docx", "pdf"]


# ── Analyst/Investor Day 전용 (2026-08-14) ──────────────────────────────
# 어닝콜과 달리 컨센서스 비교·분기 실적 프레임이 없다. 중장기 목표·전략·로드맵
# 중심으로 요약한다. 스타일 규칙(길이·bullet·번역투 금지·표 금지)은 어닝콜과 동일.

INVESTORDAY_SYSTEM_PROMPT = FINAL_SYSTEM_PROMPT.replace(
    "an earnings-call summary", "an analyst/investor day summary"
)

INVESTORDAY_USER_PROMPT_TEMPLATE = """아래 Analyst/Investor Day transcript와 metadata를 바탕으로 행사 요약을 작성한다.

{LANGUAGE_RULE_KO}

[출력 형식]
- 분량은 Telegram 단일 메시지에 들어가도록 공백 포함 3,500자 이내(권장 3,200자).
- '중장기 목표'·'제품·기술 로드맵'은 간결한 수치·개조식 bullet, '전략 방향'·'Q&A 핵심'은 완결 문장 bullet.
- 섹션 제목만 <b>...</b>로 감싼다. 그 외 HTML 태그·Markdown table 금지.
- 영어 직역 번역투 금지(성장 내구성→성장 지속성, 구조적 순풍→구조적 성장 요인, 레버→성장 동력 등). 국문 리서치 관용 표현을 쓴다.
- 중국어식 한자어 금지(예: 근기→단기적으로, 동비→YoY, 환비→QoQ).
- 표기 통일(글로벌 셀사이드 표기): 전년 대비→YoY, 전분기 대비→QoQ. 분기는 Q3 / Q3 2026, 반기는 H1·H2, 회계연도가 달력과 다른 회사는 FQ3 2026·FY27. 마진·비율 변화는 bp(+1.2%p→+120bp). 금액은 $1.2B·$350M·$1.2T(억·조 달러 금지). run-rate→연환산, outlook→전망, 궤적→추이. 범위 표기는 '한 자릿수 후반'·'두 자릿수 초반'·'10%대 중반'·'50%대 초중반'(고한자릿수·십중후반·mid-teens 금지).
- 억지 직역 금지: 업계에서 굳어진 우리말이 없는 개념은 글자 그대로 옮기지 말고 원어를 쓴다. 회사 고유 전략·제품 용어도 원어 유지(예: major breakthrough, personal superintelligence). 국내 업계·언론에서 한글 음차로 굳어진 신조어는 음차를 쓴다(예: 에이전틱 커머스, 피지컬 AI, 네오클라우드). 기준은 '한국 애널리스트가 실제로 쓰는 말인가' — 애매하면 원어.
- 같은 숫자를 여러 섹션에서 반복하지 않는다. 별도 서론 없이 아래 섹션 순서대로 출력한다.

<b>{{TICKER}} | Analyst/Investor Day</b>

<b>🎯 행사 핵심</b>
행사의 성격과 가장 중요한 메시지 2~3개를 완결 문장 bullet로. 무엇이 새로 공개됐고 왜 중요한지.

<b>📈 중장기 재무 목표</b>
제시된 재무 목표를 '항목: 목표치 (기간)' 개조식 bullet로. 매출·마진·EPS·FCF·CAGR 등. 기존 목표 대비 변경(상향/하향/신규)이 언급되면 명시. 목표가 없으면 이 섹션 생략.

<b>🧭 전략 방향</b>
사업 포트폴리오·투자 우선순위·자본배분 등 전략 메시지를 3~4개 완결 문장 bullet로.

<b>🛠 제품·기술 로드맵</b>
신제품·기술·출시 시점을 '제품/기술: 내용 (시점)' 개조식 bullet로. 없으면 생략.

<b>🌐 시장·수요 전망</b>
TAM·수요 전망·경쟁 구도 관련 언급을 2~3개 bullet로. 없으면 생략.

<b>❓ Q&A 핵심</b>
투자 판단에 중요한 질문 최대 4개. 각 문항은 질문 요지와 답변 핵심을 짧은 서술로. Q&A가 없으면 생략.

[METADATA]
{{METADATA}}

[TRANSCRIPT]
{{TRANSCRIPT}}
"""

INVESTORDAY_USER_PROMPT_TEMPLATE = INVESTORDAY_USER_PROMPT_TEMPLATE.replace(
    "{LANGUAGE_RULE_KO}", LANGUAGE_RULE_KO
)


# ── v2 (2026-10-23 테스트): 숫자 임팩트 강화 ─────────────────────────────
# 맨 위 한줄평 + 코드가 계산한 확정 수치 블록, 핵심 숫자 굵게, Q&A 3문항으로 압축.
FINAL_USER_PROMPT_TEMPLATE_V2 = """아래 earnings call transcript와 metadata를 바탕으로 실적발표 요약을 작성한다.

{LANGUAGE_RULE_KO}

[출력 형식 — 반드시 지킨다]
- 공백 포함 3,800자 이내. 숫자가 먼저 눈에 들어오게, 설명은 짧게.
- 섹션 제목과 핵심 숫자만 <b>...</b>로 감싼다. 핵심 숫자 = 각 bullet에서 가장 중요한 수치 1~2개(금액·성장률·bp·마진). 그 외 HTML·Markdown table 금지.
- 수치 규칙: 원문에 수치가 있으면 반드시 숫자로 쓴다. 수치 없이 '개선/양호/상회' 같은 말로 끝내지 않는다. 수치가 공개되지 않았으면 '(수치 미공개)'라고 쓴다. YoY·QoQ가 원문에 있으면 항상 병기한다.
- 금액은 $1.23B / $456M처럼 B·M 단위로 쓴다(mm 표기 금지).
- 영어 직역 번역투 금지(성장 내구성→성장 지속성, 구조적 순풍→구조적 성장 요인, 레버→성장 동력, 볼륨에 연동→물량(Q)에 연동).
- 한국어 문장 안에 영어 일반 단어를 그대로 남기지 않는다(예: monetization→수익화, ramp→증산, visibility→가시성). 영어는 EPS·capex·HBM처럼 업계가 영어로 부르는 약어·고유명사만 허용.
- 중국어식 한자어 금지(예: 근기→단기적으로, 동비→YoY, 환비→QoQ).
- 표기 통일(글로벌 셀사이드 표기): 전년 대비→YoY, 전분기 대비→QoQ. 분기는 Q3 / Q3 2026, 반기는 H1·H2, 회계연도가 달력과 다른 회사는 FQ3 2026·FY27. 마진·비율 변화는 bp(+1.2%p→+120bp). 금액은 $1.2B·$350M·$1.2T(억·조 달러 금지). run-rate→연환산, outlook→전망, 궤적→추이. 범위 표기는 '한 자릿수 후반'·'두 자릿수 초반'·'10%대 중반'·'50%대 초중반'(고한자릿수·십중후반·mid-teens 금지).
- 억지 직역 금지: 업계에서 굳어진 우리말이 없는 개념은 글자 그대로 옮기지 말고 원어를 쓴다. 회사 고유 전략·제품 용어도 원어 유지(예: major breakthrough, personal superintelligence). 국내 업계·언론에서 한글 음차로 굳어진 신조어는 음차를 쓴다(예: 에이전틱 커머스, 피지컬 AI, 네오클라우드). 기준은 '한국 애널리스트가 실제로 쓰는 말인가' — 애매하면 원어.
- 같은 숫자를 두 번 쓰지 않는다. [확정 수치]에 나온 지표(EPS·매출·가이던스)는 아래 섹션에서 다시 쓰지 않는다.
- 별도 서론 없이 아래 순서대로 출력한다.

<b>{{TICKER}} | {{SESSION}}</b>
<b>한줄평:</b> (판정 한 단어 — 서프라이즈 / 부합 / 쇼크 / 혼조 — 와 그 이유 한 문장. 확정 수치·가이던스·이익 흐름을 함께 본다. EPS·매출이 상회해도 영업이익·마진이 크게 악화했거나(일회성 비용 포함) 비용·capex 가이던스 상향으로 이익 전망이 나빠졌으면 '혼조'로 판정한다.)

(아래 [확정 수치] 줄을 한 글자도 바꾸지 말고 그대로 옮긴다. [확정 수치]가 비어 있으면 이 줄들은 생략한다.)
(이어서, transcript에서 아래 주제가 다뤄졌으면 금액 유무와 관계없이 반드시 같은 블록에 한 줄씩 추가한다. 전혀 언급이 없을 때만 생략.)
- 자본지출: '◆ Capex <b>금액 또는 방향</b> (기간, 기존 계획 대비 변화, 주요 용도)'. 금액이 없으면 '(금액 미공개)'를 붙이고 증액·감액·유지 방향을 굵게 쓴다. 예: '◆ Capex <b>FY27 기존 계획 대비 증액</b> (금액 미공개, 대부분 '28년 말 이후 가동 클린룸 건설)'
- 자금조달: '◆ 조달 <b>금액</b> (방식: 회사채·전환사채·유상증자·대출·신용한도 신규/증액, 용도)'. 실제로 자금을 끌어온(또는 끌어올 계획을 밝힌) 경우만 쓴다. 주식분할·신주 클래스 신설·자사주 매입·배당은 조달이 아니므로 쓰지 않는다.
- 범위·점 가이던스: 아래 [다음 분기 컨센서스]에 있는 지표에 대해 회사가 해당 분기 가이던스를 제시했고 [확정 수치]에 없으면, 정확히 '<분기> <지표> 가이던스 <b>범위</b>' 형식으로 한 줄 쓴다(예: 'FQ4 2026 매출 가이던스 <b>$73~76B</b>'). 중간값·컨센 비교·기호는 시스템이 붙이므로 쓰지 않는다.

<b>📈 핵심 KPI</b>
투자 판단에 중요한 지표 4~6개. 형식: '- 지표명: <b>수치</b> (YoY/QoQ, 비교 기준)'. 세그먼트·지역·제품·마진·현금흐름 중 서프라이즈가 큰 것 우선. EPS·매출 총액과 capex·조달은 위 블록에 있으므로 쓰지 않는다.

<b>🧭 가이던스</b>
위 블록에 없는 가이던스만(연간 목표·마진·세그먼트 등) '- 항목: <b>수치</b> (상향/하향/신규/재확인)' 개조식 3개 이내. 실질 변경이 없으면 '- 기존 가이던스 재확인' 한 줄.

<b>💬 경영진 핵심 메시지</b>
3개 bullet, 각 한 문장. 숫자를 반복하지 말고 해석과 다음 분기 변수 위주.

<b>❓ Q&A 핵심</b>
투자 판단에 중요한 질문 최대 5개(콜에 질문이 적으면 그만큼만). 각 문항 형식:
<b>Q1. {{주제}}</b>
- 질문: 애널리스트가 무엇을 확인하려 했는지 한 문장
- 답변: 경영진 답변 2~3문장. 제시한 숫자·조건·시점·전제를 빠짐없이 담고, 회피·유보했으면 그 사실도 쓴다
- 투자 관점: 이 답이 실적 추정·밸류에이션에 주는 의미 한 문장

<b>⚠️ 리스크</b>
2개, 각 한 문장.

[확정 수치 — 코드가 계산함. 그대로 사용]
{{FACTS}}

[다음 분기 컨센서스 — 가이던스 비교 기준]
{{NEXT_CONSENSUS}}

[METADATA]
{{METADATA}}

[TRANSCRIPT]
{{TRANSCRIPT}}
"""
FINAL_USER_PROMPT_TEMPLATE_V2 = FINAL_USER_PROMPT_TEMPLATE_V2.replace("{LANGUAGE_RULE_KO}", LANGUAGE_RULE_KO)


# ── v3 (2026-10-26 테스트): 업황 시그널 섹션 ─────────────────────────────
# v2 + 원가·인플레 / 판가 / 수요 / 공급 을 고정 이름표로 모은다.
# 언급이 없는 항목·섹션은 쓰지 않는다(억지 작성 금지가 사용자 요구).
_SIGNAL_SECTION = """<b>🔎 업황 시그널</b>
콜에서 경영진 또는 애널리스트가 아래 주제를 직접 언급한 경우에만 쓴다. 해당 항목만 한 줄씩, 순서 유지.
- 원가·인플레: 원자재·부품·에너지·임금·물류·관세 등 비용 변화와 마진 영향
- 판가: 가격 인상·인하, 평균판가(ASP), 계약 가격, 전가 여부·시점
- 수요: 주문·수주잔고·book-to-bill·리드타임·고객 재고·최종 수요 변화
- 공급: 자사·업계 생산능력·가동률·공급 부족/과잉·증설·감산
형식: '- 항목: ▲/▼/━ 내용' (항목명은 위 네 개 이름 그대로) — 기호는 경영진이 말한 직전 분기 대비 변화 방향(원가는 상승=▲). 숫자가 언급됐으면 반드시 쓰고(마진 영향은 bp), 없으면 '(수치 미공개)'.
엄격 규칙:
- transcript에 명시적 발언이 있는 항목만 쓴다. 발언이 없는 항목은 줄을 만들지 않는다. '견조한 흐름 지속' 같은 일반론, 실적 숫자로부터의 추론, 업계 상식으로 채우지 않는다.
- 네 항목 모두 언급이 없으면 섹션 제목까지 통째로 생략한다. 항목 수를 채우려고 쓰지 않는다.
- 각 줄은 한 문장, 핵심 수치 1~2개만(가격·지표를 나열하지 않는다. 예: 금속 5종 가격 나열 금지 → 주력 품목 1개).
- 수요·판가·원가 관련 숫자(최종시장·지역별 성장률, ASP, 원가 변화 등)는 이 섹션에 우선 배치하고, 아래 KPI·가이던스·Q&A에서 다시 쓰지 않는다.
- '(수치 미공개)'는 콜 전체에서 그 항목의 숫자가 전혀 언급되지 않았을 때만 쓴다.

"""

FINAL_USER_PROMPT_TEMPLATE_V3 = FINAL_USER_PROMPT_TEMPLATE_V2.replace(
    "<b>📈 핵심 KPI</b>", _SIGNAL_SECTION + "<b>📈 핵심 KPI</b>", 1
).replace(
    "3개 bullet, 각 한 문장. 숫자를 반복하지 말고 해석과 다음 분기 변수 위주.",
    "2개 bullet, 각 한 문장. 숫자를 반복하지 말고 해석과 다음 분기 변수 위주. 업황 시그널과 겹치는 내용은 쓰지 않는다.",
    1,
).replace(
    "EPS·매출 총액과 capex·조달은 위 블록에 있으므로 쓰지 않는다.",
    "EPS·매출 총액과 capex·조달은 위 블록에 있으므로 쓰지 않는다. 업황 시그널에 쓴 지표·숫자(최종시장 성장률·판가·원가 등)도 쓰지 않는다.",
    1,
)
assert FINAL_USER_PROMPT_TEMPLATE_V3 != FINAL_USER_PROMPT_TEMPLATE_V2
