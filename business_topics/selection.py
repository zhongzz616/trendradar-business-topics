"""Track recommendations across days; repeated crawling is not new evidence."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

NOTICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_notifications (
 delivery_key TEXT NOT NULL, event_id INTEGER NOT NULL, sent_at TEXT NOT NULL,
 content_json TEXT NOT NULL, PRIMARY KEY(delivery_key,event_id),
 FOREIGN KEY(event_id) REFERENCES events(id)
);
CREATE INDEX IF NOT EXISTS ix_notifications_event ON event_notifications(event_id,sent_at);
"""


def parse_time(value, fallback_zone):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=fallback_zone) if result.tzinfo is None else result
    except (TypeError, ValueError):
        return None


def article_key(source, url, title):
    import hashlib
    return hashlib.sha256((source + "|" + (url or normalize(title))).encode()).hexdigest()


def normalize(title):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", title.casefold())


def facts(title):
    quantities = sorted(set(re.findall(
        r"\d+(?:\.\d+)?\s*(?:%|亿元|万元|亿美?元|万美元|million|billion|stores|jobs)", title, re.I)))
    stages = []
    for name, pattern in [
        ("批准", r"获批|批准|approved|approval"),
        ("完成", r"完成.{0,8}(?:收购|并购|交易)|completed?.{0,16}(?:acquisition|merger|deal)"),
        ("终止", r"终止|撤回|取消.{0,8}(?:交易|收购)|abandon|terminat|withdraw|cancel.{0,16}(?:deal|acquisition)"),
        ("法律决定", r"裁定|判决|达成和解|settlement|court.{0,20}rul"),
        ("正式发布", r"正式发布|开始销售|上市销售|starts? selling|officially launches"),
    ]:
        if re.search(pattern, title, re.I):
            stages.append(name)
    return {"quantities": quantities, "stages": stages}


def snapshot(articles, verified=False):
    return {"verified": verified, "articles": [
        {"key": a["article_key"], "title": a["title"], "facts": facts(a["title"])} for a in articles]}


def record_recommendation(conn, delivery_key, event_id, moment):
    event = conn.execute("SELECT verified_at,verification_note FROM events WHERE id=?", (event_id,)).fetchone()
    arts = conn.execute("SELECT * FROM articles WHERE event_id=?", (event_id,)).fetchall()
    conn.execute("INSERT OR IGNORE INTO event_notifications VALUES(?,?,?,?)", (
        delivery_key, event_id, moment.isoformat(timespec="seconds"),
        json.dumps(snapshot(arts, bool(event[0] and event[1])), ensure_ascii=False)))


def migrate_sent_digests(conn, seed_file):
    """Import only reports whose delivery is confirmed in the existing DB."""
    conn.executescript(NOTICE_SCHEMA)
    if not seed_file.exists():
        return
    for digest in json.loads(seed_file.read_text(encoding="utf-8")):
        delivery = conn.execute("SELECT sent_at FROM deliveries WHERE delivery_key=? AND status='sent'",
                                (digest["delivery_key"],)).fetchone()
        if not delivery:
            continue
        for item in digest["events"]:
            event = conn.execute("SELECT id FROM events WHERE headline=?", (item["headline"],)).fetchone()
            if not event:
                continue
            baseline = {"verified": False, "articles": [
                {"key": article_key(a["source_id"], a["url"], a["title"]),
                 "title": a["title"], "facts": facts(a["title"])} for a in item["articles"]]}
            conn.execute("INSERT OR IGNORE INTO event_notifications VALUES(?,?,?,?)", (
                digest["delivery_key"], event[0], delivery[0], json.dumps(baseline, ensure_ascii=False)))


def recommendation_state(conn, event, info, moment, source_weights):
    arts = conn.execute("SELECT * FROM articles WHERE event_id=?", (event["id"],)).fetchall()
    previous = conn.execute("SELECT * FROM event_notifications WHERE event_id=? ORDER BY sent_at DESC LIMIT 1",
                            (event["id"],)).fetchone()
    if info["事件状态"] not in {"优先推荐", "每日候选"}:
        reasons = {"事实核查中": "标题涉及危机、指控、否认或未证实消息，需核查原始披露",
                   "信息不足": "企业尚未识别或来源证据不足", "低于门槛": "规则评分不足65分"}
        return False, info["事件状态"], reasons.get(info["事件状态"], "暂未达到推荐条件")
    cutoff = moment - timedelta(hours=48)
    # RSS timestamps without offsets are feed publication timestamps (UTC),
    # while first_found is explicitly in the configured local timezone.
    fresh = [a for a in arts if (
        parse_time(a["published_at"], timezone.utc) or parse_time(a["first_found"], moment.tzinfo)
    ) and (parse_time(a["published_at"], timezone.utc) or parse_time(a["first_found"], moment.tzinfo)) >= cutoff]
    if not previous:
        return (True, "新增候选", "首次推荐；48小时内发布或首次发现，已达到基础证据与评分门槛") if fresh else (
            False, "历史观察", "原始报道超过48小时；重新抓到旧文章不算新增事件")
    baseline = json.loads(previous["content_json"])
    if event["verified_at"] and event["verification_note"] and not baseline.get("verified"):
        return True, "核查进展", "此前已推荐，现新增人工核查记录"
    sent = parse_time(previous["sent_at"], moment.tzinfo)
    old_articles = baseline.get("articles", [])
    old_titles = [normalize(a["title"]) for a in old_articles]
    old_quantities = {x for a in old_articles for x in a["facts"]["quantities"]}
    old_stages = {x for a in old_articles for x in a["facts"]["stages"]}
    old_by_key = {a["key"]: a for a in old_articles}
    for a in fresh:
        observed = parse_time(a["last_seen"], moment.tzinfo)
        if not observed or observed <= sent or source_weights.get(a["source_id"], 0) < 5:
            continue
        old = old_by_key.get(a["article_key"])
        if old and normalize(old["title"]) == normalize(a["title"]):
            continue
        if not old and (parse_time(a["first_found"], moment.tzinfo) or sent) <= sent:
            continue
        new_facts = facts(a["title"])
        stages = set(new_facts["stages"]) - old_stages
        quantities = set(new_facts["quantities"]) - old_quantities
        if stages:
            return True, "重大进展", "新增报道出现实质阶段变化：" + "、".join(sorted(stages))
        # Changed numbers require otherwise strongly similar wording. A new
        # publisher or a differently worded copy alone does not count.
        similarity = max((SequenceMatcher(None, normalize(a["title"]), t).ratio()
                          for t in old_titles), default=0)
        if quantities and similarity >= 0.75:
            return True, "重大进展", "新报道中的关键数值变化：" + "、".join(sorted(quantities))
    return False, "已推荐·无实质进展", "上次推荐于" + previous["sent_at"][:10] + "；重复抓取、排名和分数变化不算新进展"
