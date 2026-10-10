# 商业热点选题扩展：部署与验收

截至 2026-10-10：**本地与 GitHub Actions 的真实抓取、历史写回、跨运行器恢复和 Gmail 邮件送达均已测试；定时表达式已启用，首次自动触发仍待观察**。用户选择 Gmail，发件和收件均为其指定地址；地址、SMTP 参数和应用专用密码均存于仓库 Secrets。

## 架构与费用

- 上游 TrendRadar v6.10.0（GPL-3.0）保持核心代码原样；热榜、RSS、关键词和禁用 AI 均通过官方配置。独立 `business_topics` 扩展完成事件聚合、100 分评分、事实核查门槛、选题卡和通知。
- 公共 GitHub 仓库、标准 GitHub 托管运行器；每小时第 33 分钟抓取，北京时间 10:00 加跑每日简报。GitHub 的定时触发允许延迟，10:33 的正常运行可补发尚未发送的简报。**官方“Check In”工作流原样保留**，须每 7 天内手动运行一次。
- 数据保存在同一仓库的公开 `business-history` 分支：每天的原始新闻及 RSS SQLite、完整的 `business/events.db` 和最新 JSON 报告。无 R2、付费 AI 或付费视频服务。仓库体积会增长，需定期查看大小。GitHub Actions 的免费规则以官方现行政策为准。
- GitHub Actions 无法主动向当前 Codex 对话发送消息。用户已选择电子邮件；Gmail 地址、`smtp.gmail.com`、SSL 465 端口和应用专用密码已存入 GitHub Secrets，**测试邮件已获用户确认送达**。参见 [Google 应用专用密码说明](https://support.google.com/accounts/answer/185833?hl=en) 和 [SMTP 设置](https://support.google.com/a/answer/176600?hl=en)。
- 公开历史分支只应包含公开新闻标题、链接和派生评分，绝不放私人备注、密钥或版权正文。

## 数据源现状

| 来源 | 接入 | 本地验收 |
| --- | --- | --- |
| 今日头条、百度热搜、华尔街见闻、B站热搜、财联社热门、微博、抖音、知乎 | TrendRadar 原生 NewsNow 配置 | 8/8 成功 |
| 36氪快讯、人气榜 | TrendRadar 支持的 NewsNow ID | 2/2 返回 HTTP 500；保留配置等待上游恢复 |
| TechCrunch、The Verge、CNBC Business | 公开 RSS | 3/3 成功 |
| 界面新闻 | [官网列出的 RSS](https://www.jiemian.com/app/index.html) | 成功，30 条 |
| 36氪 RSS | [官网公布 feed 地址](https://www.36kr.com/rss-center) | 返回 HTML，0 条可解析；未强行采集 |
| Reuters | [Reuters Connect 的 RSS 需要认证](https://liaison.thomsonreuters.com/page/rss-feeds-tech-notes) | 未接入；优先从已接入媒体交叉发现事件 |
| Bloomberg | [媒体内容分发属授权服务](https://www.bloomberg.com/distribution/) | 未接入；不使用猜测地址 |
| Financial Times | [授权 RSS 需要 Feed Key](https://legal.ft.com/wp-content/uploads/2022/07/Republishing-Terms-26-Aug-2022.pdf) | 未接入；不使用付费授权 |
| 第一财经 | 未找到可验证的公开综合新闻 RSS | 未接入；后续可评估其官方公开接口或人工来源 |

## 2026-10-10 真实测试

TrendRadar 原生运行：热榜 8 个成功、2 个 36氪接口失败；4 个 RSS 成功。当前日数据库累计 **346 条热榜新闻、103 条 RSS 新闻**。最终关键词规则命中 8 条新闻，聚合为 7 个事件。最后一次原生增量抓取新增 10 条热榜及 30 条界面新闻 RSS，原生筛选为 0/10 和 1/30；扩展对整个当日库重新评分。没有通过核查且达到 65 分的每日候选，也没有 80 分的重要提醒，故不会凑够 3—5 条。

三个真实事件样例（仅供验收，不代表已核实全部事件细节）：

1. [Tesla 在欧洲更名驾驶辅助产品](https://techcrunch.com/2026/10/09/tesla-renames-full-self-driving-to-tesla-assisted-driving-in-europe/)：71/100，品牌定位和监管预期；第二来源为 [CNBC](https://www.cnbc.com/2026/10/09/tesla-full-self-driving-europe-regulator.html)。标题角度《为什么企业会给已有产品重新命名？》。状态：事实核查中，暂不推送。
2. [Delta Air Lines 下调预期](https://www.cnbc.com/2026/10/09/delta-air-lines-dal-q3-2026-earnings.html)：64/100，燃油成本、经营杠杆；标题角度《为什么成本上涨会迫使企业下调经营预期？》。未达 65 分，暂不推送。
3. [Anthropic 模型误报事件](https://techcrunch.com/2026/10/09/an-anthropic-ai-model-sent-a-false-homicide-tip-to-philadelphia-police/)：58/100，AI 产品责任与信任成本；因涉及争议且单一来源，事实核查中，暂不推送。

分数分别来自榜位、跨来源、重复出现、可解释的商业概念、可视化和来源质量。RSS 不提供真实播放量或阅读量，因此这些数值不是实际传播人数，也不能推出真实增长率。报道发布时间不当作事件发生时间；后者无法确认时记录“未确认”。

两次云端手动运行：[首次抓取](https://github.com/zhongzz616/trendradar-business-topics/actions/runs/38059266332)成功获取 193 条热榜与 90 条 RSS，扩展匹配 6 条、聚合 5 个事件，并向 `business-history` 提交新闻库、RSS 库、事件库和报告；[第二次恢复测试](https://github.com/zhongzz616/trendradar-business-topics/actions/runs/38059437281)从该分支恢复了三个数据库，新增 5 条热榜及 2 条 RSS，扩展 `new_articles=0`，再次成功写回。上述数字是云端当次结果，和此前多次本地抓取的累计库不同。

[真实邮件测试](https://github.com/zhongzz616/trendradar-business-topics/actions/runs/38060267884)显示 `channel=email, success=true`，用户确认收到。[正常通知测试](https://github.com/zhongzz616/trendradar-business-topics/actions/runs/38060420199)显示当次库中热榜与 RSS 共 293 条、关键词规则命中 6 条、聚合 5 个事件，历史库记录了 `daily:2026-10-10` 的邮件发送。云端最终每日候选为 **1 条达美航空经营预期选题（65 分）**，重要提醒为 0；数量不足 3 条时不凑数。实测中发现标题模板未识别“cuts 2026 forecast”，已修正规则；当天已发送的测试简报仍保留原文，后续运行使用修正后的标题《为什么成本上涨会迫使企业下调经营预期？》。

## 查询和事实核查

```bash
uv run python business_topics/search.py Tesla
uv run python business_topics/search.py --theme 企业经营 --min-score 65
```

敏感事件默认拦在“事实核查中”。人工检查原始披露或可靠交叉来源后，可用 `business_topics/verify.py` 为事件记录核查说明和链接；该记录必须同步到历史分支，下一次运行才会沿用。未经核查的危机、财务争议和法律指控不能自动变成确定性结论。

## 已完成的上线步骤与日常维护

1. 官方模板仓库 `zhongzz616/trendradar-business-topics` 和 `business-history` 分支已建立；手动工作流已通过抓取、恢复、去重、写回和 Gmail 送达验收。应用专用密码仅在 GitHub Secret 中，未提交到仓库。
2. `crawler.yml` 已启用两条 cron；应查看 Actions 页面确认下一次实际定时触发。定时触发可能延迟或跳过，不能保证严格准点。
3. 每周进入仓库 `Actions → Check In → Run workflow` 手动续期。最好在第 6 天前操作；过期导致工作流停用时，可能还须在 Actions 页面重新启用 `Get Hot News`。

GitHub Actions [标准公开仓库计费规则](https://docs.github.com/en/billing/concepts/product-billing/github-actions)；[定时任务延迟和 60 天无活动规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)。
