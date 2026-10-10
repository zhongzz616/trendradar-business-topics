"""Record a human source check for a sensitive event before it can be pushed."""
import argparse
import sqlite3
from pathlib import Path

from engine import DB, ensure_schema, now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("event_id", type=int)
    parser.add_argument("--source-url", required=True, help="Primary source or corroborating article reviewed")
    parser.add_argument("--note", required=True, help="What the source actually establishes")
    parser.add_argument("--database", type=Path, default=DB)
    args = parser.parse_args()
    if not args.source_url.startswith("https://"):
        parser.error("A reviewed HTTPS source URL is required")
    if len(args.note.strip()) < 12:
        parser.error("Explain the verified fact in at least 12 characters")
    with sqlite3.connect(args.database) as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT headline FROM events WHERE id=?", (args.event_id,)).fetchone()
        if row is None:
            parser.error(f"Unknown event id: {args.event_id}")
        conn.execute("UPDATE events SET verified_at=?, verification_note=? WHERE id=?",
                     (now().isoformat(timespec="seconds"), f"{args.note.strip()} | {args.source_url}", args.event_id))
    print(f"Recorded source check for event {args.event_id}: {row[0]}")


if __name__ == "__main__":
    main()
