"""v2 요약 프롬프트 테스트 — 지정한 transcript를 v2로 요약해 개인 chat에만 보낸다.

운영 경로(run_summary_pipeline)·manifest·전송 마커는 건드리지 않는다.

Usage:
  python scripts/test_prompt_v2.py "transcripts/.../Netflix Inc._Earnings Call_2026-10-20_English.docx"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from summary_lib import prompts  # noqa: E402
from summary_lib.config import ROOT, GrokSettings, TelegramSettings, load_env_file  # noqa: E402
from summary_lib.facts import apply_range_guidance, build_facts, consensus_hint_lines, normalize_terms, tidy_numbers  # noqa: E402
from summary_lib.grok_client import call_grok  # noqa: E402
from summary_lib.metadata import extract_metadata_block, extract_session, title_label  # noqa: E402
from summary_lib.polish import polish_summary  # noqa: E402
from summary_lib.telegram_client import build_telegram_messages, send_messages  # noqa: E402
from summary_lib.transcript_io import load_transcript_text  # noqa: E402

PERSONAL_CHAT = "7798477187"  # 테스트는 개인 chat으로만 (단체방 금지 규칙)


def main() -> int:
    load_env_file()
    path = Path(sys.argv[1]).resolve()
    text = load_transcript_text(path)
    try:
        display = path.relative_to(ROOT)
    except ValueError:
        display = path
    metadata = extract_metadata_block(display, text)
    facts = build_facts(metadata)

    prompt = prompts.FINAL_USER_PROMPT_TEMPLATE_V3 if "--v3" in sys.argv else prompts.FINAL_USER_PROMPT_TEMPLATE_V2
    prompt = prompt.replace("{{TICKER}}", title_label(text, path.stem))
    prompt = prompt.replace("{{SESSION}}", extract_session(text))
    prompt = prompt.replace("{{FACTS}}", "\n".join(facts) if facts else "(없음)")
    hints = consensus_hint_lines(metadata)
    prompt = prompt.replace("{{NEXT_CONSENSUS}}", "\n".join(hints) if hints else "(없음)")
    prompt = prompt.replace("{{METADATA}}", metadata)
    prompt = prompt.replace("{{TRANSCRIPT}}", text)

    summary = call_grok(
        GrokSettings.from_env(),
        system_prompt=prompts.FINAL_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_output_tokens=prompts.FINAL_SUMMARY_MAX_OUTPUT_TOKENS,
    )
    draft = apply_range_guidance(tidy_numbers(summary), metadata)
    summary = normalize_terms(polish_summary(GrokSettings.from_env(), draft))
    print(summary)
    if "--diff" in sys.argv:
        import difflib
        print("\n=== 교정 전후 바뀐 줄 ===")
        for d in difflib.unified_diff(draft.split("\n"), summary.split("\n"), lineterm="", n=0):
            if d.startswith(("-", "+")) and not d.startswith(("---", "+++")):
                print(d[:200])
    print(f"\n--- {len(summary)}자 ---")

    msgs = build_telegram_messages([{"file_name": path.name, "summary": summary}])
    target = TelegramSettings(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=PERSONAL_CHAT)
    tag = "v3" if "--v3" in sys.argv else "v2"
    sent = send_messages(target, [f"🧪 [테스트 {tag}]\n" + msgs[0]] + msgs[1:])
    print(f"개인 chat 전송: {sent}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
