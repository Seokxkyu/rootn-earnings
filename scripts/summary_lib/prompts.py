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
- 문장은 완결된 서술체로 쓴다(개조식 단어 나열 금지). 섹션별 형식은 다음을 따른다: '핵심 실적 vs 컨센서스'·'특이사항 & 핵심 KPI'는 수치 bullet, '경영진 핵심 메시지'·'서프라이즈 포인트'는 완결 문장으로 된 bullet, '가이던스'·'Q&A 답변'·'핵심 리스크'는 서술 문단.
- 분량은 Telegram 단일 메시지에 들어가도록 공백 포함 3,500자 이내로 쓴다(권장 3,200자). 넘칠 것 같으면 덜 중요한 세부부터 덜어내되 핵심 투자 근거는 유지한다.
- 같은 숫자를 여러 섹션에서 반복하지 않는다. 개별 KPI 수치는 '특이사항 & 핵심 KPI' 섹션에서만 나열하고, 경영진 메시지·서프라이즈에서는 흐름과 해석 위주로 쓴다.
- 문단은 짧게 끊는다. 섹션 제목과 Q&A 질문 제목만 <b>...</b>로 감싼다(그 외 HTML 태그·Markdown table 금지). 예: <b>📊 핵심 실적 vs 컨센서스</b>
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
핵심은 '기존 대비 무엇이 바뀌었나'다. 신규 제시·상향·하향·범위 조정된 항목을 위주로 쓰고, 변경 없이 재확인된 항목은 한 문장으로 묶어 압축한다. 모든 세부 수치를 나열하지 말고 투자 판단을 바꾸는 변경에 집중한다.
각 변경의 성격을 규정한다: 상향 / 하향 / 재확인 / 범위 축소 / 범위 확대 / 철회 / 정성적 변경.
전체 3~4문장 이내로 압축한다.

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
FINAL_SUMMARY_MAX_OUTPUT_TOKENS = 3200
REQUEST_PAUSE_SEC = 1.0
FILE_FORMAT_PREFERENCE = ["docx", "pdf"]
