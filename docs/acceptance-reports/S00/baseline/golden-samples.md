# 算法与解析黄金样本

## 目的

S00 把旧版关键算法和文件解析输入/输出冻结为机器可读 JSON。后续实现必须按计算档案区分：

- `legacy_2_0_2`：复现 Delphi 2.0.2 的边界、峰高、高斯插值、曲线拟合、暗扣除和结果处理。
- `modern_v1`：后续新增中心、峰高、Sigma、峰面积，并以峰面积参与定量；不能改变旧数据默认档案。

## 黄金文件

| 文件 | 覆盖 | 源码依据 |
|---|---|---|
| `golden/legacy-gaussian.json` | 3/5/7 点高斯、偶数点和非正值拒绝、double 结果及 float32 落库值 | `uPeakMode.pas:TGaussCur.Cal` |
| `golden/legacy-curve-fit.json` | 直线、二次、三次最小二乘，自然样条，普通/对数坐标 | `uFitMode.pas`、`FmAnaCurve.pas:TCoordTransform` |
| `golden/legacy-signal-processing.json` | 曝光均值、暗扣除、0.1 下限、寻峰、背景/内标、样本标准差、RSD、ID | `uCcdBand.pas`、`uAnaThread.pas`、`FmAnaCheck.pas` |
| `generated/legacy-format-probes.json` | CFG/OPT、SAM、PDT、DAT、真实 ACQ 帧及镜像/非镜像 CCD 映射 | 对应读写源码和真实样本 |
| `generated/access-probes/*.json` | Access 表结构、记录数、首行标量/BLOB 哈希与端点值 | `uDbPack.pas` 和真实数据库临时副本 |

`golden/manifest.json` 保存上述核心黄金文件的大小和 SHA-256。验证器先校验黄金文件完整性，再校验关键数学恒等和边界。

## 数值口径

- Delphi `Single` 的落库/结构体结果按 IEEE-754 `float32` 固化。
- 高斯内部、最小二乘内部按源码中的 `Double` 计算；高斯峰写入 `TPdt.Peak` 时再取 `float32`。
- 曲线系数 `TCs.Data` 是 `Single[4]`，黄金值按 float32 固化。
- RSD 使用有效重复值的样本标准差，`RSD=abs(100×StdDev/Mean)`，最大 999。
- ID 判定值为 `21.7147×ln(Max/Min)`。
- 光谱均值为燃烧 ADC 除以“帧数×燃烧周期”，再减暗 ADC 除以“暗帧数×暗周期”，最终下限 0.1。
- JSON 中声明绝对容差；实现测试不得用扩大容差掩盖系统性差异。

## 来源等级与剩余验证

数学向量是对 Delphi 源码逐式翻译得到的“源码派生黄金值”，真实 ACQ/PDT/DAT/Access 探针来自仓库原始样本。源码派生值足以约束首次移植，但 S16–S17 的算法正式关闭还应加入由旧版可执行程序对相同输入产生的第二套输出，或由独立实现交叉计算；该项已在风险账登记，不能由模拟结果替代。
