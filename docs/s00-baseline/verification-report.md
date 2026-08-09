# S00 自动验收报告

执行日期：2026-08-05（Asia/Shanghai）  
结论：**通过，停在 S00，等待确认**

## 范围

- 仅验证事实源、哈希清单、功能证据、旧格式可读性、协议说明和算法黄金样本。
- 数据库迁移、OpenAPI、前端、Tauri 和产品构建不属于 S00，因此本步骤的这些差异均为“无变化”。
- 历史资料不得产生内容或修改时间变化。

## 执行结果

### 1. 基线生成

```powershell
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  'C:\Users\Hust\Desktop\地质局项目\docs\s00-baseline\tools\generate_s00.py'
```

- 退出码：`0`
- 状态：`S00_GENERATION_OK`
- 总耗时：14.666 秒；第一遍全量哈希 5.513 秒。
- 受控资料：767 个文件，2,334,721,143 字节。
- 旧格式清单：81 个文件，覆盖 `acq/cdt/cfg/cmt/dat/edt/mdb/mtd/opt/pdt/sam/wdt` 12 种格式。
- Access 只读探针：8 个；全部通过临时副本读取。
- 核心黄金文件：4 个（3 份算法 JSON + 1 份真实格式探针）。

### 2. 独立复核

```powershell
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  'C:\Users\Hust\Desktop\地质局项目\docs\s00-baseline\tools\verify_s00.py'
```

- 退出码：`0`
- 状态：`S00_VERIFICATION_OK`
- 总耗时：4.794 秒；第二遍全量哈希 4.402 秒。
- 767 个受控文件的路径、大小、UTC 修改时间和 SHA-256 全部与第一遍一致。
- 功能证据：F0–F15 共 16 项，主证据均非空。
- 验收归档：独立核对 `docs/acceptance-reports/S00/验收报告.md`，其状态、机器结论和执行时的 `PLAN.md` SHA-256 快照均已记录。
- Access：8 个探针通过，BLOB 形状/长度校验 9 项通过。
- `DIRECT.MTD`：`MTD_PRIM=3`、`LINES=20`、`WSTC=5`、`USER=0`。
- `.cdt` 样本：`CCD_BAND=120`，首条 `CcdAvgs=40,960` 字节，符合 `5×2048×float32`。
- `.cmt` 样本：`CCD_BAND=120`，首条 `BurnAdcs=307,200`、`DarkAdcs=102,400` 字节。
- `.edt/.wdt`：各 120 条，首条 `BurnAdcs=368,640`、`DarkAdcs=102,400` 字节。
- `.pdt` 完整消费，矩阵为 10 条谱线 × 120 个重复谱带；`.dat` 完整消费，矩阵为 3 条结果线 × 90 个样品。
- `.acq` 为 24,579 字节、3 个有效帧头，5 个安装 CCD 的镜像/非镜像映射均生成哈希。
- `测试15-5-960.sam` 实际为 800 行，按重复数展开 960 个谱带；验证器同时断言两者。
- `SpecFile/03_方法与数据库/DIRECT.MTD` 的 `Stds` 为 224 字节；`分时样品.mdb` 与 `蒸发色散.mdb` 均为空模板，后者额外包含 `POINT_WAVE` 表。

### 3. 静态检查

```powershell
python -m py_compile docs\s00-baseline\tools\generate_s00.py `
  docs\s00-baseline\tools\verify_s00.py
```

- 退出码：`0`
- `app/` 目录仍不存在，符合 S00“不创建产品骨架”的范围。
- Python 缓存只作为检查临时产物，检查后清理，不纳入交付。

## 变化与不适用项

- 数据库迁移：无。
- OpenAPI 差异：无。
- 前端/Tauri 构建：无；S00 不创建产品工程。
- SQLite 完整性检查：不适用；尚无 SQLite 数据库。
- 产品覆盖率：不适用；本步骤无领域、适配器或 API 产品代码。验证脚本覆盖了 S00 的全部机器验收条件，不以跳过项掩盖失败。
- 截图：不适用；本步骤交付 CSV/JSON/Markdown 和哈希证据，不交付 UI。

## 发现并锁定的事实

- `.cdt CcdAvgs` 是 little-endian `float32`，不是格式文档所写的每点 2 字节。
- `SampName` 有 8/10 字符 schema 变体；不能使用全局固定宽度。
- 标准点 `Stds` BLOB 有 16 点（224 字节）和 50 点（700 字节）变体。
- `SpecFile/` 当前只保留 77 个可回溯 `Spec Source/` 的分类副本，文件直接位于 11 个类别目录根部；来源清单与副本哈希全部一致。
- “960” SAM 是 800 个源记录、960 个展开谱带。
- 旧高斯算法返回峰高，不计算峰面积。
- 旧版没有独立基线谱线、完整角色权限、汞灯流程、PDF 预览导出或关键波段优先闭环。
- `Spec Source/Bin` 中存在 `.qct/.qct_` 遗留资料：表结构与 `.edt/.wdt` 同构，但旧源码未将其列入正式文件类型；在取得运行证据前不纳入兼容承诺。

## 已知风险

详见 `risks-and-decisions.md`。其中设备命令协议、真实硬件在环、算法旧 EXE 第二判据、代码签名证书仍未关闭；这些不阻塞 S00，也不能被模拟结果替代为正式发布证据。

## S00 结论

S00 的五项验收口径全部满足：受控资料均有哈希、F0–F15 均有有效来源、12 种旧格式均有可读探针、算法输入输出黄金样本已冻结、历史原件在双遍校验中内容与修改时间不变。

按 `PLAN.md` 的逐步确认规则，当前必须停止并等待明确确认，不能进入 S01。

## 后续状态更新（2026-08-05）

- 根目录 `PLAN.md` 已补齐原截断内容，并将正式确认点收敛为完整 S00–S21及第 7–11 章；原截断风险 `R-S00-001` 已关闭。
- `SpecFile/` 已按 11 类整理并仅保留 77 个 `Spec Source/` 副本；整理前自带的 6 个文件已移除，相关路径、证据描述和 Access 探针已切换到现有文件。
- `PLAN.md` 已增加逐步骤验收报告门禁；`docs/acceptance-reports/` 负责 S00–S21 的简要报告和状态索引，关键证据按需保存。S00 已完成补录并纳入机器复核，报告中的计划哈希作为执行快照保留；计划仍保持 S00–S21 的收敛结构。
