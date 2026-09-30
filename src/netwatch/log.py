import logging
import os
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    data_dir = os.environ.get("DATA_DIR", "").strip()
    if data_dir:
        path = Path(data_dir) / "netwatch.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format=_FORMAT, handlers=handlers, force=True)


def read_log_tail(path: Path, max_lines: int = 200) -> list[str]:
    if not path.is_file():
        return []
    data = path.read_bytes()[-64_000:]
    text = data.decode("utf-8", errors="replace")
    if data and not text.startswith("20") and b"\n" in data:
        text = text.split("\n", 1)[-1]
    return text.splitlines()[-max_lines:]
