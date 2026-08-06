"""Earnings Q&A 봇 (@RootN_QA_bot).

텔레그램 단체방에서 `/ask <질문>`을 받아, transcript 아카이브를 근거로 Grok이
답한다. long-polling(getUpdates) 데몬. web search 없음(docs/qa_bot_design.md).

흐름: /ask 감지 → 종목 인식(Grok) → 그 기업 transcript 검색 → Grok 답변 → 회신.

Usage:
  python scripts/qa_bot.py            # 데몬 (Ctrl-C 종료)
  python scripts/qa_bot.py --once "엔비디아 데이터센터 매출 가이던스"  # 1회 콘솔 테스트(전송 안 함)
"""

from __future__ import annotations

import html
import json
import logging
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from summary_lib.config import GrokSettings, LOG_DIR, load_env_file  # noqa: E402
from qa_lib import corpus, llm, retriever  # noqa: E402

log = logging.getLogger("qa_bot")

API = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 50


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "qa_bot.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _get_env(key: str) -> str:
    import os

    v = os.getenv(key, "").strip()
    if not v:
        raise RuntimeError(f"{key} 가 .env에 없습니다.")
    return v


def tg(token: str, method: str, **params) -> dict:
    data = urllib.parse.urlencode(params).encode()
    url = API.format(token=token, method=method)
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=POLL_TIMEOUT + 10) as r:
        return json.load(r)


def _is_table_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 3


def _split_row(line: str) -> list[str]:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return [re.sub(r"<br\s*/?>", "; ", c) for c in cells]


def _is_separator(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells if c != "")


def flatten_markdown_tables(text: str) -> str:
    """마크다운 표를 항목별 목록으로 변환.

    텔레그램은 표를 렌더하지 못해 파이프가 그대로 노출된다. 비교표는
    '행 이름'을 소제목으로 두고 '열 이름: 값' bullet으로 펴면 모바일에서도 읽힌다.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not _is_table_line(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        block = []
        while i < len(lines) and _is_table_line(lines[i]):
            block.append(_split_row(lines[i]))
            i += 1
        rows = [r for r in block if not _is_separator(r)]
        if len(rows) < 2:
            out.extend("| " + " | ".join(r) + " |" for r in rows)
            continue
        header, body = rows[0], rows[1:]
        for row in body:
            label = row[0] if row else ""
            if label:
                out.append(f"**{label}**")
            for col_name, value in zip(header[1:], row[1:]):
                if value:
                    out.append(f"- {col_name}: {value}")
            out.append("")
    return "\n".join(out)


def md_to_telegram_html(text: str) -> str:
    """Grok이 내는 마크다운을 텔레그램 HTML(parse_mode=HTML)로 변환.

    텔레그램은 ## 헤더·리스트 마크다운을 렌더하지 않으므로 굵게(<b>)와 순수 텍스트로
    정리한다. 먼저 HTML 특수문자를 이스케이프한 뒤 서식만 태그로 되살린다.
    """
    out_lines = []
    for line in flatten_markdown_tables(text).split("\n"):
        s = html.escape(line)
        # ### 헤더 → 굵게 (마커 제거)
        m = re.match(r"\s*#{1,6}\s+(.*)", s)
        if m:
            out_lines.append(f"<b>{m.group(1).strip()}</b>")
            continue
        # - / * 불릿 → • 로 정규화
        s = re.sub(r"^(\s*)[-*]\s+", r"\1• ", s)
        # **굵게** / __굵게__ → <b>
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
        # *기울임* → 텔레그램 <i> (단, 남은 단독 * 는 제거)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", s)
        # `코드` → <code>
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        out_lines.append(s)
    return "\n".join(out_lines)


def send(token: str, chat_id: str, text: str) -> None:
    body = md_to_telegram_html(text)
    # 텔레그램 4096자 제한 → 분할(태그 깨짐 방지 위해 넉넉히 3900).
    for i in range(0, len(body), 3900):
        chunk = body[i : i + 3900]
        try:
            tg(token, "sendMessage", chat_id=chat_id, text=chunk, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            log.error("HTML 전송 실패, 평문 재시도: %s", exc)
            try:
                tg(token, "sendMessage", chat_id=chat_id, text=re.sub(r"<[^>]+>", "", chunk))
            except Exception as exc2:  # noqa: BLE001
                log.error("평문 전송도 실패: %s", exc2)


def parse_ask(text: str) -> str | None:
    """/ask 또는 /ask@봇 뒤의 질문 텍스트. 명령이 아니면 None."""
    if not text:
        return None
    head, _, rest = text.strip().partition(" ")
    cmd = head.split("@")[0].lower()
    if cmd != "/ask":
        return None
    return rest.strip() or None


def handle_question(grok: GrokSettings, question: str) -> str:
    docs = corpus.load_docs()
    if not docs:
        return "아직 수집된 transcript가 없습니다."
    available = corpus.company_list(docs)
    # 인식은 manifest 전체(파일 없는 것 포함)로 한다 → '모르는 기업'과
    # '파일이 없는 기업'을 구분해 안내할 수 있다.
    picked_all = llm.resolve_companies(grok, question, corpus.all_companies())
    if not picked_all:
        return (
            "질문에서 대상 기업을 특정하지 못했습니다. "
            "회사명이나 티커를 넣어 다시 물어봐 주세요.\n"
            f"(현재 보유 기업 {len(available)}곳)"
        )
    picked = [c for c in picked_all if c in available]
    missing = [c for c in picked_all if c not in available]
    if not picked:
        return (
            f"🏢 {', '.join(picked_all)}\n\n"
            "해당 기업 transcript가 이 서버에 없습니다. "
            "(Mac 이전 전에 수집된 자료라 파일이 Windows PC에 있습니다)"
        )
    keywords, broad = llm.analyze_question(grok, question)
    contexts: list[tuple[str, str]] = []
    if broad:
        # 전체 훑기 질문(Q&A 전부 정리, 총평 등): 청크 검색으로는 누락이 생기므로
        # 기업당 최신 transcript 원문 전체를 투입한다. 총량은 상한으로 보호.
        from summary_lib.transcript_io import load_transcript_text

        FULL_CHAR_CAP = 150_000  # 요약 파이프라인이 9만자 1-pass를 검증했으므로 여유 상한
        used = 0
        for company in picked:
            target = corpus.docs_for_company(docs, company)
            if not target:
                continue
            d = target[0]  # 최신 발표분
            try:
                text = load_transcript_text(d.path)
            except Exception:  # noqa: BLE001
                continue
            budget = FULL_CHAR_CAP - used
            if budget <= 0:
                break
            contexts.append((d.label, text[:budget]))
            used += min(len(text), budget)
    if not contexts:
        # 핀포인트 질문(또는 broad 로드 실패): 하이브리드 청크 검색.
        per_k = 5 if len(picked) == 1 else 4
        for company in picked:
            target = corpus.docs_for_company(docs, company)
            contexts.extend(retriever.search(target, question, top_k=per_k, extra_terms=keywords))
    label = ", ".join(picked)
    answer = llm.answer_question(
        grok, question, label, contexts,
        max_output_tokens=2400 if broad else 1200,
    )
    srcs = ", ".join(sorted({lb for lb, _ in contexts}))
    note = f"\n※ {', '.join(missing)}는 transcript가 서버에 없어 제외했습니다." if missing else ""
    return f"🏢 {label}\n\n{answer}\n\n— 근거: {srcs}{note}"


def run_once(question: str) -> None:
    load_env_file()
    grok = GrokSettings.from_env()
    print(handle_question(grok, question))


def acquire_single_instance_lock():
    """데몬이 동시에 두 개 돌지 않도록 배타 잠금을 잡는다.

    같은 봇 토큰으로 폴러가 2개면 텔레그램 getUpdates가 409 Conflict를 내고
    메시지가 유실될 수 있다. 이미 실행 중이면 잠금 실패로 즉시 종료한다.
    """
    import fcntl

    lock_path = LOG_DIR / "qa_bot.lock"
    LOG_DIR.mkdir(exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("이미 다른 qa_bot 인스턴스가 실행 중입니다. 이 인스턴스는 종료합니다.")
        sys.exit(0)
    return fh  # 프로세스가 살아있는 동안 잠금 유지(GC 방지 위해 반환값 보관)


def run_daemon() -> None:
    load_env_file()
    setup_logging()
    _lock = acquire_single_instance_lock()  # noqa: F841 - 살아있는 동안 잠금 유지
    grok = GrokSettings.from_env()
    token = _get_env("QA_BOT_TOKEN")
    me = tg(token, "getMe").get("result", {})
    log.info("Q&A 봇 시작: @%s", me.get("username"))

    offset = 0
    while True:
        try:
            resp = tg(token, "getUpdates", offset=offset, timeout=POLL_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            log.warning("getUpdates 실패, 5초 후 재시도: %s", exc)
            time.sleep(5)
            continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            # 수신 전량을 원문으로 기록: "메시지가 왔는데 무시됐는지 / 아예 안 왔는지"를
            # 로그만으로 판정하기 위함. (진단용 수동 getUpdates는 메시지를 파괴하므로 금지)
            log.info("RAW update: %s", json.dumps(upd, ensure_ascii=False)[:800])
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat") or {}
            if msg.get("migrate_to_chat_id"):
                log.warning("★그룹이 supergroup으로 전환됨: %s → %s (.env chat_id 갱신 필요)",
                            chat.get("id"), msg["migrate_to_chat_id"])
            question = parse_ask(msg.get("text", ""))
            if not question:
                continue
            chat_id = str(chat.get("id"))
            log.info("질문 수신 (chat %s): %s", chat_id, question)
            try:
                reply = handle_question(grok, question)
            except Exception as exc:  # noqa: BLE001
                log.exception("답변 생성 실패")
                reply = f"답변 생성 중 오류가 발생했습니다: {exc}"
            send(token, chat_id, reply)
            log.info("답변 전송 완료 (chat %s)", chat_id)


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--once":
        run_once(" ".join(sys.argv[2:]))
        return 0
    run_daemon()
    return 0


if __name__ == "__main__":
    sys.exit(main())
