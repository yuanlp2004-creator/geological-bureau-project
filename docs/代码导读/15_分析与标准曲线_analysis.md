# 分析与标准曲线模块导读（`analysis`）

## 1. 模块定位

本模块把采集波段转换为谱线强度，处理慢速人工检查、重复样质量判定、标准曲线拟合、曲线发布和最终浓度合并。它同时保留 `legacy_2_0_2` 与 `modern_v1` 两种计算口径。

这是业务规则最密集的模块。阅读时应把“原始强度分析”“质量判定”“曲线工作区”“发布曲线”“最终结果”分成五层，不要把一个页面操作误认为一次数据库更新。

## 2. 代码入口

- 公共入口：[`analysis/__init__.py`](../../app/backend/modules/analysis/__init__.py)，保留 AnalysisService、AnalysisError 和公开算法。
- 分析运行：[`analysis/service.py`](../../app/backend/modules/analysis/service.py)，创建、运行、慢进干预与取消；显式组合下面三个服务。
- 纯算法：[`analysis/algorithms.py`](../../app/backend/modules/analysis/algorithms.py)，不依赖数据库或 PDF。
- 质控：[`analysis/quality.py`](../../app/backend/modules/analysis/quality.py)；曲线调整/拟合/发布/合并：[`analysis/curves.py`](../../app/backend/modules/analysis/curves.py)。
- 曲线预览与 PDF：[`analysis/printing.py`](../../app/backend/modules/analysis/printing.py)。
- 共享数据库查询、结果装配与事务内审计辅助：[`analysis/repository.py`](../../app/backend/modules/analysis/repository.py)。所有对象共享同一 Database，完整写事务仍由对应业务方法持有。
- 错误与稳定 JSON/哈希：analysis/errors.py、analysis/serialization.py。
- API：[`api/analysis.py`](../../app/backend/api/analysis.py)；`/api/v1/analyses`
- 请求模型：[`schemas/analysis.py`](../../app/backend/schemas/analysis.py)。
- 前端：[`pages/analysis/AnalysisPage.tsx`](../../app/frontend/src/pages/analysis/AnalysisPage.tsx)
- 测试：[`tests/test_s16_analysis.py`](../../app/tests/test_s16_analysis.py)、[`tests/test_s17_quality_curves.py`](../../app/tests/test_s17_quality_curves.py)

## 3. 先读纯函数

- `repeat_statistics()`：计算均值、极差、标准差、RSD 等重复性指标。
- `legacy_gaussian()`：旧版高斯峰算法的兼容实现。
- `fit_curve()`：线性、二次、三次和样条等曲线拟合。
- `evaluate_curve()`：用拟合快照反算未知样浓度。
- `_float32()`、`_legacy_floor()`：旧版数值精度与下限口径。
- `_search_peak()`：在受限窗口内寻找峰位并返回诊断。

这些函数无数据库副作用，最适合先理解和单独测试。改动时要用数值样例证明结果，而不能只看类型检查通过。

## 4. 原始分析运行

`create_run()` 固定方法版本载荷哈希、采集样品和波段哈希、计算配置。`start()` 后，`step()` 按样品和谱线逐项推进：

1. 从波段取得搜索窗口。
2. 进行参考校正和峰值/高斯计算。
3. 应用无内标、背景内标或谱线内标规则。
4. 根据计算配置执行旧版 float32/下限口径或现代算法。
5. 写入逐谱线结果并推进位置。

慢速模式可生成检查点，等待 `intervene()` 接受、丢弃或调整位置。干预必须带理由，并与结果和审计关联。

## 5. 质量判定

`build_quality()` 按标准样、未知样、谱线和重复次序分组，调用 `repeat_statistics()` 生成质量快照。`decide_quality()` 可以接受、排除或恢复重复结果，然后生成新的不可变 QC 快照。

后续曲线只能引用明确的 QC 快照。质量决定发生变化时，应生成新快照，不应原地修改旧快照导致已发布曲线失去依据。

## 6. 标准曲线工作区

`_curve_workspace()` 从最新 QC 快照生成标准点工作区。`curve_action()` 记录启用/禁用点、坐标类型、拟合模式、点调整和恢复等动作。`fit_standard_curve()` 将当前工作区拟合为不可变曲线快照，并保存残差等诊断。

`publish_standard_curve()` 只允许发布满足条件、基于当前有效 QC 的曲线。`curve_evaluators()` 按方法版本和计算配置加载已发布曲线，供本模块和后处理共同使用。

## 7. 最终结果与输出

`merge_results()` 用发布曲线计算并合并最终元素结果，固定其曲线快照和 QC 依据。`curve_preview()` 和 `print_curve()` 从不可变曲线快照生成预览或 PDF，不重新读取可变工作区。

报告模块要求存在已合并的最终结果；仅完成原始强度分析还不能生成正式报告。

## 8. 推荐阅读顺序

纯函数 → `create_run()` → `_line_candidate()` → `step()` → `intervene()` → `_qc_groups()` → `build_quality()` → `curve_action()` → `fit_standard_curve()` → `publish_standard_curve()` → `merge_results()`。

## 9. 修改检查

- 运行是否固定方法、采集数据和计算配置的哈希证据。
- 旧版和现代计算配置是否明确分流，未发生混用。
- 慢速干预是否可追溯，并拒绝非法状态或过期检查点。
- QC、曲线和最终合并结果是否都是版本化快照。
- 曲线发布是否拒绝旧 QC、不可发布拟合和错误方法版本。
- 预览、打印、后处理和报告是否读取同一曲线快照。
- 运行 S16、S17 测试以及相关数值黄金样例。

## 2026-09-14 内部解耦更新

`Runtime.analysis_service()` 显式注入方法服务；分析服务与仓储通过 `bind_snapshots()` 在原连接读取固定版本，不直接查询方法表。创建运行要求已发布版本，运行读取使用已固定版本，不随最新草稿变化。后处理通过 `analysis/contracts.py` 的小型契约调用分析。几何换算仍使用方法服务的 `_layout`、`_dispersion`、`_reference_position`，属于本轮之外的剩余私有依赖。
