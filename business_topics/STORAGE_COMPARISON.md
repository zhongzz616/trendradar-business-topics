# GitHub Actions 持久化比较（2026-10-10）

| 方案 | 费用与账号 | 与 TrendRadar 的关系 | 长期查询与风险 |
| --- | --- | --- | --- |
| Cloudflare R2 Standard | 每月 10 GB 存储、100 万次 A 类、1000 万次 B 类操作免费；开通要绑定支付方式，超额可能收费 | 官方原生 S3 后端，最少改动 | 每天一组 SQLite，适合长期历史；需监控用量并由用户完成计费资料 |
| GitHub 仓库独立 data 分支 | 标准公开仓库运行器免费，不另开计费账户 | 必须增加同步工作流，属二次开发 | 新闻元数据公开；SQLite 二进制频繁提交会膨胀，需按月归档并监控仓库大小；不宜直接承诺一年无维护 |
| GitHub Actions artifact/cache | 有免费额度 | 需要自定义上传下载 | artifact 有保留期，cache 可被回收；不适合唯一的长期历史库 |
| Mac 本地 SQLite | 无额外平台费用 | 原生支持 | Mac 关机时 Actions 无法读取它，不能作为全天候部署的唯一存储 |

当前实施选择：GitHub 仓库独立 `business-history` 分支。它符合“不启用付费服务”的约束；TrendRadar 仍使用原生本地 SQLite，工作流每次运行前恢复当天及前一天的原始库和完整事件库，运行后将它们提交到历史分支。旧日期的原始 SQLite 留在分支中，事件库汇总全文标题、来源链接、企业、主题、评分、状态与观察记录。仓库体积和 Git 历史会增长，需要定期检查；此方案不能保证 GitHub 永久免费或任务准点。

本机已对 2026-10-10 的新闻、RSS 和事件 SQLite 做备份与 `PRAGMA quick_check`，均通过。**远端推送、全新运行器恢复和 Actions 持久化仍需 GitHub 登录后验收**，验收前不启用长期调度。

来源：TrendRadar README 的“远程云存储 & 签到配置”和“数据保存在哪里？”；GitHub Actions 计费文档；Cloudflare R2 Pricing 文档。
