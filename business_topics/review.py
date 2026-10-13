"""Unfiltered source snapshots and readable daily review emails."""
from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path

import yaml

SOURCE_ORDER = ["weibo", "douyin", "baidu", "cls-hot", "wallstreetcn-hot",
                "zhihu", "bilibili-hot-search", "toutiao", "36kr-quick", "36kr-renqi"]
UNCONNECTED = [
    {"name": name, "status": "未接入", "reason": reason, "kind": "未接入来源", "items": []}
    for name, reason in [
        ("Reuters", "尚未配置可验证的免费公开数据源"),
        ("Bloomberg", "尚未配置可验证的免费公开数据源"),
        ("Financial Times", "尚未配置可验证的免费公开数据源"),
        ("第一财经", "尚未找到并配置可验证的官方公开RSS"),
    ]]


def collect_sources(data: Path, root: Path, moment, describe):
    config = yaml.safe_load((root / "config/config.yaml").read_text(encoding="utf-8"))
    day = moment.date().isoformat()
    sources = []
    platform_config = config.get("platforms", {}).get("sources", [])
    platform_config = sorted(platform_config, key=lambda s: SOURCE_ORDER.index(s["id"])
                             if s["id"] in SOURCE_ORDER else len(SOURCE_ORDER))
    for kind, specs in [("news", platform_config), ("rss", config.get("rss", {}).get("feeds", []))]:
        path = data / kind / f"{day}.db"
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True) if path.exists() else None
        if conn:
            conn.row_factory = sqlite3.Row
        try:
            for spec in specs:
                if spec.get("enabled", True) is False:
                    continue
                source_id = spec["id"]
                info = {"id": source_id, "name": spec.get("name", source_id),
                        "kind": "热榜前10" if kind == "news" else "RSS最新5条（非热榜）",
                        "status": "未抓取", "snapshot_at": None, "reason": "当天无抓取记录", "items": []}
                if conn:
                    records = "crawl_records" if kind == "news" else "rss_crawl_records"
                    latest = conn.execute(f"SELECT id,crawl_time FROM {records} ORDER BY crawl_time DESC LIMIT 1").fetchone()
                    if latest:
                        info["snapshot_at"] = day + " " + latest["crawl_time"].replace("-", ":")
                        status_table = "crawl_source_status" if kind == "news" else "rss_crawl_status"
                        id_field = "platform_id" if kind == "news" else "feed_id"
                        status = conn.execute(f"SELECT * FROM {status_table} WHERE crawl_record_id=? AND {id_field}=?",
                                              (latest["id"], source_id)).fetchone()
                        if status:
                            info["status"] = "成功" if status["status"] == "success" else "失败"
                            info["reason"] = "最新抓取快照；原始列表未经过商业关键词过滤" if status["status"] == "success" else (
                                status["error_message"] if kind == "rss" and status["error_message"] else
                                "本次来源抓取失败，详细原因见Actions日志；不使用旧榜单填充")
                        if info["status"] == "成功":
                            if kind == "news":
                                rows = conn.execute("""SELECT n.title,n.url,MIN(h.rank) AS rank,
                                    n.first_crawl_time AS first_found,NULL AS published_at
                                    FROM rank_history h JOIN news_items n ON n.id=h.news_item_id
                                    WHERE h.crawl_time=? AND n.platform_id=? AND h.rank>0
                                    GROUP BY n.id ORDER BY rank,n.id LIMIT 10""", (latest["crawl_time"], source_id)).fetchall()
                            else:
                                rows = conn.execute("""SELECT title,url,NULL AS rank,first_crawl_time AS first_found,published_at
                                    FROM rss_items WHERE feed_id=? AND last_crawl_time=?
                                    ORDER BY CASE WHEN published_at IS NULL OR published_at='' THEN 1 ELSE 0 END,
                                    julianday(published_at) DESC,first_crawl_time DESC,id DESC LIMIT 5""",
                                                    (source_id, latest["crawl_time"])).fetchall()
                            for index, row in enumerate(rows, 1):
                                item = dict(row)
                                item["position"] = index
                                item.update(describe(source_id, item["title"], item["url"]))
                                info["items"].append(item)
                            if not rows:
                                info["reason"] += "；本次返回0条"
                sources.append(info)
        finally:
            if conn:
                conn.close()
    return sources + [dict(s) for s in UNCONNECTED]


def score_text(item):
    return " / ".join(f"{k} {v}" for k, v in item["评分理由"].items() if isinstance(v, int))


def render_report(report):
    stamp = report["generated_at"]
    candidates = report["daily_candidates"]
    sources = report["platform_lists"]
    text = [f"商业热点人工审查简报｜{stamp[:10]}", f"生成时间：{stamp}（北京时间）",
            f"新增或有实质进展的推荐：{len(candidates)}条；不凑数。",
            "原始平台列表保留所有主题；RSS最新文章不代表热度排名。", ""]
    esc = lambda v: html.escape(str(v or ""))
    def link(url, title):
        return f'<a href="{esc(url)}">{esc(title)}</a>' if url.startswith(("https://", "http://")) else esc(title)
    body = [f'<h1>商业热点人工审查简报</h1><p>{esc(stamp[:10])} · 北京时间 {esc(stamp[11:19])}</p>',
            f'<p>新增或有实质进展的推荐 <b>{len(candidates)}</b> 条。下面先展示原始来源，再列最终汇总与筛选理由。</p>',
            '<p class="note">规则评分用于排序。没有真实阅读量、播放量或增长率；RSS按发布时间展示，没有官方热度排名。未命中规则的标题仍保留，供人工发现漏选。</p>',
            '<h2>各来源原始列表</h2>']
    for source in sources:
        heading = f"{source['name']}｜{source['kind']}｜{source['status']}"
        text += [heading, f"快照：{source.get('snapshot_at') or '无'}；{source['reason']}"]
        body += [f'<h3>{esc(heading)}</h3>', f'<p class="note">快照：{esc(source.get("snapshot_at") or "无")} · {esc(source["reason"])}</p>']
        if source["items"]:
            body.append('<table><tr><th>榜位/序号</th><th>原始标题与链接</th><th>筛选说明</th></tr>')
        for item in source["items"]:
            position = f"榜位{item['rank']}" if item["rank"] is not None else f"最新{item['position']}"
            time_note = "发布时间：" + (item.get("published_at") or "未知") if item["rank"] is None else ""
            decision = item["decision"] + "：" + item["decision_reason"]
            text += [f"{position}. {item['title']}", item["url"], time_note, decision]
            body.append(f'<tr><td>{esc(position)}</td><td>{link(item["url"], item["title"])}'
                        + (f'<br><small>{esc(time_note)}</small>' if time_note else '')
                        + f'</td><td>{esc(decision)}</td></tr>')
        if source["items"]:
            body.append('</table>')
        text.append("")
    body.append('<h2>最终推荐汇总</h2>')
    text += ["最终推荐汇总"]
    if not candidates:
        message = "本次没有达到门槛且未重复推荐的新增商业选题。已推荐事件和待核查线索在下方列出。"
        text.append(message); body.append(f'<p>{message}</p>')
    for index, item in enumerate(candidates, 1):
        heading = f"{index}. {item['推荐视频标题']}（{item['综合评分']}分 · {item['推荐状态']}）"
        lines = [item["事件名称"], f"企业/行业：{item['企业']} / {item['行业']}",
                 f"事件时间：{item['事件发生时间']}；首次监测：{item['首次监测时间']}",
                 f"新闻简述：{item['事件简述']}", f"推荐依据：{item['推荐理由']}",
                 f"评分：{score_text(item)}", f"热度代理：{json.dumps(item['热度及变化趋势'],ensure_ascii=False)}",
                 f"知识概念：{'；'.join(item['商业知识概念'])}",
                 f"三个角度：{'；'.join(item['三个选题角度'])}", f"可视化：{item['知识可视化方法']}",
                 f"事实状态：{item['事实状态']}；立即制作：{'可优先研究，仍需核对原始资料' if item['是否值得立即制作'] else '先研究与核查'}"]
        text += [heading, *lines]
        body += [f'<h3>{esc(heading)}</h3>', '<p>' + '<br>'.join(esc(x) for x in lines) + '</p>']
        for source in item["主要新闻来源及原始链接"]:
            text += [source["source"] + "：" + source["url"]]
            body.append(f'<p>{esc(source["source"])}：{link(source["url"],source["title"])}</p>')
        text.append("")
    text.append("全部匹配事件及未入选理由")
    body.append('<h2>全部匹配事件及未入选理由</h2><table><tr><th>事件</th><th>分数</th><th>判断</th></tr>')
    for item in report["event_decisions"]:
        title = item["事件名称"]
        url = item["主要新闻来源及原始链接"][0]["url"] if item["主要新闻来源及原始链接"] else ""
        why = item["推荐状态"] + "：" + item["推荐理由"]
        text += [f"{title}｜{item['综合评分']}分｜{why}"]
        body.append(f'<tr><td>{link(url,title)}</td><td>{item["综合评分"]}</td><td>{esc(why)}</td></tr>')
    body.append('</table><p class="note">相同事件曾推荐过，只有新报道出现明确阶段、关键数值或核查变化才会再次推荐；榜位、抓取次数和分数波动不算重大进展。免费规则只识别有限的标题变化，制作前需人工核对。</p>')
    text.append("重复事件不会因持续在榜、RSS重现或分数变化而再次推荐。平台原始列表可能仍出现旧标题，方便人工审查。")
    document = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>商业热点审查</title><style>body{font-family:system-ui,-apple-system,sans-serif;color:#202b3b;max-width:1000px;margin:24px auto;padding:0 16px;line-height:1.6}h1{font-size:26px}h2{margin-top:36px;border-bottom:2px solid #dde4ef;padding-bottom:8px}h3{margin-top:26px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #dde4ef;padding:9px;text-align:left;vertical-align:top}th{background:#edf3fc}a{color:#1559ad;overflow-wrap:anywhere}.note,small{color:#647187;font-size:13px}td:first-child{min-width:58px}@media(max-width:600px){td,th{padding:6px;font-size:12px}}</style></head><body>' + ''.join(body) + '</body></html>'
    return "\n".join(text), document


def save_report(directory, name, report, plain, document):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / f"{name}.txt").write_text(plain, encoding="utf-8")
    (directory / f"{name}.html").write_text(document, encoding="utf-8")
