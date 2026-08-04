"""수집된 transcript를 구글드라이브 종목별 폴더로 업로드.

로컬 transcripts/YYYY-MM-DD/ 아래의 transcript 파일을
'Investment Research/Transcripts/<회사명>/' 로 올린다. 회사명은 파일명의
"_Earnings Call" 앞부분을 그대로 쓰므로 별도 매핑 테이블이 필요 없고,
rclone copy가 원격 폴더를 자동 생성한다.

- 업로드 원장: output/gdrive_uploaded.txt (한 줄 = 업로드 완료한 상대경로).
  원장에 있는 파일은 건너뛰므로 매 회차 돌려도 신규분만 올라간다.
- manifest.csv는 Transcripts 루트에 매 실행 갱신 업로드한다.
- 개별 파일 실패는 기록만 하고 계속 진행. 실패가 있으면 exit 1
  (원장에 안 적히므로 다음 회차에 자동 재시도된다).

Usage:
  python scripts/upload_transcripts_gdrive.py
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT_DIR = ROOT / "transcripts"
LEDGER = ROOT / "output" / "gdrive_uploaded.txt"
LOG_DIR = ROOT / "logs"

RCLONE = "/opt/homebrew/bin/rclone"
REMOTE_BASE = "gdrive:Investment Research/Transcripts"
TRANSCRIPT_SUFFIXES = {".docx", ".pdf", ".doc"}
PER_FILE_TIMEOUT_SEC = 180

log = logging.getLogger("gdrive_upload")


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / f"gdrive_{datetime.now():%Y%m%d}.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def company_folder(file_name: str) -> str:
    """파일명에서 회사명 추출: '<회사명>_Earnings Call_...' 형식."""
    name = Path(file_name).stem
    company = name.split("_Earnings Call")[0].strip()
    return company or "_unclassified"


def load_ledger() -> set[str]:
    if not LEDGER.exists():
        return set()
    return {line.strip() for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_ledger(rel_path: str) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(rel_path + "\n")


def rclone_copy(src: Path, dest_dir: str) -> bool:
    result = subprocess.run(
        [RCLONE, "copy", str(src), dest_dir, "--retries", "2"],
        capture_output=True,
        text=True,
        timeout=PER_FILE_TIMEOUT_SEC,
    )
    if result.returncode != 0:
        log.error("업로드 실패: %s → %s\n%s", src.name, dest_dir, (result.stderr or "").strip())
        return False
    return True


def main() -> int:
    setup_logging()

    if not TRANSCRIPT_DIR.exists():
        log.info("transcripts 폴더 없음. 종료.")
        return 0

    uploaded = load_ledger()
    targets: list[Path] = [
        p
        for date_dir in sorted(TRANSCRIPT_DIR.iterdir())
        if date_dir.is_dir()
        for p in sorted(date_dir.iterdir())
        if p.suffix.lower() in TRANSCRIPT_SUFFIXES
    ]
    pending = [p for p in targets if str(p.relative_to(ROOT)) not in uploaded]

    ok_count = 0
    fail_count = 0
    for path in pending:
        rel = str(path.relative_to(ROOT))
        dest = f"{REMOTE_BASE}/{company_folder(path.name)}"
        try:
            if rclone_copy(path, dest):
                append_ledger(rel)
                ok_count += 1
                log.info("업로드 완료: %s → %s/", path.name, dest)
            else:
                fail_count += 1
        except subprocess.TimeoutExpired:
            log.error("업로드 타임아웃: %s", rel)
            fail_count += 1

    # manifest는 매 실행 갱신 (rclone copy는 변경 없으면 스킵)
    manifest = TRANSCRIPT_DIR / "manifest.csv"
    if manifest.exists():
        try:
            rclone_copy(manifest, REMOTE_BASE)
        except subprocess.TimeoutExpired:
            log.error("manifest 업로드 타임아웃")

    log.info("Drive 업로드 결과: 신규 %d건 성공, %d건 실패 (대기 %d건 중)", ok_count, fail_count, len(pending))
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
