"""Search the curated event history by company, theme, title, or score."""
import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "output/business/events.db"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="", help="Company or headline substring")
    parser.add_argument("--theme", default="", help="One of the six Chinese themes")
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error(f"Database not found: {args.database}")
    with sqlite3.connect(f"file:{args.database}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""SELECT e.id,e.company,e.industry,e.theme,e.headline,e.first_found,
            e.last_updated,e.score,e.fact_status,e.event_status,
            (SELECT COUNT(*) FROM articles a WHERE a.event_id=e.id) AS article_count
            FROM events e WHERE (e.company LIKE ? OR e.headline LIKE ?
            OR EXISTS (SELECT 1 FROM articles a WHERE a.event_id=e.id AND a.title LIKE ?))
            AND e.theme LIKE ? AND e.score>=?
            ORDER BY e.last_updated DESC LIMIT ?""",
            (f"%{args.query}%", f"%{args.query}%", f"%{args.query}%",
             f"%{args.theme}%", args.min_score, max(1, min(args.limit, 200)))).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["sources"] = [dict(a) for a in conn.execute(
                "SELECT source_name,url,published_at,first_found FROM articles WHERE event_id=? ORDER BY first_found",
                (row["id"],))]
            result.append(item)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
