# 电机 API 完成范围与磋商需求核对

核对对象是当前 `Reference/RtuMotor` 源码、根目录原始 `磋商文件.doc` 和独立 Python API 1.1.0。本篇只讨论电机相关能力。

## 当前结论

**RtuMotor 的公开驱动 API 已全部提供 Python 对应：31 个公开方法（含构造函数）、17 个公开属性。独立服务提供 23 个电机 HTTP 操作，另有健康检查。120 项离线测试通过。**软件实现与离线覆盖完成，不代表整机接入或真机验收完成。

逐项清单从原 Delphi 声明生成，见 [公开 API 对应表](../evidence/rtumotor_python_api_map.md) 和 [核对结果](../reports/motor_api_coverage.json)。31 个方法不等于 31 条 HTTP 路由：一个 HTTP 操作可能调用多个寄存器方法，构造函数和缓存属性也不必各有一个路由。

## 两层 API

| 层次 | 入口 | 职责 |
|---|---|---|
| 驱动层 | `StandaloneMotorApi/rtumotor_api/legacy.py` 中 `RtuMotor` / `TRtuAgeMotion` | 全部原读写方法、7 类控制字、角度换算、缓存属性、收发报文与 OutOnly |
| 应用层 | `MotorService`、HTTP、`MotorApiClient` | 单轴任务、角度/脉冲/MMS 定位、范围与补偿检查、到位确认、暂停/恢复、故障及生命周期 |

驱动层保留 Delphi 同名方法、属性，并提供蛇形命名的方法。`ReadPosition()` 返回新读值并更新 `Position` 缓存；读取 `Position` 本身不发串口请求。写目标会立即触发驱动器定位，不等待到位；写当前位置是修改坐标。

驱动层供独占连接的设备调试和移植使用，不执行应用层的机械限位、任务和现场标定检查。不要与运行中的 MotorService 共享同一 client；产品调用优先使用应用层 API。

## 原能力与应用接口对应

HTTP 前缀 `/api/v1/motors`；完整参数见 [启动说明](../StandaloneMotorApi/startup_and_integration.md) 与 [OpenAPI](../StandaloneMotorApi/OpenAPI.json)。

| RtuMotor 能力 | 应用层对应 |
|---|---|
| 连接、选 COM、初始化读回 | `/ports`、`/connect`、`/disconnect`、`/parameters` |
| 全部 12 个读方法 | `/registers/{name}`；另有状态、刷新及参数读取 |
| 电流、降流、运行/启动速度写入 | `PATCH /parameters` |
| WritePulseLength | `PATCH /pulse-length`，读回后作废当前参考，要求重新核对配置并连接 |
| WritePosition、WritePulsePosition | `/coordinate-native`，静止时一致更新当前与目标坐标 |
| WritePositionSet、WritePulsePositionSet | `/move-native`，支持 pulse 与 MMS |
| Degree2Pulse、Pulse2Degree、角度与步数输入 | 驱动层同名函数；应用层 `/move`、`/jog`、`/move-native` |
| ControlEnable、ControlFree、ControlRestartFlag | `/control/enable`、`/control/free`、`/control/restart_flag` |
| ControlPause | `/pause`；增加 `/resume` 以恢复本会话确认过的目标 |
| ControlStop、旧界面 P 按钮 | `/stop`，终止任务并确认停止 |
| ControlOffsetToZero | `/coordinate/offset-to-zero`，仅静止时执行并读回 |
| ControlReset | `/save-restart`，单次发送保存重启并作废连接 |
| OutHex、InHex | `/diagnostics`，返回最后一笔交易且不发送新请求 |
| OutOnly | 驱动层属性；无应答写后作废连接，不伪造成功读值 |
| 每圈 MMS/脉冲、间隙、范围配置 | 驱动层属性及应用层 MotorProfile |
| 窗口按钮、空闲轮询、计时 | 按动作映射到任务、刷新和事件；不复制 VCL 消息循环、窗口布局或空的 Save 实现 |

旧界面“自由转动”是绕过范围检查，应用层改为明确配置已验证的上下限。旧 `BbtPause` 实际调用 Stop；此次应用层暂停/恢复是基于 ControlPause 新增的受控任务能力。

## 必要行为修正

- 负数对称取整，溢出报错；原生 MMS 以十进制字符串传入 HTTP，保留不足一个脉冲的整数目标。
- 应用层设坐标先确认静止、暂停并核对，再同步当前和目标坐标、恢复原模式；它不是机械寻零。
- 暂停确认暂停位、速度零、位置稳定和目标不变；恢复前核对目标、故障及几何。暂停时间计入原运动总超时，停止优先于恢复。
- 运动使用同一个绝对截止时间；即使工作线程暂时拿不到服务锁，截止时间以后 `resume` 也不会再次发送使能命令。
- STOP 在调用入口即记录截止时间和取消意图，在当前 RTU 帧结束后优先于批量读取的后续帧。STOP 控制字直接发送，不先读取 Control，避免读取动作改变驱动器 BusWDT 状态；已知的重启/参考标记位由会话状态保留。
- 主动 STOP 且确认静止记为 `stopped`；运动超时、驱动器/通信故障、停止未确认或参考失效记为 `failed/fault`。这是应用 API 的安全状态约定，旧 RtuMotor 界面没有定义任务状态。
- 修改 PulseLength 后，旧参考不再可用，角度显示失效，必须重新核对每圈脉冲、零点和范围并连接；本操作不自动保存到闪存。
- 保存重启及 OutOnly 均不自动重试，明确区分已发送和已确认。故障不自动恢复旧任务。

## 磋商文件还需要哪些电机相关 API

已重新解析原始 DOC。原文定位见 [条款摘录](procurement_motor_requirements.md)。文件规定整机功能，没有逐条规定路由或个人分工。

| 条款 | 电机相关含义 | 实现及剩余事项 |
|---|---|---|
| 概述、总体要求：按需要精确转角 | 接收目标并执行定位，反馈成功/失败 | 动作、范围、到位及任务反馈已实现；实际精度、传动换算和允许范围待真机验证 |
| 总体要求：兼容固定转角仪器 | 没有电机时也能进入固定角度流程 | 新增 `FixedAngleTurnAdapter`：只接受配置角度，明确不执行运动；还需 GeoSpectrum 根据仪器模式选择适配器 |
| 1.1.1：转角对应摄谱区间 | 执行上层为区间指定的角度 | `MotorTurnAdapter.turn`、任务 ID、correlation_id、calibration_id 可用于关联；电机层不选择区间 |
| 1.2.1：短波优先、关键波段优先 | 按给定顺序执行目标并反馈 | 不需要另设“短波电机指令”；原项目有排序逻辑，仍需接入真实转角执行。电机 API 不从波长自行求角度 |
| 1.2.1：峰位自动校正或提示 | 若采用微转角校正，需要执行微调 | `/jog`、`/move-native` 已支撑动作；条款没有指定必须用电机校正，校正量由上层决定 |
| 1.2.9：汞灯调试光学系统 | 调试时可能需要单独调整光栅 | 增量定位、参数修改、状态和停止已具备；汞灯模式允许运动的时机由整机流程决定 |

**未从磋商文件发现还缺少的通用电机动作接口。剩余关键工作是正式软件接入与现场验证。**`GeoSpectrum/app/backend/app/modules/hardware_acquisition.py` 的 `SerialTurnAdapter.connect` 仍报告 `hardware_protocol_unavailable/deferred_external`；本次没有修改它。因此独立库完成不等于正式软件已经能够实机自动转角。

1.2.4 的“定位查看”是数据定位；1.2.6 的“慢进”位于样品分析语境，不能认定为电机慢速转动。文件没有明确要求自动机械回零、传感器寻限、多轴或无限连续转动 API。

若现场后来确认需要机械回零、硬限位寻位或非线性光栅机构换算，应补充专门流程，并提供端口、电平、机械关系与验证标准。详见 [现场核对清单](commissioning_checklist.md)。

## 验证

检验结论分为以下证据层次：

1. `audit_motor_api.py` 直接解析受保护的 Delphi 源码、原始磋商 DOC 和当前 OpenAPI，不以人工整理表代替原文件；结果为 31 个公开方法、17 个属性、23 个电机 HTTP 操作，缺失项 0。
2. 寄存器地址、宽度、大小端、控制字及 BusWDT 行为依据 RtuMotor 源码和随附 AgeMotion 驱动器手册；CRC、分段帧、异常帧和写回显由协议测试覆盖。
3. 内存设备模拟器经过与串口相同的 RTU 编解码，注入停转、报警、坏帧、短写、超时和并发时序。它用于验证软件协议和状态机，不模拟真实机械负载、惯性或光学效果。
4. 回归测试覆盖原公开 API、原生坐标及补偿限位、暂停/恢复/STOP 竞争、请求起算的停止截止时间、故障状态、固定角度、HTTP 鉴权及 Python SDK。独立 API **120 项通过**；GeoSpectrum 相关的电机、设备、采集调度、汞灯标定和架构测试 **75 项通过**。独立测试原始结果见 [测试 XML](../StandaloneMotorApi/test_results.xml)。
5. `verify_originals.py` 重新计算受保护文件摘要：391 项均未发生未记录的修改。

```powershell
python MotorApiResearch/tools/audit_motor_api.py
python MotorApiResearch/StandaloneMotorApi/run_tests.py
python MotorApiResearch/StandaloneMotorApi/verify_originals.py
```

未连接真机，未重打包 Runtime。现有检验不能证明交付机的 COM 接线、驱动器固件、BusWDT 实际时序、机械方向/传动比/限位、失步、间隙、停止距离、定位重复性或角度—波长关系正确，也没有完成 GeoSpectrum 的真实串口适配器装配。两个参考项目、Word 文档和既有 `.http` 文件保持原样。
