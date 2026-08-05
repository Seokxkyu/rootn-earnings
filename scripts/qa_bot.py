"""Earnings Q&A 봇 (@RootN_QA_bot).

텔레그램 단체방에서 `/ask <질문>`을 받아, transcript 아카이브를 근거로 Grok이
답한다. long-polling(getUpdates) 데몬. web search 없음(docs/qa_bot_design.md).

흐름: /ask 감지 → 종목 인식(Grok) → 그 기업 transcript 검색 → Grok 답변 → 회신.

Usage:
  python scripts/qa_bot.py            # 데몬 (Ctrl-C 종료)
  python scripts/qa_bot.py --once "엔비디아 데이터센터 매출 가이던스"  # 1회 콘솔 테스트(전송 안 함)
"""

from __future__ import annotations

import json
import logging
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


def send(token: str, chat_id: str, text: str) -> None:
    # 텔레그램 4096자 제한 → 분할.
    for i in range(0, len(text), 3900):
        try:
            tg(token, "sendMessage", chat_id=chat_id, text=text[i : i + 3900])
        except Exception as exc:  # noqa: BLE001
            log.error("전송 실패: %s", exc)


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
    companies = corpus.company_list(docs)
    company = llm.resolve_company(grok, question, companies)
    if not company:
        return (
            "질문에서 대상 기업을 특정하지 못했습니다. "
            "회사명이나 티커를 넣어 다시 물어봐 주세요.\n"
            f"(현재 보유 기업 {len(companies)}곳)"
        )
    target = corpus.docs_for_company(docs, company)
    keywords = llm.extract_keywords(grok, question)
    contexts = retriever.search(target, question, top_k=5, extra_terms=keywords)
    answer = llm.answer_question(grok, question, company, contexts)
    srcs = ", ".join(sorted({label for label, _ in contexts}))
    return f"🏢 {company}\n\n{answer}\n\n— 근거: {srcs}"


def run_once(question: str) -> None:
    load_env_file()
    grok = GrokSettings.from_env()
    print(handle_question(grok, question))


def run_daemon() -> None:
    load_env_file()
    setup_logging()
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
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat") or {}
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
