import time
from pathlib import Path


def read_log_with_retry(log_dir: Path, timeout: float = 2.0, min_len: int = 1) -> str:
    log_file = Path(log_dir) / "deckard.log"
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        if log_file.exists():
            try:
                last = log_file.read_text()
            except Exception:
                last = ""
            if len(last) >= min_len:
                return last
        time.sleep(0.05)
    return last
