# 跟进 TrendRadar 上游更新

本仓库由官方 **Use this template** 创建，保留了原项目的 `LICENSE`，但模板仓库与上游没有共享 Git 历史。当前本地克隆已添加 `upstream=https://github.com/sansan0/TrendRadar.git`；在其他电脑克隆时需重新添加此 remote。

检查官方更新：

```bash
git remote add upstream https://github.com/sansan0/TrendRadar.git  # 如果尚未存在
git fetch upstream
git diff --stat master upstream/master -- trendradar pyproject.toml uv.lock config .github/workflows
```

升级时先查看官方 README、版本说明和配置变更，再把核心包、依赖锁文件和必要的官方配置变更移入当前仓库。`business_topics/` 是独立扩展；`config/frequency_words.txt`、`config/config.yaml` 和 `.github/workflows/crawler.yml` 包含本系统的定制规则，不应直接用上游文件覆盖。升级后先手动触发一次工作流验证抓取、数据库恢复、通知和 7 天签到，再保留定时运行。
