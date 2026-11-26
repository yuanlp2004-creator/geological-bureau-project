# AgeMotion 51个逻辑寄存器完整表

来源：随包控制器手册§4.1及§4.4；表与`motor_protocol.REGISTERS`同步。宽度包含连续的16位物理寄存器数；每次只访问一个逻辑寄存器。协议可写不表示HTTP已开放，也不代表支持在线随意修改。字符串字段采用8字节原样承载，调用方须按手册ASCII编码解码。

| 零起始地址 | API内部键 | 类型/宽度 | 协议读写 | 单位/用途 |
|---|---|---|---|---|
| 0x0000 | control | uint16，1 words | R/W | 控制位；不把所有位开放到HTTP |
| 0x0002 | error_code | uint16，1 words | R | 故障编码，0正常 |
| 0x0008 | input_type | uint16，1 words | R/W | 模式/方向位域 |
| 0x0010 | current_max | uint16，1 words | R | 0.01A；厂商固化 |
| 0x0011 | current_min | uint16，1 words | R | 0.01A；厂商固化 |
| 0x0012 | current_set | uint16，1 words | R/W | 0.01A相电流峰值 |
| 0x0013 | current_low | uint16，1 words | R/W | %，30..100 |
| 0x0014 | current_low_wait_ms | uint16，1 words | R/W | ms，50..65535，缺省为记忆值 |
| 0x0015 | current | uint16，1 words | R | 0.01A相电流峰值 |
| 0x001E | voltage_break | uint16，1 words | R/W | 刹车电压参数；详见手册§4.4.38 |
| 0x0020 | position | int64，4 words | R/W | MMS；写入改坐标 |
| 0x0024 | position_set | int64，4 words | R/W | MMS；写入触发运动 |
| 0x0028 | resolution | uint32，2 words | R | MMS/机械齿 |
| 0x002A | pulse_length | uint32，2 words | R/W | MMS/脉冲，1..3840000 |
| 0x002C | pulse_position | int32，2 words | R/W | 脉冲坐标；写入改坐标 |
| 0x002E | pulse_position_set | int32，2 words | R/W | 脉冲目标；写入触发运动 |
| 0x0030 | position_error_alarm | uint32，2 words | R/W | MMS；伺服专用 |
| 0x0032 | position_error_allowed | uint32，2 words | R/W | MMS；伺服专用 |
| 0x0034 | time_error_allowed | uint16，1 words | R/W | ms；伺服专用 |
| 0x0038 | position_error | int64，4 words | R | MMS；伺服专用 |
| 0x003C | pulse_position_error | int32，2 words | R | 脉冲；伺服专用 |
| 0x0040 | velocity_set | uint16，1 words | R/W | 原始速度，手册1..38400 |
| 0x0041 | velocity_start | uint16，1 words | R/W | 原始启动速度，手册1..192 |
| 0x0042 | velocity_filter | uint16，1 words | R/W | 脉冲控制滤波0..31 |
| 0x0043 | velocity_factor | uint16，1 words | R | KV；出厂固化 |
| 0x0044 | velocity_filter_com | uint16，1 words | R/W | 通讯控制滤波0..31 |
| 0x0045 | velocity | int16，1 words | R | 有符号实时速度；换算待型号确认 |
| 0x0046 | velocity_zero | uint16，1 words | R/W | 寻零/限位速度，1..38400 |
| 0x0047 | velocity_filter_zero | uint16，1 words | R/W | 寻零/限位滤波0..31 |
| 0x0060 | bus_watchdog_ms | uint16，1 words | R/W | ms；2..65535，>=32768关闭 |
| 0x0061 | bus_address | uint16，1 words | R/W | 1..247；不是广播地址0 |
| 0x0062 | bus_baud | uint32，2 words | R/W | bit/s；更改会影响后续通信 |
| 0x0080 | port | uint16，1 words | R | 原始输入端口位域；有效电平须现场核对 |
| 0x0081 | port_hi_flag | uint16，1 words | R/W | 上升沿标志 |
| 0x0082 | port_lo_flag | uint16，1 words | R/W | 下降沿标志 |
| 0x0083 | port_flip_flag | uint16，1 words | R/W | 翻转标志 |
| 0x0084 | port_config | uint64，4 words | R/W | 端口配置位域；不得擅改 |
| 0x0090 | input_band | uint32，2 words | R/W | Hz；输入带宽 |
| 0x0300 | cpu_temperature | int16，1 words | R | 温度原始值；详见手册§4.4.47 |
| 0x0301 | sink_temperature | int16，1 words | R | 温度原始值；详见手册§4.4.48 |
| 0x2000 | motor_sn0 | uint64，4 words | R/W | 电机授权/序列号数据；不得擅改 |
| 0x2004 | motor_sn1 | uint64，4 words | R/W | 电机授权/序列号数据；不得擅改 |
| 0x2008 | motor_sn2 | uint64，4 words | R/W | 电机授权/序列号数据；不得擅改 |
| 0x200C | motor_sn3 | uint64，4 words | R/W | 电机授权/序列号数据；不得擅改 |
| 0x2100 | motor_name | ASCII[8] / uint64载体，4 words | R/W | 8字节ASCII；底层按uint64承载，需要按字节解码 |
| 0x2104 | motor_date | uint32，2 words | R/W | 生产日期编码；不是时间戳 |
| 0x2106 | motor_number | uint32，2 words | R/W | 电机编号 |
| 0x2108 | servo | uint16，1 words | R/W | 伺服功能位域 |
| 0x8000 | driver_name | ASCII[8] / uint64载体，4 words | R | 8字节ASCII；底层按uint64承载，需要按字节解码 |
| 0x8008 | driver_date | ASCII[8] / uint64载体，4 words | R | 8字节ASCII |
| 0x800C | driver_number | ASCII[8] / uint64载体，4 words | R | 8字节ASCII |

合计：51个逻辑寄存器。普通HTTP参数修改只允许current_set/current_low/velocity_set/velocity_start；运动由move/jog完成。
