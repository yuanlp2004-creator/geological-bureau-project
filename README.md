# GeoSpectrum

GeoSpectrum 是兼容 SpecDirect 2.0.2 业务流程和旧数据格式的 Windows 光谱分析软件。它涵盖方法、样品队列、色散／蒸发／样品摄谱、定量分析、质控和报告输出。

## 启动软件

双击项目根目录的 `GeoSpectrum.exe`。同目录的 `geospectrum-backend.exe` 由主程序自动启动。首次使用按界面提示创建本地管理员，默认数据目录为 `%LOCALAPPDATA%\cn.geospectrum.desktop`。

通过 Git 获取源码后，按 [开发与构建说明](app/README.md) 准备环境并生成程序。配对 EXE 和本机旧版资料独立于 Git 源码分发。

## 从这里查找

| 需要做什么 | 阅读入口 |
|---|---|
| 上手操作、迁移旧数据、排查常见问题 | [使用说明与离线手册](docs/使用与说明/README.md) |
| 核对本机交付、测试结果或现场验收状态 | [当前交付与验收](docs/acceptance-reports/README.md) |
| 运行开发环境、构建和测试 | [应用开发说明](app/README.md) |
| 查源码、硬件资料和历史记录 | [文档索引](docs/README.md) |

正式实现位于 [app/](app/)。开发范围和执行规则见 [PLAN.md](PLAN.md) 与 [AGENTS.md](AGENTS.md)。
