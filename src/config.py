import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / ".env", override=False)

MODE = os.environ.get("MY_AGENT_MODE", "local")
if MODE not in {"local", "demo"}:
    raise RuntimeError("MY_AGENT_MODE must be local or demo")

IS_DEMO = MODE == "demo"
DEMO_FILES_DIR = PROJECT_DIR / "demo_files"
LOCAL_MEMORY_DB = PROJECT_DIR / "data" / "memory.db"
LOCAL_CHECKPOINT_DB = Path("agent_checkpoints.db")
LOCAL_APP_DB = PROJECT_DIR / "data" / "local_sessions.db"


def get_demo_data_dir():
    configured = Path(os.environ.get("MY_AGENT_DEMO_DATA_DIR", ""))
    if not configured.is_absolute():
        raise RuntimeError("MY_AGENT_DEMO_DATA_DIR must be an absolute path")

    directory = configured.resolve()
    protected = (PROJECT_DIR / "data").resolve()
    if (
        directory in {PROJECT_DIR, Path.cwd().resolve()}
        or directory.is_relative_to(protected)
        or protected.is_relative_to(directory)
        or directory.is_relative_to(DEMO_FILES_DIR.resolve())
        or directory.is_relative_to((PROJECT_DIR / "frontend").resolve())
    ):
        raise RuntimeError("Demo data directory must be separate from local data and demo files")

    for name in ("memory.db", "agent_checkpoints.db", "app.db"):
        for suffix in ("", "-wal", "-shm", "-journal"):
            path = directory / (name + suffix)
            try:
                info = path.lstat()
            except FileNotFoundError:
                # Other SQLite workers may remove WAL/SHM/journal files during
                # startup. Inspect one metadata snapshot, not exists/is_file/stat.
                continue
            if path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError("Demo database paths must be regular, unlinked files")

    directory.mkdir(parents=True, exist_ok=True)
    if not os.access(directory, os.W_OK):
        raise RuntimeError("Demo data directory must be writable")
    return directory


if IS_DEMO:
    PUBLIC_ORIGIN = os.environ.get("MY_AGENT_PUBLIC_ORIGIN") or os.environ.get(
        "RENDER_EXTERNAL_URL", ""
    )
    parsed_origin = urlsplit(PUBLIC_ORIGIN)
    if (
        parsed_origin.scheme != "https"
        or not parsed_origin.hostname
        or PUBLIC_ORIGIN != f"https://{parsed_origin.hostname}"
    ):
        raise RuntimeError("MY_AGENT_PUBLIC_ORIGIN must be an HTTPS origin without a path or port")
    DATA_DIR = get_demo_data_dir()
    MEMORY_DB = DATA_DIR / "memory.db"
    CHECKPOINT_DB = DATA_DIR / "agent_checkpoints.db"
    APP_DB = DATA_DIR / "app.db"
else:
    PUBLIC_ORIGIN = None
    MEMORY_DB = LOCAL_MEMORY_DB
    CHECKPOINT_DB = LOCAL_CHECKPOINT_DB
    APP_DB = LOCAL_APP_DB


def debug_print(*values):
    """Keep diagnostic content out of default application logs."""
    import logging
    logger = logging.getLogger("my_agent")
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(" ".join(str(value) for value in values))
