"""Capital IQ transcript collector driven by the saved default page state.

This collector assumes the user has already configured the desired universe or
filters inside Capital IQ so that opening the transcript summary page shows only
the rows that should be collected.

Flow:
1. Reuse the persistent browser profile in `.browser_profile`.
2. Open the transcript summary page.
3. Re-authenticate only when the session has expired.
4. Read only the rows already visible on the default page.
5. Download WORD by default, with PDF fallback when WORD is unavailable.
6. Save each file under `transcripts/YYYY-MM-DD/` using the collection date.
7. Record each collected file in `transcripts/manifest.csv` for deduping.
8. Write per-run JSON and CSV outputs under `output/collection_runs/`.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Locator, Page, TimeoutError as PWTimeout, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / ".browser_profile"
CONFIG_PATH = ROOT / "config" / "collector_config.json"
TRANSCRIPTS_DIR = ROOT / "transcripts"
MANIFEST_PATH = TRANSCRIPTS_DIR / "manifest.csv"
LOG_DIR = ROOT / "logs"
RUNS_DIR = ROOT / "output" / "collection_runs"
MANIFEST_FIELDS = [
    "company",
    "event",
    "event_date",
    "format",
    "file",
    "size_bytes",
    "downloaded_at",
]

TRANSCRIPTS_URL = (
    "https://www.capitaliq.spglobal.com/web/client?auth=inherit#news/transcriptsSummary"
)

BUTTON_LABELS = {"PDF", "WORD", "MP3"}

# 세션 만료 시 사용자가 브라우저 창에서 직접 로그인(MFA 포함)을 완료할 때까지 대기하는 최대 시간.
MANUAL_LOGIN_TIMEOUT_SEC = 300

SEL = {
    "login_email": "input[type='email'], input[placeholder*='Email' i]",
    "login_next": "button:has-text('NEXT'), button:has-text('Next')",
    "login_password": "input[type='password']",
    "login_signin": "button:has-text('SIGN IN'), button:has-text('Sign In')",
    "mfa_input": "input[autocomplete='one-time-code'], input[name*='code' i], input[placeholder*='code' i]",
    "grid_row": "[role='row'], tr",
    "row_word_button": "[title*='WORD' i], [aria-label*='WORD' i], button:has-text('WORD'), a:has-text('WORD'), a.hui-download-btn-doc",
    "row_pdf_button": "[title*='PDF' i], [aria-label*='PDF' i], button:has-text('PDF'), a:has-text('PDF'), a.hui-download-btn-pdf",
}

log = logging.getLogger("capiq")


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_path_component(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "Unknown"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def normalize_token(value: str) -> str:
    return re.sub(r"[_\W]+", " ", (value or "").casefold(), flags=re.UNICODE).strip()


def normalize_event_date(value: str) -> str:
    cleaned = norm(value)
    if not cleaned:
        return ""
    try:
        return datetime.strptime(cleaned, "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return cleaned


def build_dedupe_key(company: str, event_date: str) -> str:
    canonical_company = normalize_token(company)
    canonical_date = normalize_event_date(event_date)
    return f"{canonical_company}|{canonical_date}"


def infer_format_from_path(path_str: str) -> str:
    lowered = (path_str or "").lower()
    if lowered.endswith(".docx") or lowered.endswith(".doc"):
        return "word"
    if lowered.endswith(".pdf"):
        return "pdf"
    return ""


def parse_manifest_rows() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []

    with open(MANIFEST_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        raw_rows = list(reader)

    rows: list[dict] = []
    for source in raw_rows:
        if not source or not any(norm(value) for value in source.values() if value):
            continue

        file_path = source.get("file", "")
        row = {
            "company": source.get("company", ""),
            "event": source.get("event", ""),
            "event_date": source.get("event_date", ""),
            "format": source.get("format", "") or infer_format_from_path(file_path),
            "file": file_path,
            "size_bytes": source.get("size_bytes", ""),
            "downloaded_at": source.get("downloaded_at", ""),
        }
        if not row["company"] or not row["event_date"]:
            continue

        row["company"] = norm(row["company"])
        row["event"] = norm(row["event"])
        row["event_date"] = normalize_event_date(row["event_date"])
        row["format"] = norm(row["format"]).lower()
        row["file"] = norm(row["file"])
        rows.append(row)

    return rows


def choose_storage_date(row: dict) -> str:
    downloaded_at = norm(row.get("downloaded_at", ""))
    if downloaded_at:
        try:
            return datetime.fromisoformat(downloaded_at).strftime("%Y-%m-%d")
        except ValueError:
            pass

    event_date = normalize_event_date(row.get("event_date", ""))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
        return event_date
    return datetime.now().strftime("%Y-%m-%d")


def migrate_storage_layout(rows: list[dict]) -> list[dict]:
    layout_changed = False
    visited_dirs: set[Path] = set()

    for row in rows:
        file_value = norm(row.get("file", ""))
        if not file_value:
            continue

        current_rel = Path(file_value)
        current_abs = ROOT / current_rel
        target_dir = TRANSCRIPTS_DIR / choose_storage_date(row)
        target_rel = target_dir.relative_to(ROOT) / current_rel.name
        target_abs = ROOT / target_rel

        if current_rel == target_rel:
            continue

        row["file"] = str(target_rel)
        layout_changed = True
        if not current_abs.exists():
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        if not target_abs.exists():
            current_abs.replace(target_abs)
        visited_dirs.add(current_abs.parent)

    for directory in sorted(visited_dirs, key=lambda path: len(path.parts), reverse=True):
        if directory == TRANSCRIPTS_DIR:
            continue
        try:
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            continue

    if layout_changed:
        write_manifest_rows(rows)
    return rows


def write_manifest_rows(rows: list[dict]) -> None:
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})


def normalize_manifest() -> list[dict]:
    rows = parse_manifest_rows()
    if not rows:
        return []

    rows = migrate_storage_layout(rows)

    deduped: dict[str, dict] = {}
    for row in rows:
        fmt = row.get("format", "")
        dedupe_key = build_dedupe_key(row["company"], row["event_date"])
        if dedupe_key in deduped:
            if fmt == "word" and deduped[dedupe_key].get("format") != "word":
                deduped[dedupe_key] = row
            continue
        deduped[dedupe_key] = row

    normalized_rows = list(deduped.values())
    write_manifest_rows(normalized_rows)
    return normalized_rows


def load_manifest_keys() -> set[str]:
    rows = normalize_manifest()
    return {
        build_dedupe_key(row["company"], row["event_date"])
        for row in rows
        if row.get("company") and row.get("event_date")
    }


def append_manifest(entry: dict) -> None:
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    write_header = not MANIFEST_PATH.exists()
    with open(MANIFEST_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({field: entry.get(field, "") for field in MANIFEST_FIELDS})


def get_run_output_paths(run_started_at: datetime) -> tuple[Path, Path, Path]:
    run_date = run_started_at.strftime("%Y-%m-%d")
    run_stamp = run_started_at.strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_date
    run_dir.mkdir(parents=True, exist_ok=True)
    return (
        run_dir / f"collection_run_{run_stamp}.json",
        run_dir / f"collection_run_{run_stamp}.csv",
        RUNS_DIR / "latest.json",
    )


def write_run_outputs(downloaded: list[dict], run_started_at: datetime, run_finished_at: datetime) -> None:
    json_path, csv_path, latest_path = get_run_output_paths(run_started_at)
    payload = {
        "run_started_at": run_started_at.isoformat(),
        "run_finished_at": run_finished_at.isoformat(),
        "download_count": len(downloaded),
        "downloads": downloaded,
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in downloaded:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})


def is_logged_in(page: Page) -> bool:
    url = page.url.lower()
    if "login" in url or "web/client" not in url:
        return False

    try:
        for sel in (SEL["login_email"], SEL["login_password"], SEL["mfa_input"]):
            control = page.locator(sel).first
            if control.count() and control.is_visible():
                return False
        return "transcriptssummary" in page.url.lower()
    except Exception:  # noqa: BLE001
        return False


def wait_visible(page: Page, selector: str, timeout: int = 8000):
    """요소가 보일 때까지 대기해 Locator를 반환한다. navigation 중이어도 견딘다.

    안 나타나거나 페이지 전환 중이면 None을 반환한다(count()처럼 즉시 크래시하지 않음).
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        return locator
    except Exception:  # noqa: BLE001 - 요소 부재/전환 중은 None 처리
        return None


def safe_click(page: Page, selector: str, timeout: int = 5000) -> None:
    """클릭 시도. 요소가 없거나 전환 중이면 조용히 넘어간다."""
    try:
        page.locator(selector).first.click(timeout=timeout)
    except Exception:  # noqa: BLE001
        pass


def try_login(page: Page) -> bool:
    """세션 만료 시 재로그인.

    이메일/비밀번호는 환경변수(CAPIQ_EMAIL / CAPIQ_PASSWORD)가 있으면 자동 입력해
    수동 단계를 줄인다. 다만 MFA 4자리 코드는 자동 조회하지 않는다.
    (인증 메일이 Gmail이 아니므로 IMAP 자동조회를 제거했다.)

    로그인 완료(Transcripts 화면 진입)를 최대 MANUAL_LOGIN_TIMEOUT_SEC 동안 폴링한다.
    사용자는 열린 Playwright 브라우저 창에서 필요한 단계(비어 있으면 이메일/비밀번호,
    그리고 항상 MFA 코드)를 직접 입력하면 된다. 무인 실행이라 아무도 입력하지 않으면
    타임아웃되어 False를 반환하고, 상위 파이프라인이 세션 만료 알림을 보낸다.
    """
    email_addr = os.environ.get("CAPIQ_EMAIL")
    password = os.environ.get("CAPIQ_PASSWORD")

    # 로그인 페이지로의 리다이렉트(navigation)가 끝날 때까지 대기한다.
    # 안정화 전에 Locator.count()를 부르면 "Execution context was destroyed"로 크래시한다.
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2000)

    email_input = wait_visible(page, SEL["login_email"])
    if email_addr and email_input is not None:
        email_input.fill(email_addr)
        safe_click(page, SEL["login_next"])
        page.wait_for_timeout(3000)

    password_input = wait_visible(page, SEL["login_password"])
    if password and password_input is not None:
        password_input.fill(password)
        safe_click(page, SEL["login_signin"])
        page.wait_for_timeout(5000)

    if is_logged_in(page):
        return True

    log.warning(
        "세션이 만료되었습니다. 열린 브라우저 창에서 로그인을 완료하세요 "
        "(필요 시 이메일/비밀번호 입력 후, MFA 4자리 코드 직접 입력). 최대 %d초 대기합니다.",
        MANUAL_LOGIN_TIMEOUT_SEC,
    )
    deadline = time.time() + MANUAL_LOGIN_TIMEOUT_SEC
    stable_checks = 0
    while time.time() < deadline and stable_checks < 2:
        time.sleep(5)
        stable_checks = stable_checks + 1 if is_logged_in(page) else 0
    return stable_checks >= 2


def extract_company_and_event(row: Locator, row_text: str) -> tuple[str, str]:
    try:
        link_texts = [
            norm(text)
            for text in row.locator("a").all_inner_texts()
            if norm(text) and norm(text) not in BUTTON_LABELS
        ]
    except Exception:  # noqa: BLE001
        link_texts = []

    company = link_texts[0] if link_texts else ""
    event = ""
    for text in link_texts[1:]:
        if "earnings call" in text.lower():
            event = text
            break

    if not event:
        match = re.search(
            r"([A-Za-z0-9][^|]*?Earnings Call(?:,\s*[A-Za-z]{3}\s+\d{1,2},\s*\d{4})?)",
            row_text,
            re.I,
        )
        event = norm(match.group(1)) if match else "Earnings Call"

    if not company:
        company = norm(event.split(",")[0]) if "," in event else "Unknown Company"

    return company, event


def extract_event_date(event: str) -> str:
    match = re.search(r"([A-Za-z]{3}\s+\d{1,2},\s*\d{4})$", event)
    return norm(match.group(1)) if match else ""


DOC_CLASS = "hui-download-btn-doc"   # WORD
PDF_CLASS = "hui-download-btn-pdf"   # PDF

# 아시아(일본 등) transcript는 한 행에 언어 세트가 여러 개 있고, 실제 제공되는 세트만
# display:table-row로 보인다(숨겨진 세트를 클릭하면 다운로드가 안 돼 타임아웃). 라벨로
# 언어를 구분하고, 영어(ENG-TRANSL/ENG) 우선, 없으면 일본어(JPN, 번역 필요)로 고른다.
LANG_SETS = [
    ("ENG-TRANSL", "english", False),
    ("ENG", "english", False),
    ("JPN", "japanese", True),
]


def _visible_format_button(scope: Locator, preferred_format: str) -> tuple[Locator | None, str]:
    """scope 안에서 선호 포맷의 '보이는' 다운로드 버튼을 고른다."""
    normalized = (preferred_format or "word").strip().lower()
    order = ["word", "pdf"] if normalized == "word" else ["pdf", "word"]
    class_of = {"word": DOC_CLASS, "pdf": PDF_CLASS}
    for fmt in order:
        btn = scope.locator(f"a.{class_of[fmt]}").first
        try:
            if btn.count() and btn.is_visible():
                return btn, fmt
        except Exception:  # noqa: BLE001
            continue
    return None, ""


def pick_download_button(
    row: Locator, preferred_format: str
) -> tuple[Locator | None, str, str, bool]:
    """(버튼, 포맷, 언어, 번역필요)를 반환한다.

    - 언어 세트(SCRIPTS Asia: ENG-TRANSL / JPN 등)가 있으면 영어 우선으로 고른다.
    - 언어 세트가 없으면(미국 등 영어 원문) 기존처럼 보이는 첫 버튼을 고른다.
    """
    # 언어 세트가 있는 행(일본 등): 보이는 세트 div에서 우선순위대로 선택.
    for label, lang, needs_trans in LANG_SETS:
        set_div = row.locator(
            f"xpath=.//div[contains(@style,'table-row')][contains(., '{label}')]"
        )
        if not set_div.count():
            continue
        btn, fmt = _visible_format_button(set_div.first, preferred_format)
        if btn is not None:
            return btn, fmt, lang, needs_trans

    # 언어 세트가 없는 행(영어 원문): 행 전체에서 보이는 첫 버튼.
    btn, fmt = _visible_format_button(row, preferred_format)
    if btn is not None:
        return btn, fmt, "english", False

    return None, "", "english", False


def scan_rows(
    page: Page,
    seen: set[str],
    max_downloads: int,
    preferred_format: str,
) -> tuple[list[dict], int]:
    """(다운로드 목록, 그리드 행 수)를 반환한다.

    행 수가 0이면 로그인은 됐어도 그리드가 렌더되지 않은 것으로, 상위에서
    '로드 실패 의심'으로 처리한다(정상적인 '신규 없음'은 항상 여러 행이 보인다).
    """
    downloaded: list[dict] = []
    seen_this_run: set[str] = set()

    # 그리드(SPA)가 실제로 렌더될 때까지 대기한다. 스케줄러 콜드 스타트(밤새 유휴 후
    # 실행)에서는 SPA 렌더가 느려, 고정 대기만으로는 빈 셸을 스캔해 "0행"으로
    # 오판(신규를 놓침)할 수 있다. 그리드 행이 나타나면 로드가 끝난 것으로 본다.
    try:
        page.wait_for_selector(SEL["grid_row"], timeout=45000)
    except PWTimeout:
        log.info("그리드 행이 45초 내 나타나지 않음 (빈 그리드/신규 0으로 간주).")
    page.wait_for_timeout(3000)

    rows = page.locator(SEL["grid_row"])
    row_count = rows.count()
    log.info("Visible grid rows: %d", row_count)

    for index in range(row_count):
        if len(downloaded) >= max_downloads:
            log.info("Reached max_per_run limit: %d", max_downloads)
            break

        row = rows.nth(index)
        try:
            row_text = norm(row.inner_text(timeout=2000))
        except PWTimeout:
            continue

        if "earnings call" not in row_text.lower():
            continue

        company, event = extract_company_and_event(row, row_text)
        event_date = extract_event_date(event)
        download_btn, actual_format, language, needs_translation = pick_download_button(
            row, preferred_format
        )
        if not download_btn:
            log.warning("No downloadable transcript button found for row: %s", row_text)
            continue

        if not event_date:
            log.warning("Skipping row because its event date could not be parsed: %s", row_text)
            continue

        key = build_dedupe_key(company, event_date)
        if key in seen or key in seen_this_run:
            continue

        downloaded_at = datetime.now()
        dest_dir = TRANSCRIPTS_DIR / downloaded_at.strftime("%Y-%m-%d")
        dest_dir.mkdir(parents=True, exist_ok=True)

        try:
            with page.expect_download(timeout=60000) as dl_info:
                download_btn.click()
            download = dl_info.value
            suffix = ".docx" if actual_format == "word" else ".pdf"
            fallback_name = safe_path_component(f"{company}_{event}") + suffix
            filename = download.suggested_filename or fallback_name
            dest = dest_dir / filename
            download.save_as(dest)
        except PWTimeout:
            log.error("Download timed out for key: %s", key)
            continue

        size = dest.stat().st_size
        log.info(
            "Download completed (%s/%s%s): %s (%d bytes)",
            actual_format.upper(), language,
            ", 번역필요" if needs_translation else "",
            dest.name, size,
        )
        entry = {
            "company": company,
            "event": event,
            "event_date": normalize_event_date(event_date),
            "format": actual_format,
            "language": language,
            "needs_translation": needs_translation,
            "file": str(dest.relative_to(ROOT)),
            "size_bytes": size,
            "downloaded_at": downloaded_at.isoformat(),
        }
        append_manifest(entry)
        seen.add(key)
        seen_this_run.add(key)
        downloaded.append(entry)
        time.sleep(3)

    return downloaded, row_count


def main() -> int:
    LOG_DIR.mkdir(exist_ok=True)
    run_started_at = datetime.now()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / f"capiq_{datetime.now():%Y%m%d}.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    setup_mode = "--setup" in sys.argv
    dump_mode = "--dump" in sys.argv

    cfg = load_config()
    seen = load_manifest_keys()
    preferred_format = str(cfg.get("download_format", "word")).strip().lower()
    if preferred_format not in {"word", "pdf"}:
        raise ValueError("download_format must be either 'word' or 'pdf'.")

    max_downloads = int(cfg.get("max_per_run", 4))
    if max_downloads < 1:
        raise ValueError("max_per_run must be at least 1.")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            accept_downloads=True,
            viewport={"width": 1600, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(TRANSCRIPTS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)

        if setup_mode:
            print("Sign in to Capital IQ in the opened browser window. Waiting up to 10 minutes...")
            deadline = time.time() + 600
            stable_checks = 0
            while time.time() < deadline and stable_checks < 2:
                time.sleep(5)
                stable_checks = stable_checks + 1 if is_logged_in(page) else 0
            if stable_checks >= 2:
                page.wait_for_timeout(10000)
                snapshot = LOG_DIR / f"grid_dump_{datetime.now():%Y%m%d_%H%M%S}.html"
                snapshot.write_text(page.content(), encoding="utf-8")
                print(f"Setup complete. HTML snapshot saved to {snapshot}")
                ctx.close()
                return 0
            print("Login was not confirmed within the time limit.")
            ctx.close()
            return 1

        if not is_logged_in(page):
            log.info("Session expired; attempting automatic re-authentication")
            if not try_login(page):
                ctx.close()
                return 2
            page.goto(TRANSCRIPTS_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(8000)

        if dump_mode:
            snapshot = LOG_DIR / f"grid_dump_{datetime.now():%Y%m%d_%H%M%S}.html"
            snapshot.write_text(page.content(), encoding="utf-8")
            print(f"HTML snapshot saved to {snapshot}")
            ctx.close()
            return 0

        downloaded, row_count = scan_rows(
            page=page,
            seen=seen,
            max_downloads=max_downloads,
            preferred_format=preferred_format,
        )
        run_finished_at = datetime.now()
        write_run_outputs(downloaded, run_started_at, run_finished_at)

        log.info("Completed run with %d new downloads", len(downloaded))
        for item in downloaded:
            log.info("  - %s | %s | %s", item["format"], item["event"], item["file"])

        # 로그인은 됐는데 그리드 행이 0개면 페이지 로드 실패 의심(신규를 놓쳤을 수 있음).
        # 정상 페이지는 신규가 없어도 최근 이벤트 행이 항상 보인다.
        if row_count == 0 and not downloaded:
            log.warning("그리드 행이 0개 - 페이지 로드 실패 의심(신규 누락 가능). 알림 대상.")
            ctx.close()
            return 3

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
