# 光谱查看模块导读（`spectrum-viewer`）

## 1. 模块定位

本模块为两类历史数据提供统一只读视图：从旧 Access 光谱迁入的 `spectrum_bands`，以及从 DAT/PDT 迁入的 `result_matrices`。它负责列表、局部读取、坐标转换、CSV 导出和可见区域 PDF，不负责修改原始数据。

## 2. 代码入口

- 服务：[`modules/spectrum_viewer.py`](../../app/backend/modules/spectrum_viewer.py)
- API：[`api/spectrum_viewer.py`](../../app/backend/api/spectrum_viewer.py)；`/api/v1/spectra`
- 请求模型：[`schemas/spectrum_viewer.py`](../../app/backend/schemas/spectrum_viewer.py)。
- 前端：`pages/spectra/SpectrumViewerPage.tsx`（相对于 frontend/src/）。
- 测试：[`tests/test_s10_spectrum_viewer.py`](../../app/tests/test_s10_spectrum_viewer.py)

## 3. 统一记录标识

`_record_id(kind, identifier)` 把来源类型和数据库 ID 编入一个外部标识。调用者必须把它当作不透明字符串，不应自行拆接数字 ID。

`list()` 根据 `kind`、数量上限和可选角度筛选两类来源，返回统一摘要；`get()` 再根据记录标识进入正确来源分支。

## 4. 曲线读取

`_raw()` 是核心：

1. 读取波段布局、CCD 索引和点数。
2. 校验请求的 CCD 与横坐标窗口。
3. 从平均点或原始帧产生曲线。
4. 根据步长和波长系数生成像素坐标或波长坐标。
5. 返回多曲线、元数据和可见范围。

调用方可以只请求视窗内的数据，避免前端每次都搬运全部原始帧。坐标系切换时，筛选和导出必须使用同一组已解析坐标，不能在前后端各算一遍不同结果。

## 5. 导出与打印

`export_csv()` 导出当前可见范围，而非数据库中的完整隐藏数据。`render_visible_pdf()` 使用同一可见模型绘制 PDF，并通过 `_spectrum_pdf_font()` 选择可显示中文的字体。

因此，修复图表范围问题时应同时检查页面显示、CSV 和 PDF；三者应共享“当前选择、当前曲线、当前坐标窗口”的语义。

## 6. 错误边界

`SpectrumViewerError` 携带稳定错误码、状态码和明细。常见失败包括记录不存在、CCD 不存在、范围非法、BLOB 点数不匹配和请求格式不支持。

本模块读取迁移数据时仍会做结构检查，不能因为迁移阶段已经校验过就直接信任数据库 BLOB。

## 7. 推荐阅读顺序

`_record_id()` → `list()` → `get()` → `_raw()` → `_wave()` → `export_csv()` → `render_visible_pdf()` → 前端 `SpectrumPlot`。

## 8. 修改检查

- 两类来源是否保持同一响应语义而不丢失各自元数据。
- CCD、角度、像素/波长范围筛选是否一致。
- 平均曲线与原始帧是否清楚区分。
- CSV、PDF 是否只包含当前可见范围。
- 损坏 BLOB 和无效系数是否产生明确错误。
- 运行 S10 后端测试和前端构建。


## 实现分工

谱图服务继续负责来源选择、坐标兼容、区间和可见范围验证。`spectrum_pdf.py::render_spectrum_pdf` 接收选好的曲线、坐标范围和显示信息，只负责字体、绘制、分页及字节输出。前端 `SpectrumViewerPage` 统一持有选择、加载代次和视图状态；`SpectrumQueryToolbar.tsx`、`SpectrumRecordList.tsx`、`SpectrumViewToolbar.tsx` 分别呈现查询、来源列表和视图操作，继续使用现有 `SpectrumPlot`。

## 当前观察和输出操作（2026-10-16）

`SpectrumViewToolbar.tsx`、`SpectrumPlot.tsx` 与 `SpectrumPointDetails.tsx` 提供以下入口：多样叠加的同点强度表、任意点全部燃烧/空白原始积分明细及复制/PDF、输入 `CCD,点号` 跨CCD定位、左右逐点和上下缩放。界面点号从1开始。

CCD打印可选灰度/峰形图层及宽边、窄边、十倍CCD比例；至少选择一个图层，十倍比例需校验纸张可容纳。可见区域PDF与CCD比例打印分别使用各自模型，不能混用范围和比例。明细复制/输出执行权限及审计，损坏帧拒绝读取；观察不回写历史分析结果。证据与实体打印边界见 [十项实施清单第3、4、8、9项](../acceptance-reports/S24/artifacts/2026-10-16-legacy-ten-completion/实施清单.md)。
