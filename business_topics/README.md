# 商业热点选题扩展：部署与验收

截至 2026-10-13：本地与 GitHub Actions 的真实抓取、历史写回、跨运行器恢复和 Gmail 邮件送达均已测试。日报新增各热榜前10条、各RSS最新5条的原始列表及完整筛选说明；修正前的跨日重复推荐问题记录在下方。用户选择 Gmail；地址、SMTP 参数和应用专用密码均存于仓库 Secrets。

## 架构与费用

- 上游 TrendRadar v6.10.0（GPL-3.0）保持核心代码原样；热榜、RSS、关键词和禁用 AI 均通过官方配置。独立 `business_topics` 扩展完成事件聚合、100 分评分、事实核查门槛、选题卡和通知。
- 公共 GitHub 仓库、标准 GitHub 托管运行器；每小时第 33 分钟抓取，北京时间 10:00 加跑每日简报。GitHub 的定时触发允许延迟，10:33 的正常运行可补发尚未发送的简报。**官方“Check In”工作流原样保留**，须每 7 天内手动运行一次。
- 数据保存在同一仓库的公开 `business-history` 分支：每天的原始新闻及 RSS SQLite、完整的 `business/events.db` 和最新 JSON/HTML/文本报告。`business/reviews/日期.*` 保留当天最新审查快照，`business/digests/日期.*` 保留实际已发送的日报；`event_notifications` 记录各事件已推荐的事实快照。无 R2、付费 AI 或付费视频服务。仓库体积会增长，需定期查看大小。GitHub Actions 的免费规则以官方现行政策为准。
- GitHub Actions 无法主动向当前 Codex 对话发送消息。用户已选择电子邮件；Gmail 地址、`smtp.gmail.com`、SSL 465 端口和应用专用密码已存入 GitHub Secrets，**测试邮件已获用户确认送达**。参见 [Google 应用专用密码说明](https://support.google.com/accounts/answer/185833?hl=en) 和 [SMTP 设置](https://support.google.com/a/answer/176600?hl=en)。
- 公开历史分支只应包含公开新闻标题、链接和派生评分，绝不放私人备注、密钥或版权正文。

## 当前筛选与评分口径

先按六类中英关键词组合发现企业事件，排除普通行情和纯娱乐标题，再聚合同一事件。100 分由热度 25、知识解释价值 30、可视化潜力 20、新颖性 15、证据质量 10 组成。热度使用热榜排名、跨来源数和重复抓取次数；其余维度使用已识别企业、事件类型、标题中的可视化线索、同企业同主题既有事件数和来源数等规则代理。**评分是选题排序工具，不代表人工判断；系统没有真实阅读量、播放量或增长速度，也没有自动核查新闻正文。**

日报只收录企业可识别、证据分至少 5 分、得分至少 65 分且不处于事实核查中的事件，最多 5 条。新增推荐使用48小时内发布时间或首次发现时间；抓取到旧RSS文章不能使它重新成为新增事件。80 分及以上标为优先推荐。召回、品牌危机、财务及法律指控，以及并购否认、传闻与未证实爆料，需要人工核查；即时提醒还要求至少两个预设可信来源，或有人工核查记录。提价报道未人工核查前不发即时提醒。

各平台原始列表在商业筛选之前展示：热榜按本次抓取的实际榜位取前10，RSS按本次返回文章的发布时间取最新5条，并标注“非热榜”。列表逐条显示原始标题、链接、时间及入选/排除/待核查/已推荐说明。失败来源不以旧榜单填充，未接入媒体亦明确列出。最终推荐之外还展示全部匹配事件及未入选理由，方便人工发现漏选。

事件去重独立于每日邮件去重。持续在榜、反复出现在RSS、增加转载来源和分数波动都不算重大进展；只有可靠来源的新标题出现明确批准/完成/终止等阶段变化、强相似标题中的关键数值变化，或新增人工核查记录时，才允许再推荐。免费规则只识别有限的标题变化，不能代替完整的事实核查。`sent_digest_seed.json` 依据历史送达记录和真实已发报告回填10月12、13日的事件基线，不会据此发送邮件。

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

[上线后回归测试](https://github.com/zhongzz616/trendradar-business-topics/actions/runs/38060749947)再次成功：当次库中共 303 条原始记录、规则命中 6 条、聚合 5 个事件，达美航空卡片更新为 66 分和修正后的标题，历史库的当日简报发送记录仍只有 **1 条**，没有重复发送。

北京时间 2026-10-11 03:29 和 06:54 的两次 [自动运行之一](https://github.com/zhongzz616/trendradar-business-topics/actions/runs/38093088059)均成功。最新一次抓取 8 个热榜来源成功、36氪两个 NewsNow 接口仍为 HTTP 500，4 个 RSS 成功；在今天与昨天的库中共有 626 条原始记录，规则匹配 11 条，聚合 5 个事件；`new_articles=0`，说明没有把已保存文章重复入库。远端 `business/events.db` 的 `PRAGMA quick_check=ok`，当日简报发送记录未重复。GitHub 定时任务发生过明显延迟或遗漏，不能把每小时第 33 分钟视为严格服务等级保证。

2026-10-11 的 [10:08 定时简报](https://github.com/zhongzz616/trendradar-business-topics/actions/runs/38104134915)只发出 1 条达美航空选题；本次原生抓取新增 106 条热榜、30 条 RSS，但两日库中 762 条原始记录仅有 11 条命中规则。复核发现规则漏掉了 Cloudflare 收购 Deno 和半导体设备零部件提价，属于过滤过严。已增加动态英文并购和关键设备提价规则，补充对应的选题标题及防止同一提价事件跨平台重复建档的判定。在 10:08 保存的真实数据库副本上离线回放后，匹配记录为 15 条、聚合 7 个事件、每日候选 3 个（阿斯麦、Cloudflare、达美航空）；阿斯麦两条报道归入同一事件，未产生重要提醒。Cloudflare 收购亦有 [Cloudflare 官方说明](https://blog.cloudflare.com/deno-joins-cloudflare/) 与 [Deno 官方说明](https://deno.com/blog/cloudflare/)；阿斯麦提价仍只有媒体报道，立即提醒需要额外核查。当天简报已发送并记录去重，不会因规则修正再自动重复发送。

修正部署后的 [12:56 云端实测](https://github.com/zhongzz616/trendradar-business-topics/actions/runs/38113085444)成功：两日原始记录 844 条、规则匹配 15 条、新入库文章 3 条、聚合事件 7 个；候选为阿斯麦 90 分、Cloudflare 68 分、达美航空 66 分。阿斯麦的两篇报道聚合成一个事件，重要提醒为 0；远端事件库 `PRAGMA quick_check=ok`，当天简报送达记录仍只有 1 条。此次 8 个原生热榜来源成功，36氪两个接口继续 HTTP 500；4 个 RSS 中 3 个成功，界面新闻本次网络连接失败（之前运行曾成功）。

## 查询和事实核查

```bash
uv run python business_topics/search.py Tesla
uv run python business_topics/search.py --theme 企业经营 --min-score 65
```

敏感事件默认拦在“事实核查中”。人工检查原始披露或可靠交叉来源后，可用 `business_topics/verify.py` 为事件记录核查说明和链接；该记录必须同步到历史分支，下一次运行才会沿用。未经核查的危机、财务争议和法律指控不能自动变成确定性结论。

## 2026-10-13 重复日报修正与人工审查

10月12日14:27和13日11:48的已发日报共有4个重复选题（阿斯麦、Cloudflare、东百集团、分众传媒）。此前仅保存每日邮件发送键，未保存事件推荐基线；旧报道重复抓取又使事件保持活跃，造成跨日重复。现增加事件级事实快照和历史送达迁移，同时修复处理昨天数据库时覆盖今天文章时间/标题/榜位的问题。标题“星巴克否认收购Chipotle”已进入事实核查，使用否认传闻的模板，不再套用普通并购标题。

在13日11:48真实数据库副本回放中，展示8个成功热榜来源各10条和4个RSS各5条，共100条原始标题；36氪两个热榜接口失败，明确显示。4个仍达到分数门槛的旧选题被标记为“已推荐·无实质进展”。动态识别补充支持英文“to acquire”，IonQ收购报道成为新增候选；不为数量不足补入旧选题。规则回归测试覆盖重复抓取、相同事实转载、明确阶段/金额变化、陈旧RSS、并购否认、真实榜位快照、HTML邮件和每日报告归档。

手动运行 `Get Hot News` 的 `review_supplement=true` 可发送当日完整审查补充，使用独立送达键，最多发送一次；正常日报仍沿用北京时间10:00及延迟补发逻辑。

## 已完成的上线步骤与日常维护

1. 官方模板仓库 `zhongzz616/trendradar-business-topics` 和 `business-history` 分支已建立；手动工作流已通过抓取、恢复、去重、写回和 Gmail 送达验收。应用专用密码仅在 GitHub Secret 中，未提交到仓库。
2. `crawler.yml` 已启用两条 cron；两次自动监测已成功。继续在 Actions 页面观察长期运行与北京时间 10:00 简报。定时触发可能延迟或跳过，不能保证严格准点。
3. 每周进入仓库 `Actions → Check In → Run workflow` 手动续期。最好在第 6 天前操作；过期导致工作流停用时，可能还须在 Actions 页面重新启用 `Get Hot News`。

GitHub Actions [标准公开仓库计费规则](https://docs.github.com/en/billing/concepts/product-billing/github-actions)；[定时任务延迟和 60 天无活动规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)。
