"""Copy TrendRadar's SQLite files to/from a dedicated Git history branch.

The branch is checked out separately by GitHub Actions. This module does not
contact GitHub or require credentials. No data is silently deleted from it.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
TZ = ZoneInfo("Asia/Shanghai")


def database_ok(path: Path) -> bool:
    if not path.exists():
        return False
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        result = conn.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {path}")
    return True


def copy_db(source: Path, destination: Path) -> bool:
    if not database_ok(source):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
    database_ok(destination)
    return True


def recent_days() -> list[str]:
    today = datetime.now(TZ).date()
    return [(today - timedelta(days=offset)).isoformat() for offset in (0, 1)]


def sync(mode: str, history: Path) -> list[str]:
    copied = []
    for day in recent_days():
        for kind in ("news", "rss"):
            relative = Path(kind) / f"{day}.db"
            source, destination = (history / relative, OUTPUT / relative) if mode == "restore" else (OUTPUT / relative, history / relative)
            if copy_db(source, destination):
                copied.append(str(relative))
    relative = Path("business/events.db")
    source, destination = (history / relative, OUTPUT / relative) if mode == "restore" else (OUTPUT / relative, history / relative)
    if copy_db(source, destination):
        copied.append(str(relative))
    if mode == "save":
        reports = [OUTPUT / "business" / f"latest.{extension}" for extension in ("json", "html", "txt")]
        for folder in ("reviews", "digests"):
            directory = OUTPUT / "business" / folder
            if directory.exists():
                reports.extend(p for p in directory.iterdir() if p.suffix in {".json", ".html", ".txt"})
        for report in reports:
            if report.exists():
                relative = report.relative_to(OUTPUT)
                target = history / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(report, target)
                copied.append(str(relative))
    return copied


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("restore", "save"))
    parser.add_argument("history", type=Path)
    arguments = parser.parse_args()
    print("\n".join(sync(arguments.mode, arguments.history.resolve())))
