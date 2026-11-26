# 硬件与电机文档

本目录集中存放自动转角光谱仪的电机控制原理、寄存器参考、控制器手册、磋商技术要求及旧版调试对中示意图。真实串口、光栅转动及现场硬件验收门禁仍以 [验收总览](../acceptance-reports/README.md) 为准。

## 文件清单

| 文件 | 用途说明 |
|---|---|
| [motor_control_reference.md](motor_control_reference.md) | 电机控制原理、`RtuMotor` 控制逻辑与旧程序源码依据 |
| [register_reference.md](register_reference.md) | AgeMotion 51 个逻辑寄存器完整地址与读写映射表 |
| [motor_api_completion.md](motor_api_completion.md) | 独立电机 Python API 完成范围与磋商需求核对 |
| [procurement_motor_requirements.md](procurement_motor_requirements.md) | 磋商文件自动转角、电机控制及相关功能原文摘录 |
| [commissioning_checklist.md](commissioning_checklist.md) | 现场调试前需确认的有效配置与联调核对清单 |
| [CtrlAndCom_CHN.pdf](CtrlAndCom_CHN.pdf) | 驱动控制器与串口通信中文手册 |
| [自动转角光谱仪功能性能配置要求.png](自动转角光谱仪功能性能配置要求.png) | 采购功能与性能配置要求原图 |
| [旧版调试对中_窗口示意.png](旧版调试对中_窗口示意.png) · [SVG](旧版调试对中_窗口示意.svg) | Spec2.02 旧版调试对中窗口布局示意 |
| [旧版调试对中_源码示意.png](旧版调试对中_源码示意.png) · [SVG](旧版调试对中_源码示意.svg) | Spec2.02 旧版调试对中源码机制示意 |

---

[返回文档首页](../README.md) · [文档归档](../归档/README.md)
