# 分步验收报告

| 步骤 | 状态 | 报告 |
|---|---|---|
| S00 | passed | [验收报告](S00/验收报告.md) |
| S01 | deferred_external | [验收报告](S01/验收报告.md) |
| S02 | passed | [验收报告](S02/验收报告.md) |
| S03 | passed | [验收报告](S03/验收报告.md) |
| S04 | passed | [验收报告](S04/验收报告.md) |
| S05 | passed | [验收报告](S05/验收报告.md) |
| S06 | passed | [验收报告](S06/验收报告.md) |
| S07 | passed | [验收报告](S07/验收报告.md) |
| S08 | passed | [验收报告](S08/验收报告.md) |
| S09 | passed | [验收报告](S09/验收报告.md) |
| S10 | passed | [验收报告](S10/验收报告.md) |
| S11 | passed | [验收报告](S11/验收报告.md) |
| S12 | passed | [验收报告](S12/验收报告.md) |
| S13 | passed | [验收报告](S13/验收报告.md) |
| S14 | deferred_external | [S14 验收报告](S14/验收报告.md) |
| S15 | deferred_external | [S15 验收报告](S15/验收报告.md) |
| S16 | passed | [S16 验收报告](S16/验收报告.md) |
| S17-S21 | not_started | 步骤完成后创建 |

状态值：`not_started`、`in_progress`、`passed`、`failed`、`deferred_external`。

## 2026-08-09 更正复验

S02、S08、S10 已针对权限与审计、真实 Access 大文件流式迁移、谱图交互与可见范围输出完成修正和复验，状态继续为 `passed`；详见各步骤报告的同日期更正记录。

## 2026-08-12 S11-S16 更正复验

S11-S16 已针对顺序 schema 迁移、色散帧压缩 BLOB、旧版 LowAvg/Single 数值口径、公开枚举、内置角色最小权限、S11 实时交互和运行时状态显示完成修正与复验。S11、S12、S13、S16 继续为 `passed`；S14、S15 的软件闭环通过，但真实转角/汞灯协议和硬件证据仍缺失，继续为 `deferred_external`。详见各步骤报告的同日期更正记录。
