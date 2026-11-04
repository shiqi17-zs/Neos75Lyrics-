#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Logging for Neos75 Screen Helper: rotating file logs + crash capture."""
import logging
import logging.handlers
import os
import sys
import time
import traceback
import zipfile
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".neos75_lyrics"
LOG_DIR = HOME / "logs"
_ready = False


MAX_TOTAL = 10 * 1024 * 1024      # 10 MB across all rotated files
MAX_SINGLE = 1900 * 1024          # 1.9 MB per file -> 5 files, under 10 MB


def _prune(path, keep):
    """Keep only `keep` newest app.log* files."""
    files = sorted(LOG_DIR.glob("app.log*"), key=lambda f: f.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except Exception:
            pass


def setup(level=logging.DEBUG, name="neos75"):
    global _ready
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if _ready:
        return logger
    logger.setLevel(level)
    logger.propagate = False
    handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=MAX_SINGLE, backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    _prune(LOG_DIR / "app.log", 4)

    # 0.0.1 wrote a log next to the exe; remove it and never do that again
    try:
        import sys
        if getattr(sys, "frozen", False):
            side = Path(sys.executable).parent / "Neos75Lyrics.log"
            for stray in (side, side.with_suffix(".log.1"), side.with_suffix(".log.2")):
                if stray.exists():
                    stray.unlink()
    except Exception:
        pass

    _ready = True
    return logger


def log(name="neos75"):
    setup()
    return logging.getLogger(name)


def dbg(message):
    try:
        log().debug(str(message))
    except Exception:
        pass


def info(message):
    try:
        log().info(str(message))
    except Exception:
        pass


def warn(message):
    try:
        log().warning(str(message))
    except Exception:
        pass


def error(message):
    try:
        log().error(str(message))
    except Exception:
        pass


def exception(message):
    try:
        log().error("%s\n%s", message, traceback.format_exc())
    except Exception:
        pass


def install_hooks(root=None):
    """Log every uncaught exception, including Tk callback errors."""
    def sys_hook(exc_type, exc, tb):
        try:
            log().error("uncaught: %s\n%s", exc_type.__name__,
                        "".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = sys_hook

    if root is not None:
        def tk_hook(exc_type, exc, tb):
            try:
                log().error("tk callback: %s\n%s", exc_type.__name__,
                            "".join(traceback.format_exception(exc_type, exc, tb)))
            except Exception:
                pass
        root.report_callback_exception = tk_hook


def export_bundle(dest=None):
    """Zip logs + config + a short system summary for sharing."""
    dest = Path(dest) if dest else Path.home() / "Desktop"
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / time.strftime("Neos75_诊断_%Y%m%d_%H%M%S.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        if LOG_DIR.exists():
            for f in sorted(LOG_DIR.glob("app.log*")):
                zf.write(f, f"logs/{f.name}")
        cfg = HOME / "config.json"
        if cfg.exists():
            zf.write(cfg, "config.json")
        vlog = HOME / "valorant"
        if vlog.exists():
            for f in sorted(vlog.glob("ocr.log")):
                zf.write(f, f"valorant/{f.name}")
            for f in sorted(vlog.glob("band_*.png"))[-3:]:
                zf.write(f, f"valorant/{f.name}")
        summary = [
            "Neos75 Screen Helper diagnostics",
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"python: {sys.version.split()[0]}",
            f"frozen: {getattr(sys, 'frozen', False)}",
            f"executable: {sys.executable}",
            f"cwd: {os.getcwd()}",
        ]
        try:
            import platform
            summary.append(f"os: {platform.platform()}")
        except Exception:
            pass
        zf.writestr("summary.txt", "\n".join(summary))
    return out
