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

## 2026-09-14 结构更新

`postprocessing/` 的 `service.py` 保留公开调用入口；`repository.py` 负责来源查询、区间读取与记录编解码；`conversion.py` 负责 EDT 转换与事务协调；`recalculation.py` 负责固定版本重算；`exporting.py` 负责矩阵构建、格式编码和原子替换；`serialization.py`、`errors.py` 保存共用序列化与错误类型。小文件整理后，原 codec.py 的两个函数已收回 repository.py，原 conversion_uow.py 的事务类型已收回 conversion.py。

转换的业务写入与审计仍在同一事务。导出保持先写文件、再登记数据库的原顺序，不提供文件与数据库之间的整体事务。文件替换失败时，已有文件保留且临时文件清理；对应失败注入测试已通过。

## 2026-09-14 内部解耦更新

Runtime 向后处理传入方法服务、分析契约实现和采集导入能力。重算全程使用同一个分析对象，方法查询通过公开快照，选项列表批量获取版本信息。`conversion.py` 中的 ConversionUnitOfWork 将转换存储与采集导入绑定同一连接；`acquisition_import.py` 负责采集表及帧记录写入，不能独立提交。中途谱带/审计失败整体回滚。

`recalculation.py` 保留格式/档案检查、JSON/BLOB 解码和流程编排，`legacy_calculation.py` 使用 `LegacyIntensity`、方法谱线及曲线参数做纯数值计算。重算与 EDT 转换的事务语义不同：重算先提交分析任务，再登记后处理结果；最终审计失败会留下已完成的分析任务，不能把它当作整体事务。
