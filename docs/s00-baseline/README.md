# S00 事实与黄金样本基线

本目录是 `PLAN.md` 的 S00 交付物，只锁定事实、兼容口径和黄金样本，不包含 `app/` 工程骨架、数据库迁移、API、React 或 Tauri 产品代码。S00 工具以只读方式使用 `Spec Source/`、`Spec2.02/`、`SpecFile/` 和 `Spec2.02功能研究/` 中的数据资料；`SpecFile/` 是包含 77 个 `Spec Source/` 分类副本的参考集合，所有副本均通过来源清单回溯原件。

## 交付内容

- `evidence-ledger.csv`：F0–F15 的逐项证据账、状态、缺口和依赖步骤。
- `formats-and-protocols.md`：ACQ、Access、PDT、DAT、SAM、CFG/OPT 的已锁定格式说明及冲突。
- `golden-samples.md` 与 `golden/*.json`：旧版高斯、曲线拟合、暗扣除、寻峰、内标、RSD/ID 及真实文件解析黄金向量。
- `generated/controlled-files.csv`：所有受控事实源的大小、UTC 修改时间和 SHA-256。
- `generated/legacy-files.csv`：旧格式文件清单和被选作解析探针的样本。
- `generated/access-probes/*.json`：从临时副本以 Jet `Mode=Read` 读取的表结构、行数、首行和 BLOB 探针。
- `risks-and-decisions.md`：冲突、发布阻塞项和后续步骤约束。
- `verification-report.md`：自动校验命令、退出码、性能和结论。

S00 的正式步骤验收结论单独记录在 [`docs/acceptance-reports/S00/验收报告.md`](../acceptance-reports/S00/验收报告.md)。本目录中的 `verification-report.md` 是机器校验明细和证据输入，不能替代正式验收报告。

`SpecFile/` 的目录说明和逐文件来源见根级 `SpecFile/README.md`、`SpecFile/文件来源清单.csv`。S00 从分类资料中选用 `DIRECT.MTD` 核对旧 16 点标准值布局，并用 `分时样品.mdb`、`蒸发色散.mdb` 核对两类空模板。

## 再生成与校验

使用工作区自带 Python：

```powershell
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  'C:\Users\Hust\Desktop\地质局项目\docs\s00-baseline\tools\generate_s00.py'

& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  'C:\Users\Hust\Desktop\地质局项目\docs\s00-baseline\tools\verify_s00.py'
```

生成器会对受控资料做第一遍哈希，验证器重新计算全部哈希并核对修改时间。Access 探针先复制样本到系统临时目录，再调用 32 位 PowerShell + Jet OLEDB 4.0 读取，因此不会在历史目录创建 `.ldb` 锁文件。

验证器还会检查 S00 正式验收报告是否存在、验收状态是否通过，以及是否记录了执行时的 `PLAN.md` SHA-256。该哈希用于标识验收所依据的计划快照；后续调整计划不要求改写已经形成的 S00 报告。

## 边界

- `UI测试/` 未纳入事实源，也未读取或修改；唯一视觉输入是根级 `docs/ui-test-homepage-reference.png`。
- S00 的算法黄金值按 Delphi 源码逐式推导，已足以约束移植；仍登记了与旧版可执行程序输出做第二判据的后续风险。
- S00 必须同时具备通过的机器校验和正式验收报告；完成后等待明确确认，不能自动进入 S01。
