# 旧格式与二进制协议基线

## 判定口径

冲突按“实际文件与旧版运行行为 → Delphi 源码/DFM → 协议文档 → 研究文档”处理。下列结论以只读探针和源码交叉验证；详细数值在 `generated/legacy-format-probes.json`、`generated/access-probes/*.json` 中。

## 兼容格式总表

| 格式 | 选定可读样本 | 读取依据 | S00 结论 |
|---|---|---|---|
| `.MTD` | `Spec2.02/DIRECT.MTD`、`SpecFile/03_方法与数据库/DIRECT.MTD` | Jet 4.0 只读表探针、`uDbPack.pas` | Access 方法库；前者为 3 个方法、20 条谱线、5 条色散曲线、空 `USER` 表，二者同时覆盖 50/16 点标准值布局 |
| `.mdb` | `SpecFile/03_方法与数据库/分时样品.mdb`、`SpecFile/03_方法与数据库/蒸发色散.mdb` | Jet 4.0 只读表探针 | 分别为空的分时样品模板，以及带 `POINT_WAVE` 表的蒸发/色散模板 |
| `.cdt` | `Spec Source/Bin/DATA/测试15-5_20170509_[2-16].cdt` | Jet 4.0、`TDbCcdCdt` | `LAYOUT` + `CCD_BAND`；保存分 CCD 的 `float32` 平均强度 |
| `.cmt` | `Spec2.02/DATA/测试15-5_20170509_[2-16].cmt` | Jet 4.0、`TDbCcdCmt` | 全时样品；保存燃烧/暗帧 `uint16` BLOB 和坏帧索引 |
| `.edt` | `Spec2.02/DATA/20141029_测试.edt` | Jet 4.0、`TDbCcdCyc` | 蒸发全帧文件 |
| `.wdt` | `Spec2.02/DATA/20141029_测试.wdt` | Jet 4.0、`TDbCcdCyc` | 色散全帧文件 |
| `.pdt` | `Spec Source/Bin/DATA/测试15-5_20190421_1842.pdt` | `TSdMatrix.LoadPdt` + 完整二进制消费 | 强度矩阵；支持普通头和曝光区间头 |
| `.dat` | `Spec Source/Bin/DATA/测试15-5_20190421_1842.dat` | `TSdMatrix.LoadDat` + 完整二进制消费 | 分析结果矩阵 |
| `.sam` | `Spec2.02/DATA/测试15-5.sam`、`测试15-5-960.sam` | `TSampList.LoadFromFile` + 行解析 | 制表符分隔；样名 + 重复数，空样重复数为 0；“960”样本实际 800 行、展开 960 个谱带 |
| `DIRECT.CFG` | `Spec2.02/DIRECT.CFG` | `uConfigs.pas` + INI 解析 | 分析显示、等待、暗帧轮询和安全时间 |
| `DIRECT.OPT` | `Spec2.02/DIRECT.OPT` | `uOptions.pas` + INI 解析 | 串口、CCD、页面、打印机和保护设置 |
| `.acq` | `Spec Source/Res/模拟数据/280-288.acq` | `2送数顺序.doc`、`TAcqCyc`、`Acq2Ccd` | 一轮 3 组、每组 2 CCD × 2048 点，总长 24,579 字节 |

## ACQ 传输帧

依据：`Spec Source/Doc/2送数顺序.doc`、`Spec Source/Source/Common/uCcdBand.pas`、`uCcdThread.pas`、`uOptions.pas`。

一轮固定结构：

```text
frame[0] = head:u8 + adc:uint16_le[4096]
frame[1] = head:u8 + adc:uint16_le[4096]
frame[2] = head:u8 + adc:uint16_le[4096]
总长 = 3 × (1 + 4096 × 2) = 24,579 字节
```

- 每帧交错传输两个 CCD：`CCD-A 点1, CCD-B 点1, CCD-A 点2, CCD-B 点2, ...`。
- `head == 0` 表示该组有效，其他值表示错误；三个头分别判定。
- 默认 `FrameCount=3`、`CcdsPerFrame=2`、`PointsPerCcd=2048`、波特率 460800。
- 实际安装 CCD 由 `DIRECT.OPT [CCD] CcdIndexs` 指定。基线样本为 `1,2,3,5,6`，内部转为零基 `[0,1,2,4,5]`。
- `Mirror=False` 时，`Acq2Ccd` 反向选择物理组和组内通道，点序保持 0→2047；`Mirror=True` 时顺向选择物理组和通道，点序 2047→0。
- 原始字节到逻辑 CCD 的两套映射结果及每片 CCD 的 SHA-256 已锁在 `generated/legacy-format-probes.json`。

仓库中的 6 个 `.acq` 文件都恰为 24,579 字节；Bin 与 Res 各有三份对应数据。S11 模拟器可使用这些文件，但不能把模拟回放当作真实设备验收。

## Access 数据库布局

所有 S00 探测均对临时副本使用 `Provider=Microsoft.Jet.OLEDB.4.0;Mode=Read`，不连接历史原件。

### 方法库 `.MTD/.mdb`

主要表：

- `MTD_PRIM`：方法主信息、参考线、重复次数、RSD/ID、曝光区间模式。
- `MTD_BURN`：预激发、燃烧/暗采样周期和次数。
- `MTD_WSTC`：方法与色散曲线关系。
- `LINES`：谱线、类型、内标/定位引用、寻峰/背景/拟合/坐标、标准点 BLOB。
- `WSTC`：CCD 布局和色散系数。
- `USER`：基线 `DIRECT.MTD` 中为空；旧源码没有可用的登录/权限闭环。

标准点 BLOB 存在版本变体：`Spec2.02/DIRECT.MTD` 首行 `Stds` 为 700 字节，即 `50 × sizeof(TStd=14)`；`SpecFile/03_方法与数据库/DIRECT.MTD` 首行是 224 字节，即旧版 `16 × 14`。S06 必须按实际 BLOB 长度判别 16/50 点布局，不能固定截取。

### 谱图库 `.cdt/.cmt/.edt/.wdt`

共同 `LAYOUT` 字段：`MtdId`、`FrameCount`、`CcdsPerFrame`、`PointsPerCcd`、`PointWidth`、`CcdGapPoints`、`CcdCount`、`CcdIndexs`、`WsCof`、`RefWave`。全帧类型还保存 `PreBurn`、`BurnCyc`、`DarkCyc`、`BurnCount`、`DarkCount`。

共同 BLOB 约定：

- `CcdGapPoints`：`(FrameCount × CcdsPerFrame - 1)` 个 little-endian `float32`。
- `CcdIndexs`：`CcdCount` 个 `uint8`，值为零基物理槽位。
- `WsCof`：packed `TWsCof`，6 个 little-endian `float32`：`A/B/C/WavePerStep/MinWave/MaxWave`。
- `BurnAdcs`：`BurnCount × CcdCount × PointsPerCcd` 个 little-endian `uint16`。
- `DarkAdcs`：`DarkCount × CcdCount × PointsPerCcd` 个 little-endian `uint16`。
- `CcdAvgs`：`CcdCount × PointsPerCcd` 个 little-endian `float32`。

`CCD_BAND` 按类型分为：

- `.cdt`：样品序号/名称/长名称/时间 + `CcdAvgs`。
- `.cmt`：同样品字段 + `BurnAdcs`、`DarkAdcs`、`ErrIndex`。
- `.edt/.wdt`：谱带名称/时间 + `BurnAdcs`、`DarkAdcs`。

`ErrIndex` 的符号语义按格式文档为“正值指燃烧帧丢失，负值指暗帧丢失”；新导入器只能标记，不能静默填补或改写原件。

## PDT 二进制

依据：`Spec Source/Source/Common/uMethodMap.pas:TSdMatrix.LoadPdt/SavePdt`。

所有多字节数值为 Windows little-endian；Delphi `Single=float32`、`Int16=2`、`Int32=4`、`TDateTime=float64`。

```text
head:u16                 0x0A70=普通 PDT，0x0A73=曝光区间 PDT
method_id:i32
measure_time:f64         Delphi TDateTime，纪元 1899-12-30
sample_count:i16
line_count:i16
sample_names:ShortString[10] × sample_count   每项固定 11 字节
sample_repeats:i16 × sample_count
elements:ShortString[4] × line_count          每项固定 5 字节
waves:f32 × line_count
backs:i16 × line_count
digits:i16 × line_count
exp_segments:(left:u8,right:u8) × line_count  仅 0x0A73
pdts:(peak:f32,back:f32) × sum(sample_repeats) × line_count
```

`TPdt` 是 packed variant record，`Black` 与 `Peak` 共用前 4 字节，完整记录仍为 8 字节。读取时未知头或截断必须整体拒绝。

## DAT 二进制

依据：`Spec Source/Source/Common/uMethodMap.pas:TSdMatrix.LoadDat/SaveDat`。

```text
head:u16                 固定 0x0A64
measure_time:f64
sample_count:i16
line_count:i16
sample_names:ShortString[10] × sample_count
elements:ShortString[4] × line_count
digits:i16 × line_count
data:f32 × sample_count × line_count
```

文件本身不保存方法 ID、波长和重复次数；导入时必须明确这种信息缺失，不能猜测补齐。

## SAM、CFG 和 OPT

`.sam` 每行是 `样品名<TAB>重复数`。旧代码先 `Trim` 样品名；重复数解析失败时按 0。S07 正式实现应更严格：失败整批回滚并保留行号、原文和原因。普通样例与文件名含“960”的大样例均纳入探针。后者实际是 800 行：720 行重复数 1、80 行重复数 3，按旧逻辑展开后恰为 960 个谱带；因此验收必须同时断言源记录数和展开谱带数。

配置职责以源码和实际文件为准：

- `DIRECT.CFG`：`[ANALYZE]` 与 `[SAFETIME]`。
- `DIRECT.OPT`：`[PComm]`、`[SCREEN]`、`[CCD]`、`[PAGESETUP]`、`[PRINTER]`、`[PROTECT]`。

## 已确认冲突与处理

1. `3数据存储格式.doc` 把 `.cdt` 的 `CcdAvgs` 写成 `CcdCount*2K*2字节`，但源码以 `Single` 读写，真实 BLOB 长度也符合每点 4 字节。锁定为 little-endian `float32`。
2. 同一文档把 `SampName` 写成 `Char(8)`；历史 `.cdt/.cmt` 样本确为 8 字符字段，但 `SpecFile/03_方法与数据库/分时样品.mdb` 空模板为 10 字符，Delphi `TSampName=string[10]`，同时还有 `LongName Char(20)`。迁移器必须按每个源文件的实际 schema 读取，不能假定所有版本都为 8 或 10。
3. 研究文档把软件参数/设备参数与 CFG/OPT 的职责有交叉描述；实际代码明确软件分析设置写 CFG、硬件与页面设置写 OPT。
4. 旧版 `TGaussCur` 计算并返回高斯峰高，没有计算峰面积。`legacy_2_0_2` 必须复现峰高；`modern_v1` 才新增峰面积并用于定量。
5. 旧版只有分析线、内标线、定位线三类，背景是参数而非独立谱线。新版“基线谱线”是明确新增类型，不能伪装成旧格式已有字段。
6. 缺少 README 所称的 `1单片机控制指令.doc`。现有资料只足以确认采集状态和帧格式，不足以确定转角或汞灯命令字；任何实现都不得猜测。
7. `测试15-5-960.sam` 实际为 800 行、展开 960 个谱带；以真实文件为准修正“960 行”口径。
