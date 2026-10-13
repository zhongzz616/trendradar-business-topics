"""Regression fixtures are synthetic; deployment acceptance uses real SQLite snapshots."""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from business_topics import engine, history
from business_topics.review import collect_sources, render_report, save_report
from business_topics.selection import NOTICE_SCHEMA, record_recommendation, recommendation_state


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        engine.ensure_schema(self.c)
        self.c.executescript(NOTICE_SCHEMA)
        self.now = datetime(2026, 10, 13, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.yesterday = self.now - timedelta(days=1)
        title = "TESTCorp acquisition for $10 million"
        self.c.execute("INSERT INTO events(id,company,industry,theme,headline,first_found,last_updated) VALUES(1,'TESTCorp','测试行业','战略决策',?,?,?)",
                       (title, self.yesterday.strftime("%Y-%m-%d %H:%M:%S"), self.now.strftime("%Y-%m-%d %H:%M:%S")))
        self.add_article("one", title, self.yesterday)
        self.info = {"事件状态": "每日候选"}

    def tearDown(self):
        self.c.close()

    def add_article(self, key, title, when, published=None):
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")
        self.c.execute("""INSERT INTO articles(article_key,event_id,title,source_id,source_name,url,
                          published_at,first_found,last_seen,sightings) VALUES(?,1,?,'techcrunch','TEST source',?,?,?, ?,1)""",
                       (key,title,"https://example.org/"+key,published,stamp,stamp))

    def state(self):
        event = self.c.execute("SELECT * FROM events WHERE id=1").fetchone()
        return recommendation_state(self.c,event,self.info,self.now,engine.SOURCE_WEIGHT)

    def notified(self):
        record_recommendation(self.c,"daily:2026-10-12",1,self.yesterday)

    def test_repeated_crawling_and_score_do_not_make_progress(self):
        self.notified()
        self.c.execute("UPDATE articles SET sightings=100,last_seen=?",(self.now.strftime("%Y-%m-%d %H:%M:%S"),))
        self.assertEqual(self.state()[1],"已推荐·无实质进展")

    def test_extra_source_same_facts_does_not_make_progress(self):
        self.notified()
        self.add_article("two","TESTCorp announces acquisition for $10 million",self.now)
        self.assertFalse(self.state()[0])

    def test_approval_is_material_progress(self):
        self.notified()
        self.add_article("two","TESTCorp acquisition for $10 million approved",self.now)
        self.assertEqual(self.state()[1],"重大进展")

    def test_changed_amount_is_material_progress(self):
        self.notified()
        self.add_article("two","TESTCorp acquisition for $20 million",self.now)
        self.assertEqual(self.state()[1],"重大进展")

    def test_old_rss_is_not_new_because_first_seen_today(self):
        self.c.execute("UPDATE articles SET published_at='2020-01-01T00:00:00',first_found=?",(self.now.strftime("%Y-%m-%d %H:%M:%S"),))
        self.assertEqual(self.state()[1],"历史观察")

    def test_denial_is_not_a_completed_acquisition(self):
        self.assertEqual(engine.action_bucket("星巴克否认收购Chipotle"),"并购否认")
        event=dict(self.c.execute("SELECT * FROM events WHERE id=1").fetchone())
        event["headline"]="TESTCorp denies acquiring Example"
        articles=[dict(self.c.execute("SELECT * FROM articles").fetchone())]
        articles[0]["title"]=event["headline"]
        self.assertEqual(engine.score_event(event,articles,0)[3],"事实核查中")


class ReviewTests(unittest.TestCase):
    def test_exact_snapshot_and_failed_source_without_stale_rows(self):
        with tempfile.TemporaryDirectory() as d:
            data=Path(d);(data/"news").mkdir()
            now=datetime(2026,10,13,10,tzinfo=engine.TZ)
            with sqlite3.connect(data/"news/2026-10-13.db") as c:
                c.executescript((engine.ROOT/"trendradar/storage/schema.sql").read_text())
                c.execute("INSERT INTO crawl_records(id,crawl_time) VALUES(1,'08-00'),(2,'10-00')")
                c.execute("INSERT INTO crawl_source_status VALUES(2,'weibo','success'),(2,'36kr-quick','failed')")
                for i in range(1,13):
                    c.execute("INSERT INTO news_items(id,title,platform_id,rank,url,first_crawl_time,last_crawl_time) VALUES(?,?,'weibo',?,?,'08-00','10-00')",
                              (i,f'TEST title {i}',i,f'https://example.org/{i}'))
                    c.execute("INSERT INTO rank_history(news_item_id,rank,crawl_time) VALUES(?,?,'10-00')",(i,13-i))
                c.execute("INSERT INTO news_items(title,platform_id,rank,url,first_crawl_time,last_crawl_time) VALUES('TEST stale','36kr-quick',1,'https://example.org/stale','08-00','08-00')")
            sources=collect_sources(data,engine.ROOT,now,lambda *args:{"decision":"测试未筛选","decision_reason":"fixture"})
            weibo=next(s for s in sources if s.get('id')=='weibo')
            self.assertEqual([x['rank'] for x in weibo['items']],list(range(1,11)))
            self.assertEqual(weibo['items'][0]['title'],'TEST title 12')
            self.assertFalse(next(s for s in sources if s.get('id')=='36kr-quick')['items'])

    def test_email_contains_full_html_review(self):
        with patch.dict(os.environ,{"EMAIL_FROM":"test@example.org","EMAIL_TO":"test@example.org",
                                   "EMAIL_PASSWORD":"test-only","EMAIL_SMTP_SERVER":"smtp.example.org",
                                   "EMAIL_SMTP_PORT":"465","FEISHU_WEBHOOK_URL":"","NTFY_TOPIC":""}), patch.object(engine,"SMTP_SSL") as smtp:
            self.assertEqual(engine.send_notification("TEST review","plain review","<html>full review</html>"),("email",True))
            message=smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(message.get_body(preferencelist=('html',)).get_content().strip(),"<html>full review</html>")

    def test_html_escapes_titles_and_history_keeps_daily_files(self):
        report={"generated_at":"2026-10-13T10:00:00+08:00","daily_candidates":[],"event_decisions":[],
                "platform_lists":[{"name":"TEST","kind":"热榜前10","status":"成功","snapshot_at":"test",
                   "reason":"fixture","items":[{"title":"<script>TEST</script>","url":"javascript:bad",
                    "rank":1,"decision":"保留","decision_reason":"fixture"}]}]}
        plain,document=render_report(report)
        self.assertNotIn('<script>',document)
        self.assertNotIn('href="javascript:',document)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'output';target=Path(d)/'history'
            save_report(out/'business/reviews','2026-10-13',report,plain,document)
            save_report(out/'business/digests','2026-10-13',report,plain,document)
            with patch.object(history,'OUTPUT',out):history.sync('save',target)
            self.assertTrue((target/'business/reviews/2026-10-13.html').exists())
            self.assertTrue((target/'business/digests/2026-10-13.json').exists())


if __name__=='__main__':unittest.main()
