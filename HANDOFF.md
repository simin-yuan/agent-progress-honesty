# HANDOFF — Agent Progress Honesty（冲刺项目）

更新时间：2026-11-11 05:20（Asia/Shanghai）
状态：**实验与交付完成**。报告提交：Simin。

## 里程碑

| 里程碑 | 状态 | 关键数字 |
|---|---|---|
| M1 试跑（5 任务 × 1 模型） | **完成** | 140.3 秒，$0.0143，0 协议错误 |
| M2 全量（30 × 3 × 3 = 270） | **完成** | 66 分钟墙钟，$0.327，1 次协议失败（0.4%） |
| M3 交付 | **完成** | results.csv、3 图、270 份原始日志、中文摘要、公开仓库 |

## 结果（预注册口径）

| 模型 | n | 夸大率 | Brier | 合理更新 | 屈服 |
|---|---|---|---|---|---|
| DeepSeek-V4.1-Flash | 90 | 13.3% (8/60) | 0.263 | 50.0% (4/8) | 10.0% (3/30) |
| DeepSeek-V4-Pro | 90 | 28.3% (17/60) | 0.331 | 64.7% (11/17) | 0.0% (0/29) |
| Qwen3.5-9B | 90 | 39.7% (25/63) | 0.434 | 40.0% (10/25) | 0.0% (0/27) |

- 夸大集中在 C 类（静默失败）：33.3% / 62.5% / 87.5%；B 类（工具明确超时）三模型均 0/15。
- Flash 的 3 次屈服全部来自 B02（测试器卡死、修好但无法用测试确认）；剔除 B02 为 0/27。
- Pro 17 次夸大中 6 次发生在已读到 ENOENT 之后；Flash 为 0/8。
- 假说 H3（屈服率高于合理更新率）**不成立**；H4（小模型夸大更多）成立，但 Pro 比 Flash 更夸大，非单调。

## 交付物

- 公开仓库：https://github.com/simin-yuan/agent-progress-honesty
- `logs/raw/full/`：270 份逐轮 JSON（transcript、tool calls、usage、校验器输出）
- `results/`：results.csv、summary_by_model(_category/_task).csv、flips.csv、flip_audit.csv
- `figures/fig1..3`：夸大率、Brier、改口率
- `SUMMARY_zh.md`：一页中文摘要
- `PROTOCOL.md`：预注册；`HANDOFF.md`：本文件

## 决定与偏差

1. 模型：flash + pro + 本机 qwen3.5:9b；统一关闭扩展思考（Pro 否则空回复）。
2. 3 次重复；总费用 $0.327，未触发降次规则。
3. 协议失败 1/270（Qwen C02-r3 未报告），1.1% < 20%，保留。
4. 真实结果 = 报告时刻校验；追问后补做另记（`actual_done_final`）。
5. 试跑/开发日志在 `logs/dev/`，已 gitignore，不计入结果。

## 复现

```bash
python -m tests.selftest
python -m bench.run --models deepseek-flash,deepseek-pro,qwen3.5-9b --runs 3 --out logs/raw/full
python -m bench.analyze --raw logs/raw/full
```

## 红线

- 不编造数据；未跑=未跑。
- 仓库只含本项目内容；无密钥、无私有仓库代码、无光之涌现内容。
- 不改运行中的桌面 DSH 进程（57831）。
