# Tauri 与发布链导读

## 1. 涉及文件

| 文件 | 职责 |
|---|---|
| [`src-tauri/src/main.rs`](../../app/src-tauri/src/main.rs) | 桌面主进程、sidecar 生命周期、运行时配置、文件保存和退出清理 |
| [`backend/sidecar_entry.py`](../../app/backend/sidecar_entry.py) | 冻结后端入口、进程密钥读取、数据目录准备和 Uvicorn 启动 |
| [`backend/upgrade.py`](../../app/backend/upgrade.py) | 旧数据目录复制、数据库稳定快照、副本升级、校验和原子切换 |
| [`tools/build_sidecar.py`](../../app/tools/build_sidecar.py) | 使用 PyInstaller 构建后端 sidecar |
| [`tools/verify_sidecar.py`](../../app/tools/verify_sidecar.py) | 校验资源、健康、业务调用和进程退出 |
| [`tools/build_release_manifest.py`](../../app/tools/build_release_manifest.py) | 生成内部发布清单并检查门禁 |

## 2. 桌面启动顺序

```text
Tauri main
  → 开发模式可读取 GEOSPECTRUM_DEV_API_BASE
  → 正式模式在 127.0.0.1 上申请随机端口
  → 生成 32 位十六进制进程密钥
  → 确定应用数据目录
  → 启动 geospectrum-backend sidecar
  → 通过标准输入写入进程密钥
  → 前端通过 runtime_config 取得 api_base 和密钥
```

正式模式不把密钥放在命令行或磁盘配置中。sidecar 的 `_read_process_key()` 限制最大读取长度并校验格式；读取失败时不会启动 API。

## 3. 数据目录

优先级如下：

1. 显式 `SPECTRUM_DATA_DIR`，用于开发和测试。
2. Tauri 的 `app_local_data_dir()`，正式位置为 `%LOCALAPPDATA%\cn.geospectrum.desktop`。

若使用正式目录，Tauri 还把旧 `%LOCALAPPDATA%\GeoSpectrum` 作为 `GEOSPECTRUM_LEGACY_DATA_DIR` 传给 sidecar。迁移逻辑只复制已知运行数据，旧目录保持不变。

## 4. 数据库升级为何在导入 main 之前

`sidecar_entry.py` 先调用 `prepare_legacy_data_directory()` 和 `prepare_database_upgrade()`，之后才导入 `backend.main`。R1 保留这个顺序，并通过 `Runtime(AppConfig(...), process_key=...)` 和 `create_app(runtime=...)` 创建独立应用；不再写入 main 的进程密钥全局变量。应用工厂只装配对象，数据库初始化在 Uvicorn 启动 lifespan 时执行，保证它发生在升级准备之后。

升级过程：

1. 连续比较 DB 与 WAL 哈希，取得稳定只读快照。
2. 检查完整性、外键和 schema 版本。
3. 创建升级前备份和暂存数据库。
4. 在暂存副本执行 `Database.initialize()`。
5. 再次检查完整性与目标版本。
6. 原子替换正式数据库。
7. 写入 `last-upgrade.json`。

失败时保留正式数据库，并在已经切换但后续检查失败时尝试恢复备份。

## 5. 文件保存安全边界

Tauri 只暴露 `runtime_config` 和 `save_export_file` 两个命令。保存流程先校验：

- 只能提供叶子文件名，不能含目录、路径穿越或 Windows 保留字符。
- 扩展名限于 PDF、CSV、TXT、LOG、SAM。
- 内容类型必须与扩展名匹配。
- 内容不能为空且不超过 64 MiB。
- PDF 必须以 `%PDF-` 开头。
- 文本不能包含 NUL 字节。

校验通过后才打开原生文件对话框。取消对话框返回 `None`，不应提示保存成功。

## 6. 退出和单实例

单实例插件在第二次启动时显示并聚焦主窗口。主窗口关闭、应用请求退出或真正退出时都会调用 `stop_sidecar()`。

Windows 上优先使用 `taskkill /T /F` 清理进程树，失败时再直接终止子进程，避免 PyInstaller 子进程残留。

## 7. 内部发布链

`npm.cmd run release:internal` 顺序执行：

1. 构建 sidecar。
2. 验证 sidecar 和冻结资源。
3. 执行 Tauri/NSIS 构建。
4. 生成内部测试发布清单。

运行资源通过 `backend/resources/resource-manifest.json` 记录字节数和 SHA-256，包括模拟 ACQ 文件及旧 Access 读取脚本。

## 8. 尚未关闭的外部门禁

- 代码签名证书。
- 干净 Windows 10/11 安装、升级和卸载复验。
- S14 自动转角真实协议和硬件证据。
- S15 汞灯真实协议和硬件证据。

因此当前构建只能视为未签名内部测试包，自动更新保持关闭。

## 9. 验证入口

```powershell
cd app
cargo test --manifest-path src-tauri/Cargo.toml
python -m pytest -p no:cacheprovider tests/test_tauri_contract.py tests/test_runtime_resources.py tests/test_s21_release.py
python tools/verify_sidecar.py
```
