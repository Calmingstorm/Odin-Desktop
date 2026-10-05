from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(level: str = "INFO", log_dir: str | None = None) -> None:
    from ..runtime_paths import runtime_profile_paths

    log_path = Path(log_dir) if log_dir is not None else runtime_profile_paths().data_dir / "logs"
    if log_dir is None:
        from ..desktop.paths import private_directory

        private_directory(log_path)
    else:
        log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("odin")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Retire only handlers installed by this core, never embedding-app handlers.
    for handler in list(root.handlers):
        if getattr(handler, "_odin_core_owned", False):
            root.removeHandler(handler)
            handler.close()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console._odin_core_owned = True
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_path / "odin.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=4,  # bounded 50 MB core log quota
    )
    file_handler._odin_core_owned = True
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"odin.{name}")
