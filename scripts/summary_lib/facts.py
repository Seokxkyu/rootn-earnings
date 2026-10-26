"""컨센서스 블록에서 '확정 수치'를 코드로 계산하고, 요약의 숫자 서식을 정리한다.

LLM에게 서프라이즈 %를 계산시키면 틀릴 수 있고, 원문 단위($12,874.18mm)를 그대로
옮겨 읽기 어렵다. 실적·컨센서스·가이던스 비교와 서식은 여기서 결정적으로 만든다.
"""

from __future__ import annotations

import re

CURRENCY_SYMBOL = {"USD": "$", "JPY": "¥", "EUR": "€", "KRW": "₩", "GBP": "£", "CNY": "¥", "TWD": "NT$"}

_NUM = r"-?\d[\d,]*(?:\.\d+)?"


def _symbol(metadata_block: str) -> str:
    m = re.search(r"Currency:\s*([A-Z]{3})", metadata_block)
    code = m.group(1) if m else "USD"
    return CURRENCY_SYMBOL.get(code, code + " ")


def _fmt(value: float, is_mm: bool, sym: str) -> str:
    if is_mm:
        if abs(value) >= 1000:
            return f"{sym}{value / 1000:,.2f}B"
        return f"{sym}{value:,.0f}M"
    return f"{sym}{value:,.2f}"


def _icon(pct: float) -> str:
    # ±0.5%: 대형사 매출·가이던스는 0.5%만 어긋나도 시장이 반응한다.
    # 색 이모지는 쓰지 않는다(한국은 빨강=상승이라 🔴/🟢가 오독된다). 방향 기호만.
    if pct >= 0.5:
        return "▲"
    if pct <= -0.5:
        return "▼"
    return "━"


def _label(raw: str) -> tuple[str, bool]:
    is_mm = "(mm)" in raw.lower()
    name = re.sub(r"\(mm\)", "", raw, flags=re.I).strip()
    low = name.lower()
    if low.startswith("revenue"):
        name = "매출"
    elif low.startswith("eps"):
        qual = name[3:].strip().strip("()").strip()  # 'EPS (GAAP)' / 'EPS GAAP' 모두 EPS(GAAP)
        name = "EPS" + (f"({qual})" if qual else "")
    return name, is_mm


def build_facts(metadata_block: str) -> list[str]:
    """컨센서스 행마다 '아이콘 지표 실적 (컨센 X, ±Y%)' 줄을 만든다.

    현재 분기는 첫 두 숫자(컨센서스, 실적). 헤더에 GUIDANCE가 있고 숫자가 4개
    이상이면 3·4번째를 다음 분기 컨센서스·회사 가이던스로 본다.
    """
    lines = metadata_block.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if "Consensus / Actual / Surprise Block" in l)
    except StopIteration:
        return []
    has_guidance = any("GUIDANCE" in l for l in lines[start:start + 3])
    # 헤더의 '-FQ3 2026- -FQ4 2026-'에서 가이던스 대상 분기 이름을 가져온다.
    periods = re.findall(r"-\s*(F?Q\d\s+\d{4}|FY\s*\d{4})\s*-", metadata_block)
    next_label = periods[1] if len(periods) >= 2 else "다음분기"
    sym = _symbol(metadata_block)
    out: list[str] = []
    guide: list[str] = []
    for raw in lines[start + 1:]:
        row = raw.lstrip("- ").strip()
        if not row or row.startswith(("CONSENSUS", "Currency")):
            continue
        m = re.match(rf"^(.*?)\s+({_NUM}(?:\s+{_NUM})*)\s*$", row)
        if not m:
            continue
        name, is_mm = _label(m.group(1))
        nums = [float(x.replace(",", "")) for x in m.group(2).split()]
        if len(nums) >= 2 and nums[0]:
            cons, act = nums[0], nums[1]
            pct = (act - cons) / abs(cons) * 100
            pct = 0.0 if abs(pct) < 0.05 else pct
            out.append(
                f"{_icon(pct)} {name} <b>{_fmt(act, is_mm, sym)}</b> "
                f"(컨센 {_fmt(cons, is_mm, sym)}, <b>{pct:+.1f}%</b>)"
            )
        # 서프라이즈 % 열은 회사에 따라 채워지거나 비어 있다(Micron 5.03 / Netflix 공란).
        # 위치로 가정하면 가이던스를 잘못 짚으므로, 3번째 값이 계산한 서프라이즈와
        # 같으면 그 열로 보고 건너뛴다.
        rest = nums[2:]
        if len(nums) >= 3 and nums[0] and abs(rest[0] - (nums[1] - nums[0]) / abs(nums[0]) * 100) < 0.2:
            rest = rest[1:]
        if has_guidance and len(rest) >= 2 and rest[0]:
            ncons, gd = rest[0], rest[1]
            gpct = (gd - ncons) / abs(ncons) * 100
            gpct = 0.0 if abs(gpct) < 0.05 else gpct
            guide.append(
                f"{_icon(gpct)} {next_label} {name} 가이던스 <b>{_fmt(gd, is_mm, sym)}</b> "
                f"(컨센 {_fmt(ncons, is_mm, sym)}, <b>{gpct:+.1f}%</b>)"
            )
    return out + guide


_MM_RE = re.compile(rf"(?:(?P<sym>[$¥€₩£])\s?)?(?P<num>{_NUM})\s?mm\b", re.I)


def tidy_numbers(text: str) -> str:
    """요약 본문의 '$12,874.18mm' 같은 표기를 '$12.87B'로 바꾼다."""
    def repl(m: re.Match) -> str:
        sym = m.group("sym") or ""
        v = float(m.group("num").replace(",", ""))
        return f"{sym}{v / 1000:,.2f}B" if abs(v) >= 1000 else f"{sym}{v:,.0f}M"

    return _MM_RE.sub(repl, text)


def next_quarter_consensus(metadata_block: str) -> dict[str, tuple[str, float, bool]]:
    """다음 분기 컨센서스 {지표명: (분기명, 값, mm단위여부)}.

    범위 가이던스($73~76B)는 CapIQ 표의 가이던스 열에 안 들어오므로, 회사가 말한
    범위와 비교할 기준으로 쓴다. 서프라이즈 열 유무를 값으로 판별한다(build_facts와 동일).
    """
    lines = metadata_block.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if "Consensus / Actual / Surprise Block" in l)
    except StopIteration:
        return {}
    periods = re.findall(r"-\s*(F?Q\d\s+\d{4}|FY\s*\d{4})\s*-", metadata_block)
    label = periods[1] if len(periods) >= 2 else "다음분기"
    out: dict[str, tuple[str, float, bool]] = {}
    for raw in lines[start + 1:]:
        row = raw.lstrip("- ").strip()
        if not row or row.startswith(("CONSENSUS", "Currency")):
            continue
        m = re.match(rf"^(.*?)\s+({_NUM}(?:\s+{_NUM})*)\s*$", row)
        if not m:
            continue
        name, is_mm = _label(m.group(1))
        nums = [float(x.replace(",", "")) for x in m.group(2).split()]
        rest = nums[2:]
        if len(nums) >= 3 and nums[0] and abs(rest[0] - (nums[1] - nums[0]) / abs(nums[0]) * 100) < 0.2:
            rest = rest[1:]
        if rest and rest[0]:
            out[name] = (label, rest[0], is_mm)
    return out


def consensus_hint_lines(metadata_block: str) -> list[str]:
    sym = _symbol(metadata_block)
    return [f"{lab} {name} 컨센 {_fmt(v, mm, sym)}"
            for name, (lab, v, mm) in next_quarter_consensus(metadata_block).items()]


_RANGE_LINE = re.compile(
    r"^.*?(?P<period>F?Q\d\s+\d{4}|FY\s*\d{4}|다음분기)\s+(?P<name>매출|EPS(?:\([^)]*\))?)\s+가이던스\s+"
    r"<b>(?P<rng>[^<]+)</b>.*$",
    re.M,
)
_RANGE_NUM = re.compile(
    r"(?P<s1>[$¥€₩£])?\s*(?P<a>\d[\d,]*(?:\.\d+)?)\s*(?P<u1>[BM])?\s*[~–\-]\s*"
    r"[$¥€₩£]?\s*(?P<b>\d[\d,]*(?:\.\d+)?)\s*(?P<u2>[BM])?"
)


def apply_range_guidance(summary: str, metadata_block: str) -> str:
    """LLM이 쓴 'FQ4 2026 매출 가이던스 <b>$73~76B</b>' 줄을 코드로 재계산한 줄로 바꾼다.

    중간값과 컨센서스 차이 %·방향 기호는 LLM 계산을 믿지 않고 여기서 결정한다.
    """
    cons = next_quarter_consensus(metadata_block)
    sym = _symbol(metadata_block)

    def repl(m: re.Match) -> str:
        name = m.group("name")
        key = next((k for k in cons if k == name or k.startswith(name)), None)
        rm = _RANGE_NUM.search(m.group("rng"))
        if not key or not rm:
            return m.group(0)
        label, cval, is_mm = cons[key]
        unit = rm.group("u2") or rm.group("u1") or ""
        a, b = float(rm.group("a").replace(",", "")), float(rm.group("b").replace(",", ""))
        scale = 1000.0 if unit == "B" else 1.0
        lo, hi = (a * scale, b * scale) if is_mm else (a, b)
        mid = (lo + hi) / 2
        pct = (mid - cval) / abs(cval) * 100
        pct = 0.0 if abs(pct) < 0.05 else pct
        return (f"{_icon(pct)} {m.group('period')} {key} 가이던스 <b>{m.group('rng').strip()}</b> "
                f"(중간값 {_fmt(mid, is_mm, sym)}, 컨센 {_fmt(cval, is_mm, sym)}, <b>{pct:+.1f}%</b>)")

    return _RANGE_LINE.sub(repl, summary)


# 표기 하드룰(사용자 지정 2026-10-23). 문맥과 무관하게 뜻이 같은 것만 기계 치환한다.
# 문맥에 따라 뜻이 갈리는 것(레버·제고 등)은 polish 교정 패스에서 처리한다.
_TERM_MAP = [
    # 단위 약어 / 스토리지 세그먼트 원어
    (r"엑사바이트", "EB"), (r"페타바이트", "PB"), (r"테라바이트", "TB"), (r"기가바이트", "GB"),
    (r"기가와트", "GW"), (r"메가와트", "MW"), (r"니어라인", "nearline"),
    # 굳은 우리말이 없는 일반 영어 수식어를 음차한 경우 → 원어 (사용자 지정)
    (r"핸드\s?브레디드", "hand-breaded"), (r"택스\s?에쿼티", "tax equity"),
    (r"블렌디드", "blended"),
    # 중국어식 한자어
    (r"(?<![가-힣])근기(?![가-힣])", "단기"), (r"(?<![가-힣])동비(?![가-힣])", "YoY"),
    (r"(?<![가-힣])환비(?![가-힣])", "QoQ"),
    # YoY / QoQ 통일
    (r"전년\s?동기\s?대비|전년동기비|전년\s?대비|전년비", "YoY"),
    (r"직전\s?분기\s?대비|전분기\s?대비|전분기비", "QoQ"),
    # '순차'는 sequential(QoQ) 뜻일 때만: '순차적으로 출시' 같은 일반 용법은 남긴다
    (r"순차(?=\s?(?:성장|증가|감소|개선|하락|상승|둔화|가속|기준|[+\-−]?\d))", "QoQ"),
    # 용어
    (r"\brun[\s-]?rate\b|런\s?레이트", "연환산"),
    (r"\boutlook\b|아웃룩", "전망"),
    # 일본·중국식 '比' → 대비, 연도 축약 '27 → 2027, 본문 Capex → capex(헤드라인 ◆ Capex 줄은 유지)
    (r"\s?比\s?", " 대비 "),
    (r"\b(Q[1-4]|H[12])\s?[’'‘](\d{2})(?![\d%])", r"\1 20\2"),   # Q3'22 → Q3 2022
    (r"\b(FY|CY)\s?[’'‘](\d{2})(?![\d%])", r"\1\2"),            # FY'27 → FY27
    (r"[’'‘](2\d|3\d)(?![\d%])", r"20\1"),
    (r"(?<!◆ )(?<![A-Za-z])Capex(?![A-Za-z])", "capex"),
    (r"내구성", "지속성"),
    (r"궤적", "추이"),
    # 분기·반기 글로벌 표기: 3분기→Q3, 3Q26→Q3 2026, 3Q→Q3, 상/하반기→H1/H2
    # '향후 3~4분기'·'최근 4분기'는 기간(분기 수)이라 라벨로 바꾸지 않는다
    (r"(?<!향후 )(?<!향후)(?<!앞으로 )(?<!최근 )(?<!지난 )(?<!과거 )(?<![\d.])([1-4])\s?~\s?([1-4])분기(?!\s?(?:연속|동안|간))", r"Q\1~Q\2"),
    (r"(?<!향후 )(?<!향후)(?<!앞으로 )(?<!최근 )(?<!지난 )(?<!과거 )(?<![\d.~])(?<!~ )([1-4])분기(?!\s?(?:연속|만에|째|동안|간|치|이상|이내|내리|가량))", r"Q\1"),
    (r"(?<![A-Za-z\d])([1-4])Q(\d{2})(?![\dA-Za-z])", r"Q\1 20\2"),
    (r"(?<![A-Za-z\d])([1-4])Q(?![\dA-Za-z])", r"Q\1"),
    (r"상반기", "H1"), (r"하반기", "H2"),
]

# '조'는 금액 뒤에 붙어도 '조달'·'조정'일 수 있어 공백 없이 붙고 한글이 이어지지 않을 때만 단위로 본다.
_MONEY_EOK = re.compile(
    r"(?:\$\s?(?P<a>\d[\d,]*(?:\.\d+)?)(?:\s?(?P<u1>억)|(?P<u1t>조)(?![가-힣]{2})))"
    r"|(?:(?P<b>\d[\d,]*(?:\.\d+)?)\s?(?P<u2>억|조)\s?달러)"
)
_PCT_POINT = re.compile(r"(?P<n>[+\-−]?\d+(?:\.\d+)?)\s?(?:%\s?p\b|%p|%\s?포인트|pp\b)")


def _exact(v: float, max_dec: int) -> str | None:
    """소수 max_dec 자리 안에서 값이 정확히 표현되면 문자열, 아니면 None."""
    for d in range(max_dec + 1):
        if abs(round(v, d) - v) < 1e-9:
            return f"{v:,.{d}f}"
    return None


def _money_repl(m: re.Match) -> str:
    """$10억 / 10억 달러 → $1B, $5억 → $500M, $10.25억 → $1,025M, $1.2조 → $1.2T.

    자릿수를 잃지 않도록 B·T는 소수 둘째 자리 안에서 정확할 때만 쓰고 아니면 M으로 쓴다."""
    raw = m.group("a") or m.group("b")
    unit = m.group("u1") or m.group("u1t") or m.group("u2")
    dollars = float(raw.replace(",", "")) * (1e8 if unit == "억" else 1e12)
    if dollars >= 1e12 and (t := _exact(dollars / 1e12, 2)):
        return f"${t}T"
    if dollars >= 1e9 and (b := _exact(dollars / 1e9, 2)):
        return f"${b}B"
    return f"${_exact(dollars / 1e6, 1) or f'{dollars / 1e6:,.1f}'}M"


# 치환으로 앞말이 모음 발음으로 끝나게 된 경우(달러·추이·베이시스포인트) 받침용 조사를 고친다.
_VOWEL_END = r"((?:\$[\d.,~]+[BMT]|\d+bp)(?:</b>)?|추이)"
_PARTICLE_FIX = [
    (_VOWEL_END + r"으로", r"\1로"),
    (_VOWEL_END + r"은(?![가-힣])", r"\1는"),
    (_VOWEL_END + r"을(?![가-힣])", r"\1를"),
    (_VOWEL_END + r"과(?![가-힣])", r"\1와"),
    (_VOWEL_END + r"이(?![가-힣])", r"\1가"),
    # '초반·중반·후반'은 받침(ㄴ)으로 끝난다: 자릿수로→초반으로 등
    (r"([초중후]반)로", r"\1으로"),
    (r"([초중후]반)가(?![가-힣])", r"\1이"),
    (r"([초중후]반)는(?![가-힣])", r"\1은"),
    (r"([초중후]반)를(?![가-힣])", r"\1을"),
    (r"([초중후]반)와(?![가-힣])", r"\1과"),
]


def _pct_point_repl(m: re.Match) -> str:
    """마진 변화 %p → bp (글로벌 표기): +1.2%p → +120bp."""
    n = m.group("n").replace("−", "-")
    bp = round(float(n) * 100)
    sign = "+" if n.startswith("+") else ""
    return f"{sign}{bp}bp"


# low/mid/high 범위 표기 → 국문 리서치 표준('한 자릿수 후반', '10%대 중반', '50%대 초중반').
# 사용자 지정 하드룰(2026-10-23): 십중후반·고한자릿수·mid-teens 같은 직역·축약 금지.
_POS = {"low": 0, "로우": 0, "저": 0, "낮은": 0,
        "mid": 1, "미드": 1, "중": 1, "중간": 1,
        "high": 2, "하이": 2, "고": 2, "높은": 2}
_POS_WORD = r"(?:low|mid|high|로우|미드|하이|낮은|중간|높은|저|중|고)"
_POS_RANGE = rf"(?P<p1>{_POS_WORD})(?:\s?[~·\-/]?\s?(?:to\s)?(?P<p2>{_POS_WORD}))?"


def _pos_label(m: re.Match) -> str:
    """('low','mid') → '초중반', ('high',) → '후반', ('low','high') → '' (구간 전체)."""
    a = _POS[m.group("p1").lower()]
    b = _POS[m.group("p2").lower()] if m.group("p2") else a
    lo, hi = sorted((a, b))
    if (lo, hi) == (0, 2):
        return ""
    names = "초중후"
    return (names[lo] + (names[hi] if hi != lo else "")) + "반"


_DIGIT_WORD = {"한": "한", "단일": "한", "single": "한", "두": "두", "double": "두", "세": "세", "triple": "세"}
_RANGE_RULES = [
    # 저~중한 자릿수, 중·고 한 자릿수, 낮은 두 자릿수, mid-single digit(s)
    (re.compile(rf"(?<![가-힣A-Za-z]){_POS_RANGE}[\s\-]?(?P<d>한|두|세|단일|single|double|triple)[\s\-]?(?:자릿수|digits?)%?"),
     lambda m: f"{_DIGIT_WORD[m.group('d').lower()]} 자릿수" + (f" {_pos_label(m)}" if _pos_label(m) else "")),
    # 중반 두 자릿수 → 두 자릿수 중반 (어순 통일)
    (re.compile(r"(?<![가-힣])(?P<pos>초반|중반|후반|초중반|중후반)\s(?P<d>한|두|세)\s?자릿수"),
     lambda m: f"{m.group('d')} 자릿수 {m.group('pos')}"),
    # mid-teens / 중고십대 / 십중후반 → 10%대 중반·중후반
    (re.compile(rf"(?<![가-힣A-Za-z]){_POS_RANGE}[\s\-]?(?:teens|십대)"),
     lambda m: "10%대" + (f" {_pos_label(m)}" if _pos_label(m) else "")),
    (re.compile(r"(?<![가-힣])십\s?(?P<pos>초|중|후|초중|중후)반"), lambda m: f"10%대 {m.group('pos')}반"),
    (re.compile(r"(?<![A-Za-z])teens\b"), lambda m: "10%대"),
    # mid-50%, low~mid-80%, high 20s% → 50%대 중반, 80%대 초중반, 20%대 후반
    (re.compile(rf"(?<![가-힣A-Za-z]){_POS_RANGE}[\s\-]?(?P<n>[1-9]0)(?:'?s)?\s?%대?"),
     lambda m: f"{m.group('n')}%대" + (f" {_pos_label(m)}" if _pos_label(m) else "")),
]


def normalize_terms(text: str) -> str:
    # 텔레그램은 HTML 모드라 Markdown이 날것으로 보인다: **굵게**→<b>, •/* 글머리→'-'
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?m)^(\s*)[•·*]\s+", r"\1- ", text)
    for pat, fn in _RANGE_RULES:
        text = pat.sub(fn, text)
    text = _MONEY_EOK.sub(_money_repl, text)
    text = _PCT_POINT.sub(_pct_point_repl, text)
    for pat, rep in _TERM_MAP:
        text = re.sub(pat, rep, text)
    # '연환산 매출 run-rate' → '연환산 매출 연환산' 중복 제거
    text = re.sub(r"(연환산\s?\S{0,6}\s)연환산\s?", r"\1", text)
    for pat, rep in _PARTICLE_FIX:
        text = re.sub(pat, rep, text)
    return text
