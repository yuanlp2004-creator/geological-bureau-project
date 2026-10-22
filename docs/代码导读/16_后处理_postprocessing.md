# 后处理模块导读（`postprocessing`）

## 1. 模块定位

本模块处理已有数据，而不驱动设备。主要能力是：查看 EDT 原始帧区间、把旧 EDT 选择转换成新版采集记录、按指定方法和曲线重新计算，以及导出原始强度、处理后强度或结果矩阵。

## 2. 代码入口

- 服务：[`modules/postprocessing/service.py`](../../app/backend/modules/postprocessing/service.py)
- 分析算法复用：[`modules/analysis/`](../../app/backend/modules/analysis/)
- API：[`api/postprocessing.py`](../../app/backend/api/postprocessing.py)；`/api/v1/postprocessing`
- 请求模型：[`schemas/postprocessing.py`](../../app/backend/schemas/postprocessing.py)。
- 前端：`App.tsx` 中的 `PostProcessingPage`
- 测试：[`tests/test_s18_postprocessing.py`](../../app/tests/test_s18_postprocessing.py)

## 3. 统一来源标识

`_id()` 和 `_split()` 把旧 EDT、转换结果和采集样品编码成不透明记录标识。`edt_records()` 列出可处理来源，`_raw()` 解析标识并读取对应记录。

`_raw_frames()` 解包并校验原始 uint16 帧；`interval()` 只返回选定阶段、CCD 和帧区间。区间端点使用什么基准以 API 返回为准，修改前要同时检查前端控件和测试边界。

## 4. EDT 转换

`convert_edt()` 的主线是：

1. 固定源记录和选择条件的输入哈希。
2. 校验目标 CCD 布局、源点数和选定 CCD。
3. 抽取所选帧并按采集模块口径计算平均谱。
4. 创建新版采集任务、样品和波段记录。
5. 保存转换记录及源到目标关系。

相同输入哈希应保持幂等。转换生成的是新版数据副本，不修改旧迁移记录。

## 5. 重新计算

`recalculation_options()` 汇总可选数据、方法版本、计算配置和曲线快照。`recalculate()` 固定这些版本后批量计算：

- 旧结果可通过 `_match_source_line()` 对齐目标谱线。
- `_legacy_net()` 和 `_recalculate_legacy_result()` 保留旧版净强度口径。
- 新版采集数据复用分析模块的曲线求值规则。
- 任一核心样品失败时，批次事务应回滚，避免只留下半批结果。

读取重算结果时，应以记录中固定的 `method_version_id`、计算配置和曲线快照为准，而不是当前活动版本。

## 6. 导出

`_rows_for_export()` 支持 `raw_intensity`、`processed_intensity` 和 `result_matrix` 三类表格。`_encode()` 编码 TXT、CSV 或 Excel 内容；`_atomic_write()` 先写临时文件再原子替换，并执行覆盖、重命名或报错策略。

导出记录保存目标路径、格式、内容哈希和输入选择。失败时不应留下伪装成完整文件的半成品。

## 7. 推荐阅读顺序

`_id()` / `_split()` → `edt_records()` → `_raw_frames()` → `interval()` → `convert_edt()` → `recalculation_options()` → `recalculate()` → `_rows_for_export()` → `_atomic_write()` → `export()`。

## 8. 修改检查

- 旧记录是否始终只读，转换是否保存源输入哈希。
- 帧区间、CCD 选择和目标布局的点数是否严格校验。
- 重算是否固定方法版本、计算配置和曲线快照。
- 批量失败是否完整回滚，而不是留下部分业务结果。
- 三类导出内容、扩展名和 MIME 类型是否匹配。
- 同名策略和原子写是否避免覆盖意外文件。
- 运行 S18 测试，并回归前端两个后处理视图。

## 实现分工

`service.py`提供公开入口，`repository.py`查询并编解码记录，`conversion.py`负责EDT转换及转换工作单元，`recalculation.py`编排固定版本重算，`exporting.py`负责矩阵、格式编码及原子文件替换，`legacy_calculation.py`执行解码后的旧PDT纯计算。

转换记录、采集导入与审计使用同一连接和事务。重算先提交分析任务，再登记后处理结果，最终审计失败可能留下已完成分析任务，不能按整体事务理解。导出先写文件再登记数据库，文件与数据库也不构成整体事务。

## 当前入口（2026-10-18）

数据处理显示“重新计算”和“打印与导出”，输出仅有分析报告、强度数据两个页签。`AnalysisIntensityOutput` 从已完成新版分析读取候选批次并复用 `IntensityOutput`，使用既有 analysis.read/print/execute 权限；输出期间锁定批次。独立旧PDT强度表卡片已移除；旧结果先通过迁移模块导入，重算及已迁移结果通过统一折叠区访问，`PostProcessingPage` 不再提供逐帧原始/平均导出选项；旧记录区间查看与EDT转换作为重算辅助工具保留。`FullTimeOutput` 和分析谱图中的全时导出动作已移除，采集全区间保存和谱线曝光区间未改。旧后端API保留兼容，无数据删除或schema改变。报告只读用户不会请求无权读取的分析批次。两入口共用工作区实例，切换保留输入。
