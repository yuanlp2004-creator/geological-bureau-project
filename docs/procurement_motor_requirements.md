# 磋商文件：自动转角、电机控制及相关功能原文摘录

核对日期：2026-09-04。来源为本项目实际提供的《磋商文件.doc》。本文按章节和条款定位；链接中的行号是ExtractedText行号，不是 Word 页码。

[原始磋商文件](E:/Bocchi/Codes/Code_Lab/地质局项目/磋商文件.doc) · [完整ExtractedText](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt)

以下引用保留原文用词及条款标记，调整表格换行以便阅读。引用后的“关联说明”是分析，不是原文。项目名称在封面、公告、表格和响应文件模板中多次重复，不重复列为功能要求。

## 一、直接涉及自动转角和电机的表述

### 第三章／二、技术要求／1、软件概述：现状

> 采购人当前CCD-I型（单转角光栅）和CCD-III（已设计为可加装步进电机光栅驱动装置）平面光栅电弧直读发射光谱仪配备的是SpecDirect2.0版软件，该软件已稳定使用近十年，工作稳定，但仅支持单转角光栅，每次摄谱的过程中，光栅固定不可转动，分析谱线波长范围不可调。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:250)

关联说明：说明现有 CCD-I、CCD-III 及旧 SpecDirect2.0 的固定转角工作方式。“已设计为可加装”不等于本次交付仪器已经安装电机。

### 第三章／二、技术要求／1、软件概述：新增目标

> 现需要开发自动转角平面光栅电弧直读发射光谱仪（以下简称光谱仪）分析软件（以下简称自动转角软件），在摄谱过程中可根据分析需要自动控制光栅转角。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:251)

关联说明：明确要求在摄谱过程中按分析需要自动控制光栅转角。

### 第三章／二、技术要求／★2、软件总体要求

> 自动转角软件应在兼容原SpecDirect2.0版软件的主要功能的基础上，增加控制步进电机驱动光栅精确转动的功能，在摄谱过程中能实时采集不同光谱波段的光谱信号，并在摄谱后分析数据，拟合标准曲线生成准确的分析报告；同时兼容原固定转角的光谱仪。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:253)

关联说明：直接要求步进电机驱动光栅精确转动，并要求不同波段采集、后续分析及固定转角兼容。这是整机功能要求，没有规定个人分工或电机 API 的路由清单。

### 第三章／详细技术要求／*1.1.1

> *1.1.1、方法的各个转角对应的摄谱区间可自由选择保存区间平均值或全区间数据。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:275)

关联说明：分析方法需要表达转角与摄谱区间的关系，并支持两种数据保存方式。主要涉及方法、采集和存储模块；电机模块为其执行目标转角。

### 第三章／详细技术要求／*1.2.1

> *1.2.1、软件自动转角控制通常先短波后长波，以节省光栅转动时间，但必要时能优先转动至关键波段转角。摄谱时可通过检测基线强度和位置判断电弧是否正常（提示异常）、峰位是否正常（自动校正或提示异常）。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:283)

关联说明：包括转角顺序、关键波段优先以及基线／峰位监测。“先短波后长波”是按波长组织的要求，不能直接等同于电机坐标递增；“自动校正”在此处没有指定必须通过转动电机实现。

### 第三章／详细技术要求／*1.2.4

> *1.2.4、软件在查看谱图和样品分析时可根据需要定位查看各分析谱线、某转角的检测器的一个信号点的强度数据。谱图可横向及纵向缩放。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:286)

关联说明：要求能按转角和检测器信号点查看强度数据。这里的“定位查看”属于谱图／数据定位，不是电机定位命令。

## 二、全部 18 条详细技术要求

为避免遗漏与新增模块的关联，下面完整收录详细技术要求。文件未将所有条款逐一标为“旧功能”或“新功能”，不能仅按是否带星号判断是否新增。上节出现的条款在本节保留，便于对照完整清单。

### *1.1.1

> *1.1.1、方法的各个转角对应的摄谱区间可自由选择保存区间平均值或全区间数据。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:275)

关联说明：转角、摄谱区间及数据保存方式；与自动转角采集直接关联。

### 1.1.2

> 1.1.2、在方法中增加谱线时要能计算谱线是否在可检测范围内。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:276)

关联说明：谱线可检测范围判断；需要结合所用光学配置／标定，属于方法与光学处理。

### 1.1.3

> 1.1.3、谱线支持基线、分析线、内标线、定位线。分析线的内标可选内标线、背景做内标、无内标。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:277)

关联说明：谱线类型和内标处理，属于光谱分析。

### 1.1.4

> 1.1.4、分析线的峰值选可最大值（单点）或高斯曲线（峰面积）。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:278)

关联说明：峰值／峰面积处理，属于光谱分析。

### 1.1.5

> 1.1.5、分析线拟合时应可选对数坐标、普通坐标。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:279)

关联说明：拟合坐标选择，属于光谱分析。

### 1.1.6

> 1.1.6、分析线的拟合函数有直线函数、二次曲线、三次曲线、样条函数插值等。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:280)

关联说明：拟合函数选择，属于光谱分析。

### 1.1.7

> 1.1.7、分析方法的条件参数及谱线参数应可打印。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:281)

关联说明：方法参数打印，属于方法管理与输出。

### *1.2.1

> *1.2.1、软件自动转角控制通常先短波后长波，以节省光栅转动时间，但必要时能优先转动至关键波段转角。摄谱时可通过检测基线强度和位置判断电弧是否正常（提示异常）、峰位是否正常（自动校正或提示异常）。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:283)

关联说明：波段转角顺序及基线／峰位异常监测；涉及调度、采集与分析的协同。

### 1.2.2

> 1.2.2、软件支持色散摄谱、蒸发摄谱、样品摄谱及后续色散曲线、蒸发曲线、样品分析功能。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:284)

关联说明：三类摄谱及其后续处理；电机控制不替代这些采集和分析功能。

### 1.2.3

> 1.2.3、软件应具有查看谱图功能，能同时查看对比多个样品的谱图强度。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:285)

关联说明：谱图查看和比较，属于数据展示。

### *1.2.4

> *1.2.4、软件在查看谱图和样品分析时可根据需要定位查看各分析谱线、某转角的检测器的一个信号点的强度数据。谱图可横向及纵向缩放。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:286)

关联说明：按转角查看检测器数据及缩放，属于数据关联和展示。

### 1.2.5

> 1.2.5、样品分析时可预先输入样号、也可摄谱完成后再给样品命名。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:287)

关联说明：样号录入与命名，属于样品管理。

### *1.2.6

> *1.2.6、样品分析时应有慢进功能，可实时查看分析谱线的峰位及周边谱图，必要时可人工干预。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:288)

关联说明：原文限定在“样品分析时”的慢进和人工干预；没有写电机慢速运动、点动或速度调节。

### 1.2.7

> 1.2.7、软件应具有检测数据重复性误差的自动识别功能，实现数据自动预警提示功能。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:289)

关联说明：数据重复性误差识别与预警；不是电机重复定位精度的数值要求。

### 1.2.8

> 1.2.8、软件拟合标准曲线时可随机切换拟合方式，可根据管理样数值适配调整曲线，并保存调整后的标准强度。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:290)

关联说明：标准曲线拟合与调整，属于定量分析。

### *1.2.9

> *1.2.9、软件应该具有调试功能，可不摄谱（激发电弧），用汞灯调试光学系统。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:291)

关联说明：汞灯光学调试及不激发电弧的使用场景。括号按原文保留，具体调试采集与转角操作流程仍需明确。

### 1.3.1

> 1.3.1、系统应具有灵活的报告打印功能，实现不同类型报告数据打印，打印预览的报告可以实现数据导出，实现excel，pdf 等格式文件的导出功能。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:293)

关联说明：报告打印、预览及文件导出。

### 1.4.1

> 1.4.1、软件系统应具有角色管理功能，不同级别的人员具有相应的权限。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:295)

关联说明：角色权限管理；电机接口应融入项目权限体系，但该条未指定电机权限名称。

## 三、稳定性、交付及架构的相关表述

### 第三章／二、技术要求／稳定性

> 稳定性：软件要求工作稳定，稳定性与SpecDirect2.0软件相当。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:254)

关联说明：整体软件稳定性要求，没有给出电机通信超时、停止时间或定位精度的数值。

### 第三章／二、技术要求／实用性

> 实用性：软件应切合光谱仪实际工作流程，同时最大限度满足各项功能要求。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:255)

关联说明：要求贴合实际仪器流程，是复用既有操作方式和安排整机联调的依据。

### 第三章／四、商务要求／★1、合同履行期限

> ★1、合同履行期限：2026年10月31日前完成第一版测试软件，2026年12月20日前完成全部工作，具体以合同约定的要求为准。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:296)

关联说明：第一章第 5 项也重复了这一期限。这里仅摘录文件中写明的交付安排。

### 第三章／四、商务要求／★2、知识产权要求

> 在本项目的软件著作权及源代码归采购人所有，供应商还应提供相关产品的技术白皮书、帮助手册、应用接口文档等。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:298)

关联说明：明确要求源代码及应用接口文档等交付物，没有指定 HTTP、REST、函数名、参数格式，也未把全部接口分配给电机开发人员。

### 第四章／评分细则／总体架构设计

> 系统架构设计合理，实现完整业务流程。软件架构能够完整说明系统采用的关键技术、具体实现途径,包含系统架构图，业务流程图，技术路线图。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:340)

关联说明：要求完整业务流程与架构、业务流程、技术路线图；不是独立的新增电机动作要求。

## 四、原文中两种星号的区别

### 第三章开头对“★”的说明

> 说明：“★”号标注的内容为实质性要求，必须满足或优于该要求，否则按照无效响应处理。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:244)

关联说明：此处说明的是实心星“★”。

### 第四章／技术要求响应评分对“*”的说明

> “*”条款每一项完全满足或正偏离的得2分，非“*”条款每一项完全满足或正偏离的得1分，不满足不得分，最高得23分。

[原文定位](E:/Bocchi/Codes/Code_Lab/地质局项目/MotorApiResearch/evidence/ExtractedText/ProcurementSpecifications.txt:337)

关联说明：详细技术要求中的星号“*”另有评分说明；不要把两种标记混为同一含义。

## 五、与电机 API 的职责对应（分析）

| 原文要求 | 对电机 API 的关联 | 还需配合的模块 |
|---|---|---|
| 步进电机驱动光栅精确转动 | 接受目标并执行运动，向调用者报告状态和结果 | 机械安装、标定、真机验证 |
| 摄谱中自动控制转角 | 提供可被调度调用的运动能力 | 采集调度、CCD／激发控制 |
| 短波优先、关键波段优先 | 执行调度选定的目标；不是自行按脉冲大小推定波长顺序 | 方法、波段选择与调度 |
| 各转角对应摄谱区间 | 提供定位结果以衔接相应采集段 | 采集、存储 |
| 按转角查看检测器信号 | 可向上层提供运动目标／结果标识 | 数据关联、谱图展示 |
| 汞灯光学调试 | 如调试流程需要，提供独立转角能力 | 汞灯使用、CCD 调试、光学标定 |
| 兼容固定转角仪器 | 固定转角模式下不应强制依赖电机连接 | 配置、调度 |

本表是开发职责分析，不是采购文件给出的人员分工。

## 六、本文核对范围内未见明确规定的内容

文件没有明确写出以下电机技术细节；它们可能需要结合最终技术方案、现场条件或后续要求确定，不能把我们的设计选择标为磋商原文：

- “任意角度”“角度无限制”或指定几个固定转角的明确限制。原文是“根据分析需要自动控制光栅转角”。
- 必须连续旋转并同时曝光，或必须逐点停稳采集的明确模式。
- 电机允许角度上下限、定位精度、重复定位误差、最大转动时间／停止时间的具体数值。
- 电机与驱动器型号、传动比、每圈脉冲数、串口参数和寄存器协议。
- 自动机械回零、原点／限位传感器、暂停继续、点动、多轴的明确功能清单。
- 通信中断后的运动恢复规则、故障时电机／电弧／CCD 的具体停止顺序。
- RtuMotor 名称、要求移植它的具体条款，或现成的电机 API 定义。
- 必须由“电机控制 API 开发人员”同时承担 CCD 采集、光谱分析或全部新增功能的分工。

第五章合同格式中的交付与验收栏为“见磋商文件”等占位表述，没有补充上述电机量化指标；该章注明其合同书仅作为正式签约参考。
