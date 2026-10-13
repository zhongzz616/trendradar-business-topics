"""Rule-based business case discovery on top of TrendRadar's SQLite output.

No AI API, paid service, article-body scraping, or fabricated reach metrics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from email.message import EmailMessage
from pathlib import Path
from smtplib import SMTP, SMTP_SSL
from urllib import request
from zoneinfo import ZoneInfo

if __package__:
    from .review import collect_sources, render_report, save_report
    from .selection import migrate_sent_digests, record_recommendation, recommendation_state
else:
    from review import collect_sources, render_report, save_report
    from selection import migrate_sent_digests, record_recommendation, recommendation_state

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output"
BUSINESS = DATA / "business"
DB = BUSINESS / "events.db"
TZ = ZoneInfo("Asia/Shanghai")
THEMES = {
    "品牌危机": ("品牌信任、信息不对称与召回成本", "为什么一次质量危机会改变消费者对品牌的信任？", "用信任账户和损失曲线展示危机扩散"),
    "商业竞争": ("价格战、博弈论与市场份额", "为什么企业宁愿少赚钱，也要发动价格战？", "用双边收益矩阵和市场份额动画展示竞争"),
    "企业经营": ("现金流、规模经济与经营杠杆", "一家企业的收入增长，为什么仍可能撑不住现金流？", "用现金流河流和成本杠杆图展示经营压力"),
    "战略决策": ("并购协同、机会成本与战略取舍", "企业为什么会卖掉正在经营的业务？", "用业务组合矩阵和资源流向展示战略取舍"),
    "商业创新": ("商业模式、网络效应与单位经济", "新产品为什么能改变一家公司的赚钱方式？", "用用户、成本和收入的反馈回路展示商业模式"),
    "消费与营销": ("品牌定位、定价心理与消费者行为", "品牌联名为什么有时能卖爆，有时却会翻车？", "用定位地图和消费者决策路径展示营销机制"),
}
CRISIS = re.compile(r"召回|食品安全|虚假宣传|投诉|抵制|处罚|危机|暴雷|财务造假|涉嫌|调查|诉讼|recall|scandal|investigation|fraud|lawsuit", re.I)
UNCONFIRMED = re.compile(r"疑爆料|爆料|传闻|消息靠谱吗|尚未证实|否认.{0,20}(?:收购|并购)|rumou?r|unconfirmed|denies?.{0,30}(?:acquir|buy|merg)", re.I)
NOISE = re.compile(r"股价|涨停|跌停|盘中|收盘|开盘|主力资金|明星恋情|绯闻|票房排行|stock price|share price|trading volume", re.I)
STRONG_EVENT = re.compile(r"价格战|降价|召回|并购|收购|破产|裁员|关店|新品|战略|营销|price war|price cut|recall|acquisition|merger|bankruptcy|layoffs|product launch", re.I)
SOURCE_WEIGHT = {"techcrunch": 6, "the-verge": 6, "cnbc-business": 7, "jiemian": 6, "cls-hot": 6, "wallstreetcn-hot": 6, "36kr-quick": 5, "36kr-renqi": 5}
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, company TEXT NOT NULL, industry TEXT NOT NULL, theme TEXT NOT NULL,
 headline TEXT NOT NULL, occurred_at TEXT, first_found TEXT NOT NULL, last_updated TEXT NOT NULL,
 score INTEGER NOT NULL DEFAULT 0, score_json TEXT NOT NULL DEFAULT '{}', knowledge_tags TEXT NOT NULL DEFAULT '[]',
 fact_status TEXT NOT NULL DEFAULT '待核查', event_status TEXT NOT NULL DEFAULT '候选',
 verified_at TEXT, verification_note TEXT,
 last_alerted_score INTEGER NOT NULL DEFAULT 0, last_alerted_sources INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_events_lookup ON events(company,theme,last_updated);
CREATE TABLE IF NOT EXISTS articles (
 id INTEGER PRIMARY KEY, article_key TEXT NOT NULL UNIQUE, event_id INTEGER NOT NULL,
 title TEXT NOT NULL, source_id TEXT NOT NULL, source_name TEXT NOT NULL, url TEXT NOT NULL,
 published_at TEXT, first_found TEXT NOT NULL, last_seen TEXT NOT NULL,
 rank_best INTEGER, rank_latest INTEGER, sightings INTEGER NOT NULL DEFAULT 1,
 FOREIGN KEY(event_id) REFERENCES events(id)
);
CREATE INDEX IF NOT EXISTS ix_articles_event ON articles(event_id);
CREATE TABLE IF NOT EXISTS observations (
 event_id INTEGER NOT NULL, observed_at TEXT NOT NULL, source_count INTEGER NOT NULL,
 best_rank INTEGER, score INTEGER NOT NULL, PRIMARY KEY(event_id,observed_at)
);
CREATE TABLE IF NOT EXISTS deliveries (
 delivery_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL
);
"""

def now() -> datetime:
    return datetime.now(TZ)

def ensure_schema(conn):
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    for name in ("verified_at", "verification_note"):
        if name not in columns:
            conn.execute(f"ALTER TABLE events ADD COLUMN {name} TEXT")

def normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text.casefold())

def word_match(spec: str, text: str) -> bool:
    if spec.startswith("/") and spec.endswith("/"):
        try:
            return re.search(spec[1:-1], text, re.I) is not None
        except re.error:
            return False
    return spec.casefold() in text.casefold()

def load_groups():
    raw = (ROOT / "config/frequency_words.txt").read_text(encoding="utf-8")
    groups = []
    active = False
    for block in re.split(r"\n\s*\n", raw):
        lines = [x.strip() for x in block.splitlines() if x.strip() and not x.lstrip().startswith("#")]
        if not lines:
            continue
        if lines[0] == "[WORD_GROUPS]":
            active = True
            lines = lines[1:]
        if not active or not lines:
            continue
        if not (lines[0].startswith("[") and lines[0].endswith("]")):
            continue
        alias = lines[0][1:-1]
        required = [x[1:] for x in lines[1:] if x.startswith("+")]
        normal = [x for x in lines[1:] if not x.startswith(("+", "!", "@"))]
        if alias.split("·")[0] in THEMES:
            groups.append((alias, required, normal))
    return groups

def identify_company(title: str, companies: list[dict]):
    for item in companies:
        for alias in sorted(item["aliases"], key=len, reverse=True):
            pat = rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])" if re.search(r"[A-Za-z]", alias) else re.escape(alias)
            if re.search(pat, title, re.I):
                return item["name"], item["industry"]
    discovered = re.search(r"\bcompany\s+([A-Z][A-Za-z0-9-]{2,})\b", title)
    if discovered:
        industry = "科技与互联网" if re.search(r"surveillance|software|AI|tech", title, re.I) else "待识别行业"
        return discovered.group(1), industry
    # Headline-only heuristics keep emerging firms eligible without putting them
    # on the fixed list. No generic sector noun is treated as a company name.
    chinese = re.match(r"^([\u4e00-\u9fffA-Za-z0-9·]{2,12})[：:]", title)
    if chinese and not re.search(r"^(?:行业|市场|专家|机构|监管|消息|最新|食品安全|支持科技)", chinese.group(1)):
        return chinese.group(1), "待识别行业"
    chinese = re.search(r"(?:新兴品牌|初创公司|连锁品牌)([\u4e00-\u9fffA-Za-z0-9·]{2,10})(?:宣布|推出|收购|融资|召回|裁员)", title)
    if chinese:
        return chinese.group(1), "待识别行业"
    english = re.match(r"^([A-Z][A-Za-z0-9-]+(?:\s+[A-Z][A-Za-z0-9-]+){0,2})\s+(?:to\s+)?(?:launch(?:es)?|cuts?|acquires?|buys?|merges?|recalls?|rebrands?|raises?|files?|enters?|exits?)\b", title)
    if english and english.group(1) not in {"The", "This", "New"}:
        industry = "科技与互联网" if re.search(r"AI|software|cybersecurity|quantum|cloud", title, re.I) else "待识别行业"
        return english.group(1), industry
    return "待识别企业", "待识别行业"

def action_bucket(title: str) -> str:
    rules = [
        (r"否认.{0,20}(?:收购|并购)|denies?.{0,30}(?:acquir|buy|merg)", "并购否认"),
        (r"renam|rebrand|drops.*brand name|更名|改名", "更名"),
        (r"recall|召回", "召回"),
        (r"layoff|cuts staff|裁员", "裁员"),
        (r"cuts\s+(?:\d{4}\s+)?forecast|下调.*预期", "下调预期"),
        (r"涨价|提价|上调.{0,8}(?:报价|价格)|price hike|raises prices", "提价"),
        (r"price war|价格战", "价格战"),
        (r"acquisition|merger|\b(?:acquires?|buys?|merges?)\b|并购|收购", "并购"),
        (r"privacy backlash|隐私争议", "隐私争议"),
    ]
    return next((name for pattern,name in rules if re.search(pattern,title,re.I)), "其他")

def same_numbered_story(first: str, second: str) -> bool:
    """Link an unnamed headline to a named one only with strong shared details."""
    percentages = lambda title: set(re.findall(r"\d+(?:\.\d+)?%", title))
    if not percentages(first).intersection(percentages(second)):
        return False
    def pairs(title):
        value = normalize(title)
        return {value[i:i+2] for i in range(len(value)-1)}
    left, right = pairs(first), pairs(second)
    overlap = len(left & right)
    return bool(left and right and overlap >= 8 and overlap / min(len(left), len(right)) >= 0.25)

def classify(title: str, groups):
    if NOISE.search(title) and not STRONG_EVENT.search(title):
        return None
    for alias, required, normal in groups:
        if all(word_match(x, title) for x in required) and (not normal or any(word_match(x, title) for x in normal)):
            return alias.split("·")[0]
    return None

def local_rows(day: str):
    def stamp(value):
        if not value:
            return day + " 00:00:00"
        if re.fullmatch(r"\d{2}[:-]\d{2}(?::\d{2})?", value):
            value = value.replace("-", ":")
            return day + " " + value + (":00" if len(value) == 5 else "")
        return value

    news = DATA / "news" / f"{day}.db"
    rss = DATA / "rss" / f"{day}.db"
    rows = []
    if news.exists():
        with sqlite3.connect(news) as c:
            c.row_factory = sqlite3.Row
            q = """SELECT n.id,n.title,n.platform_id,p.name AS source_name,n.url,n.first_crawl_time,
                    n.last_crawl_time,n.rank,n.crawl_count,
                    (SELECT MIN(rank) FROM rank_history WHERE news_item_id=n.id AND rank>0) AS best_rank
                    FROM news_items n LEFT JOIN platforms p ON p.id=n.platform_id"""
            for r in c.execute(q):
                rows.append(dict(title=r["title"], source_id=r["platform_id"], source_name=r["source_name"] or r["platform_id"],
                    url=r["url"] or "", published_at=None, first_found=stamp(r["first_crawl_time"]),last_seen=stamp(r["last_crawl_time"]),
                    rank_best=r["best_rank"] or r["rank"],rank_latest=r["rank"],sightings=r["crawl_count"]))
    if rss.exists():
        with sqlite3.connect(rss) as c:
            c.row_factory = sqlite3.Row
            q = """SELECT r.title,r.feed_id,f.name AS source_name,r.url,r.published_at,
                    r.first_crawl_time,r.last_crawl_time,r.crawl_count
                    FROM rss_items r LEFT JOIN rss_feeds f ON f.id=r.feed_id"""
            for r in c.execute(q):
                rows.append(dict(title=r["title"],source_id=r["feed_id"],source_name=r["source_name"] or r["feed_id"],
                    url=r["url"] or "",published_at=r["published_at"],first_found=stamp(r["first_crawl_time"]),
                    last_seen=stamp(r["last_crawl_time"]),rank_best=None,rank_latest=None,sightings=r["crawl_count"]))
    return rows

def s3_client():
    names = ["S3_BUCKET_NAME", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_ENDPOINT_URL"]
    if not all(os.environ.get(x) for x in names):
        return None
    import boto3
    return boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("S3_REGION") or "auto")

def pull_remote(client, days):
    if not client:
        return
    from botocore.exceptions import ClientError
    bucket = os.environ["S3_BUCKET_NAME"]
    for day in days:
        for kind in ("news", "rss"):
            path = DATA / kind / f"{day}.db"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                client.download_file(bucket, f"{kind}/{day}.db", str(path))
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                    raise
    BUSINESS.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(bucket, "business/events.db", str(DB))
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise

def push_remote(client):
    if not client:
        return
    bucket = os.environ["S3_BUCKET_NAME"]
    client.upload_file(str(DB), bucket, "business/events.db")
    report = BUSINESS / "latest.json"
    if report.exists():
        client.upload_file(str(report), bucket, "business/latest.json")

def event_for_article(c, item, company, industry, theme):
    existing = c.execute("SELECT event_id FROM articles WHERE article_key=?", (item["key"],)).fetchone()
    if existing:
        if company != "待识别企业":
            c.execute("UPDATE events SET company=?,industry=? WHERE id=? AND company='待识别企业'",
                      (company,industry,existing[0]))
        return existing[0]
    cutoff = (now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    best_id, best_sim = None, 0.0
    for row in c.execute("SELECT id,headline FROM events WHERE company=? AND theme=? AND last_updated>=?", (company,theme,cutoff)):
        sim = SequenceMatcher(None, normalize(row["headline"]), normalize(item["title"])).ratio()
        if sim >= 0.50 and company != "待识别企业" and action_bucket(row["headline"]) == action_bucket(item["title"]) != "其他":
            sim = max(sim, 0.62)
        if sim > best_sim:
            best_id, best_sim = row["id"], sim
    if best_id and best_sim >= (0.72 if company == "待识别企业" else 0.58):
        return best_id
    # A source may say "光刻机巨头" while another names ASML. Require the
    # same percentage, action, and substantial wording overlap before linking.
    if action_bucket(item["title"]) != "其他":
        for row in c.execute("SELECT id,company,headline FROM events WHERE theme=? AND last_updated>=?",(theme,cutoff)):
            if (company == "待识别企业") == (row["company"] == "待识别企业"):
                continue
            if action_bucket(row["headline"]) != action_bucket(item["title"]):
                continue
            if not same_numbered_story(row["headline"],item["title"]):
                continue
            if row["company"] == "待识别企业":
                c.execute("UPDATE events SET company=?,industry=?,headline=? WHERE id=?",(company,industry,item["title"],row["id"]))
            return row["id"]
    # A feed's published_at is the article time, not proof of when the event happened.
    c.execute("INSERT INTO events(company,industry,theme,headline,occurred_at,first_found,last_updated) VALUES(?,?,?,?,?,?,?)",
        (company,industry,theme,item["title"],None,item["first_found"],item["last_seen"]))
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]

def score_event(event, articles, prior_events):
    sources = {a["source_id"] for a in articles}
    best = min((a["rank_best"] for a in articles if a["rank_best"] is not None),default=None)
    rank_points = 12 if best and best <= 10 else 8 if best and best <= 30 else 4 if best else 0
    source_points = min(8,max(0,len(sources)-1)*3)
    appearances = sum(a["sightings"] for a in articles)
    repeat_points = min(5,max(0,appearances-1))
    heat = min(25,rank_points+source_points+repeat_points)
    known_company = event["company"] != "待识别企业"
    action = action_bucket(event["headline"])
    knowledge = min(30,18+(6 if known_company else 0)+(5 if len(sources)>=2 else 0)
        +(4 if known_company and action in {"并购","提价"} else 0))
    visual = 18 if event["theme"]=="战略决策" and action=="并购" else 15 if event["theme"] in {"商业竞争","企业经营","战略决策","商业创新"} else 13
    if re.search(r"\d|%|亿元|美元|million|billion",event["headline"],re.I):
        visual = min(20,visual+4)
    novelty = max(2,15-min(8,prior_events*4))
    credible = [s for s in sources if SOURCE_WEIGHT.get(s,0)>=5]
    evidence = 10 if len(credible)>=3 else 8 if len(credible)>=2 else 6 if credible else 3 if len(sources)>=2 else 1
    if not any(a["url"].startswith("https://") for a in articles):
        evidence = 0
    total = heat+knowledge+visual+novelty+evidence
    needs_check = (event["theme"]=="品牌危机" or CRISIS.search(event["headline"]) is not None
                   or any(UNCONFIRMED.search(a["title"]) for a in articles))
    verified = bool(event["verified_at"] and event["verification_note"])
    fact_status = "人工核查通过" if verified else "待核查" if needs_check else "来源已记录，事件细节待复核"
    # Headlines alone cannot prove a recall, allegation, or legal/financial accusation.
    eligible = (not needs_check or verified) and evidence>=5 and known_company
    alert_ready = eligible and (verified or len(credible)>=2 and action!="提价")
    status = "事实核查中" if needs_check and not verified else "信息不足" if not eligible else "优先推荐" if total>=80 else "每日候选" if total>=65 else "低于门槛"
    reasons = {"传播热度及增长速度":heat,"商业知识解释价值":knowledge,"动画可视化潜力":visual,"选题新颖性":novelty,"证据质量":evidence,
        "热度说明":"依据榜单名次、跨来源出现和抓取次数估计；无真实阅读量、播放量或增长率。",
        "证据说明":"仅核对标题、链接及来源，未抓取付费正文；争议类待人工复核。"}
    return total,reasons,fact_status,status,alert_ready

def card(c,event):
    arts = list(c.execute("SELECT * FROM articles WHERE event_id=? ORDER BY rank_best IS NULL, rank_best, first_found",(event["id"],)))
    sources = {a["source_id"] for a in arts}
    best = min((a["rank_best"] for a in arts if a["rank_best"] is not None),default=None)
    prior = c.execute("SELECT COUNT(*) FROM events WHERE company=? AND theme=? AND id<>? AND first_found<?",(event["company"],event["theme"],event["id"],event["first_found"])).fetchone()[0]
    total,reasons,fact,status,eligible=score_event(event,arts,prior)
    concept,title,visual=THEMES[event["theme"]]
    if event["theme"] == "品牌危机" and action_bucket(event["headline"]) == "更名":
        concept,title,visual="品牌定位、监管风险与消费者认知","为什么企业会给已有产品重新命名？","用产品名称、监管要求和消费者预期三层图展示定位变化"
    elif event["theme"] == "企业经营" and action_bucket(event["headline"]) == "下调预期":
        concept,title,visual="成本冲击、利润率与经营杠杆","为什么成本上涨会迫使企业下调经营预期？","用收入、成本与利润的动态面积图展示冲击"
    elif event["theme"] == "企业经营" and action_bucket(event["headline"]) == "裁员":
        concept,title,visual="固定成本、组织调整与现金流","企业裁员时究竟在调整哪些成本？","用成本结构和现金流时间轴展示组织决策"
    elif event["theme"] == "商业竞争" and action_bucket(event["headline"]) == "提价":
        concept,title,visual="市场势力、转换成本与供应链定价权","关键设备供应商为何可能拥有涨价能力？","用供应链依赖图和替代成本曲线展示定价权"
    elif event["theme"] == "战略决策" and action_bucket(event["headline"]) == "并购":
        concept,title,visual="并购协同、买与建决策与平台战略","为什么企业选择通过并购获取新能力？","用技术能力地图和买与建时间轴展示并购逻辑"
    elif event["theme"] == "战略决策" and action_bucket(event["headline"]) == "并购否认":
        concept,title,visual="企业信号、信息披露与并购传闻","企业为什么会公开否认并购传闻？","用传闻、正式披露与决策信号的时间轴展示信息变化"
    elif event["theme"] == "品牌危机" and re.search(r"light leak|质量问题",event["headline"],re.I):
        concept,title,visual="产品质量、信任成本与售后决策","小产品缺陷为什么可能变成大品牌问题？","用故障率到信任成本的扩散图展示风险"
    if total < 65:
        title = "暂不推荐制作：未达到选题门槛"
    angles=[f"用{concept.split('、')[0]}解释这件事",f"比较{event['company']}与同行的不同选择", "如果条件改变，商业结果会怎样？"]
    links=[{"source":a["source_name"],"url":a["url"],"title":a["title"]} for a in arts if a["url"]]
    trend="持续出现" if sum(a["sightings"] for a in arts)>1 else "首次监测"
    result={"事件名称":event["headline"],"企业":event["company"],"行业":event["industry"],"分类":event["theme"],
        "事件发生时间":event["occurred_at"] or "未确认","首次监测时间":event["first_found"],
        "报道发布时间":[a["published_at"] for a in arts if a["published_at"]],
        "事件简述":(event["headline"][:96]+("…" if len(event["headline"])>96 else "")),
        "主要新闻来源及原始链接":links[:5],"热度及变化趋势":{"来源数":len(sources),"最好榜位":best,"状态":trend,"真实阅读量":"未知"},
        "综合评分":total,"评分理由":reasons,"商业知识概念":[concept],"三个选题角度":angles,
        "推荐视频标题":title,"知识可视化方法":visual,"是否值得立即制作":bool(total>=80 and eligible),
        "事实状态":fact,"核查记录":event["verification_note"],"事件状态":status}
    return result,len(sources),best

def send_notification(subject: str, body: str, html_body: str | None = None):
    if os.environ.get("FEISHU_WEBHOOK_URL"):
        payload={"msg_type":"text","content":{"text":subject+"\n"+body}}
        req=request.Request(os.environ["FEISHU_WEBHOOK_URL"],data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"})
        with request.urlopen(req,timeout=20) as response:
            result=json.loads(response.read().decode("utf-8"))
            return "feishu",response.status==200 and result.get("code",result.get("StatusCode",result.get("errcode")))==0
    if os.environ.get("NTFY_TOPIC"):
        url=os.environ.get("NTFY_SERVER_URL","https://ntfy.sh").rstrip("/")+"/"+os.environ["NTFY_TOPIC"]
        req=request.Request(url,data=(subject+"\n"+body).encode("utf-8"))
        with request.urlopen(req,timeout=20) as r:return "ntfy",r.status==200
    if os.environ.get("EMAIL_FROM") and os.environ.get("EMAIL_PASSWORD") and os.environ.get("EMAIL_TO"):
        msg=EmailMessage(); msg["Subject"]=subject;msg["From"]=os.environ["EMAIL_FROM"];msg["To"]=os.environ["EMAIL_TO"];msg.set_content(body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        host=os.environ.get("EMAIL_SMTP_SERVER") or "smtp.qq.com";port=int(os.environ.get("EMAIL_SMTP_PORT") or 465)
        if port==465:
            with SMTP_SSL(host,port,timeout=20) as server:server.login(os.environ["EMAIL_FROM"],os.environ["EMAIL_PASSWORD"]);server.send_message(msg)
        else:
            with SMTP(host,port,timeout=20) as server:server.starttls();server.login(os.environ["EMAIL_FROM"],os.environ["EMAIL_PASSWORD"]);server.send_message(msg)
        return "email",True
    return "unconfigured",False

def main():
    p=argparse.ArgumentParser();p.add_argument("--test-notification",action="store_true");p.add_argument("--no-send",action="store_true")
    p.add_argument("--send-review", action="store_true", help="Send one deduplicated review supplement for today")
    args=p.parse_args()
    if args.test_notification:
        channel,ok=send_notification("TrendRadar 商业选题通知测试","这是一次真实的通知连通性测试。")
        print(json.dumps({"channel":channel,"success":ok},ensure_ascii=False));sys.exit(0 if ok else 2)
    BUSINESS.mkdir(parents=True,exist_ok=True)
    moment=now();days=[moment.date().isoformat(),(moment-timedelta(days=1)).date().isoformat()]
    client=s3_client();pull_remote(client,days)
    companies=json.loads((ROOT/"business_topics/companies.json").read_text(encoding="utf-8"))
    groups=load_groups();rows=[]
    for day in days:rows.extend(local_rows(day))
    with sqlite3.connect(DB) as c:
        c.row_factory=sqlite3.Row;ensure_schema(c)
        migrate_sent_digests(c, ROOT/"business_topics/sent_digest_seed.json")
        matched=0;new_articles=0
        for item in rows:
            theme=classify(item["title"],groups)
            if not theme:continue
            matched+=1
            company,industry=identify_company(item["title"],companies)
            item["key"]=hashlib.sha256((item["source_id"]+"|"+(item["url"] or normalize(item["title"]))).encode()).hexdigest()
            event_id=event_for_article(c,item,company,industry,theme)
            old=c.execute("SELECT id FROM articles WHERE article_key=?",(item["key"],)).fetchone()
            if not old:new_articles+=1
            c.execute("""INSERT INTO articles(article_key,event_id,title,source_id,source_name,url,published_at,first_found,last_seen,rank_best,rank_latest,sightings)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(article_key) DO UPDATE SET
                title=CASE WHEN excluded.last_seen>=articles.last_seen THEN excluded.title ELSE articles.title END,
                first_found=MIN(articles.first_found,excluded.first_found),last_seen=MAX(articles.last_seen,excluded.last_seen),
                rank_best=CASE WHEN articles.rank_best IS NULL THEN excluded.rank_best
                               WHEN excluded.rank_best IS NULL THEN articles.rank_best ELSE MIN(articles.rank_best,excluded.rank_best) END,
                rank_latest=CASE WHEN excluded.last_seen>=articles.last_seen THEN excluded.rank_latest ELSE articles.rank_latest END,
                sightings=MAX(articles.sightings,excluded.sightings)""",
                (item["key"],event_id,item["title"],item["source_id"],item["source_name"],item["url"],item["published_at"],item["first_found"],item["last_seen"],item["rank_best"],item["rank_latest"],item["sightings"]))
            c.execute("UPDATE events SET last_updated=MAX(last_updated,?) WHERE id=?",(item["last_seen"],event_id))
        c.commit()
        cards=[];alerts=[];candidate_ids=[]
        for event in c.execute("SELECT * FROM events WHERE last_updated>=? ORDER BY first_found DESC",((moment-timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),)).fetchall():
            info,source_count,best=card(c,event)
            c.execute("UPDATE events SET score=?,score_json=?,knowledge_tags=?,fact_status=?,event_status=? WHERE id=?",
                (info["综合评分"],json.dumps(info["评分理由"],ensure_ascii=False),json.dumps(info["商业知识概念"],ensure_ascii=False),info["事实状态"],info["事件状态"],event["id"]))
            c.execute("INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?)",(event["id"],moment.isoformat(timespec="seconds"),source_count,best,info["综合评分"]))
            recommend, state, reason = recommendation_state(c,event,info,moment,SOURCE_WEIGHT)
            info.update({"事件ID":event["id"],"推荐状态":state,"推荐理由":reason})
            cards.append((event["id"],info))
            if recommend:
                candidate_ids.append(event["id"])
                if info["是否值得立即制作"]:alerts.append((event["id"],info,source_count))
        cards.sort(key=lambda x:x[1]["综合评分"],reverse=True)
        daily=[x[1] for x in cards if x[0] in candidate_ids][:5]
        selected_ids={x["事件ID"] for x in daily}
        for event_id,info in cards:
            if event_id in candidate_ids and event_id not in selected_ids:
                info["推荐状态"]="人工候补"
                info["推荐理由"]="达到条件；本次最多推荐5条，保留供人工审查"
        info_by_id={event_id:info for event_id,info in cards}
        def describe(source_id,title,url):
            key=hashlib.sha256((source_id+"|"+(url or normalize(title))).encode()).hexdigest()
            article=c.execute("SELECT event_id FROM articles WHERE article_key=?",(key,)).fetchone()
            if article and article[0] in info_by_id:
                info=info_by_id[article[0]]
                return {"event_id":article[0],"score":info["综合评分"],
                        "decision":("本次推荐·" if article[0] in selected_ids else "")+info["推荐状态"],
                        "decision_reason":info["推荐理由"]}
            if NOISE.search(title) and not STRONG_EVENT.search(title):
                return {"decision":"行情或娱乐规则排除","decision_reason":"原始标题仍保留，方便人工复核"}
            theme=classify(title,groups)
            return {"decision":"未进入候选","decision_reason":f"命中{theme}，暂无符合推荐条件的事件" if theme else "商业关键词组合未命中；这不代表没有商业价值，请人工复核"}
        sources=collect_sources(DATA,ROOT,moment,describe)
        output={"generated_at":moment.isoformat(timespec="seconds"),"raw_rows":len(rows),"matched_rows":matched,"new_articles":new_articles,
            "events":len(cards),"daily_candidates":daily,"important_alerts":[x[1] for x in alerts],"top_cases":[x[1] for x in cards[:10]],
            "event_decisions":[x[1] for x in cards],"platform_lists":sources,
            "suppressed_repeats":sum(x[1]["推荐状态"]=="已推荐·无实质进展" for x in cards)}
        plain,document=render_report(output)
        if not args.no_send:
            day=moment.date().isoformat()
            key=("review:v2:" if args.send_review else "daily:")+day
            due=(args.send_review or moment.hour>=10) and not c.execute("SELECT 1 FROM deliveries WHERE delivery_key=?",(key,)).fetchone()
            if due:
                subject=("商业热点审查补充｜" if args.send_review else "每日商业选题审查｜")+day
                channel,ok=send_notification(subject,plain,document)
                output["notification_result"]={"channel":channel,"success":ok,"delivery_key":key}
                if not ok:
                    raise RuntimeError("Review notification was not delivered")
                c.execute("INSERT INTO deliveries VALUES(?,?,?,?)",(key,moment.isoformat(),channel,"sent"))
                for info in daily:
                    record_recommendation(c,key,info["事件ID"],moment)
                save_report(BUSINESS/"digests",day+("-supplement" if args.send_review else ""),output,plain,document)
                c.commit()
            elif not args.send_review:
                for event_id,info,source_count in alerts:
                    body=f"{info['事件名称']}\n{info['推荐状态']}：{info['推荐理由']}\n评分 {info['综合评分']}/100｜{info['商业知识概念'][0]}\n{info['推荐视频标题']}\n"+"\n".join(x["url"] for x in info["主要新闻来源及原始链接"][:2])
                    channel,ok=send_notification("重要商业热点",body)
                    if ok:
                        alert_key=f"alert:{event_id}:{moment.isoformat(timespec='seconds')}"
                        c.execute("UPDATE events SET last_alerted_score=?,last_alerted_sources=? WHERE id=?",(info["综合评分"],source_count,event_id))
                        c.execute("INSERT INTO deliveries VALUES(?,?,?,?)",(alert_key,moment.isoformat(),channel,"sent"))
                        record_recommendation(c,alert_key,event_id,moment)
                        c.commit()
        save_report(BUSINESS,"latest",output,plain,document)
        save_report(BUSINESS/"reviews",moment.date().isoformat(),output,plain,document)
        c.commit()
    push_remote(client)
    print(json.dumps({k:v for k,v in output.items() if k not in {"top_cases","daily_candidates","important_alerts","platform_lists","event_decisions"}},ensure_ascii=False))
    print("event_database",DB)
    print("report",BUSINESS/"latest.json")

if __name__=="__main__":main()
