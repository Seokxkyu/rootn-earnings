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
        name = "EPS" + (f"({name[3:].strip()})" if name[3:].strip() else "")
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


# 단위·세그먼트 용어 표기 통일(문맥 무관하게 뜻이 같아 기계 치환이 안전한 것만).
# 단위는 약어, 스토리지 세그먼트 용어는 원어 — 사용자 지정(2026-10-23).
_TERM_MAP = [
    (r"엑사바이트", "EB"),
    (r"페타바이트", "PB"),
    (r"테라바이트", "TB"),
    (r"기가바이트", "GB"),
    (r"니어라인", "nearline"),
]


def normalize_terms(text: str) -> str:
    for pat, rep in _TERM_MAP:
        text = re.sub(pat, rep, text)
    return text
