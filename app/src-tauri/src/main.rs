#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! GeoSpectrum 桌面边界：启动和停止本地 API sidecar，只暴露运行时握手与
//! 已校验的文件保存命令，并将后端限制在 IPv4 回环地址。
//! 项目根目录的《项目阅读指南.md》说明了该边界与 Python、React 层的关系。

use std::net::TcpListener;
use std::path::Path;
use std::sync::Mutex;
use std::io::{Read, Write};
use std::time::Duration;
use tauri::{Manager, RunEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind, MessageDialogResult};
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use uuid::Uuid;
mod open_location;
use open_location::OpenLocation;

struct SidecarState(Mutex<Option<CommandChild>>);
struct OpenLocationState(Mutex<OpenLocation>);
#[derive(Default)]
enum ExitState {
    #[default]
    Idle,
    Checking,
    Authorized(ExitAuthorization),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ExitAuthorization {
    NoOwnedSidecar,
    DeviceStopConfirmed,
    ForcedByOperator,
}

enum ExitDecision {
    Exit(ExitAuthorization),
    CheckInstrument(String),
}

#[derive(Clone, serde::Serialize)]
struct RuntimeConfig {
    api_base: String,
    process_key: String,
}

#[tauri::command]
fn runtime_config(config: tauri::State<'_, RuntimeConfig>) -> RuntimeConfig {
    config.inner().clone()
}

// Only this fixed Settings page can be launched; the WebView supplies no URI,
// executable or command-line arguments.
#[tauri::command]
fn open_bluetooth_settings() -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        #[link(name = "shell32")]
        extern "system" {
            fn ShellExecuteW(window: *mut std::ffi::c_void, operation: *const u16,
                file: *const u16, parameters: *const u16, directory: *const u16, show: i32) -> isize;
        }
        let operation: Vec<u16> = "open\0".encode_utf16().collect();
        let uri: Vec<u16> = "ms-settings:bluetooth\0".encode_utf16().collect();
        let result = unsafe { ShellExecuteW(std::ptr::null_mut(), operation.as_ptr(), uri.as_ptr(),
                                           std::ptr::null(), std::ptr::null(), 1) };
        if result <= 32 { return Err("无法打开 Windows 蓝牙设置，请从开始菜单打开设置 → 蓝牙和设备".into()); }
        Ok(())
    }
    #[cfg(not(target_os = "windows"))]
    { Err("此功能需要 Windows 蓝牙设置".into()) }
}

const MAX_EXPORT_BYTES: usize = 64 * 1024 * 1024;

fn write_export_file(path: &Path, bytes: &[u8]) -> Result<(), String> {
    std::fs::write(path, bytes).map_err(|error| format!("无法保存文件：{error}"))
}

fn validate_export(file_name: &str, _content_type: &str, bytes: &[u8]) -> Result<String, String> {
    // 显示原生对话框前先校验调用方可控的元数据。
    // 目录由用户选择，WebView 只能提供安全的叶子文件名。
    let trimmed = file_name.trim();
    let leaf_name = Path::new(trimmed)
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "文件名无效".to_string())?;
    if trimmed.is_empty()
        || leaf_name != trimmed
        || matches!(trimmed, "." | "..")
        || trimmed.chars().any(|value| "<>:\"/\\|?*".contains(value))
    {
        return Err("文件名必须是不含目录和保留字符的叶子名称".to_string());
    }
    let extension = Path::new(trimmed)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !matches!(extension.as_str(), "pdf" | "csv" | "json" | "xls" | "xlsx" | "txt" | "log" | "sam") {
        return Err("只允许保存 PDF、CSV、TXT、LOG、SAM、JSON、XLS 或 XLSX 文件".to_string());
    }
    if bytes.is_empty() || bytes.len() > MAX_EXPORT_BYTES {
        return Err("文件内容为空或超过 64 MiB 限制".to_string());
    }
    if extension == "pdf" && !bytes.starts_with(b"%PDF-") {
        return Err("PDF 文件头无效".to_string());
    }
    Ok(extension)
}

#[tauri::command]
async fn save_export_file(
    app: tauri::AppHandle,
    file_name: String,
    content_type: String,
    bytes: Vec<u8>,
) -> Result<Option<String>, String> {
    let extension = validate_export(&file_name, &content_type, &bytes)?;
    let selected = app
        .dialog()
        .file()
        .set_title("保存 GeoSpectrum 文件")
        .set_file_name(file_name)
        .add_filter("GeoSpectrum 导出", &[extension.as_str()])
        .blocking_save_file();
    let Some(selected) = selected else {
        return Ok(None);
    };
    let path = selected
        .into_path()
        .map_err(|error| format!("无法解析保存路径：{error}"))?;
    write_export_file(&path, &bytes)?;
    Ok(Some(path.to_string_lossy().into_owned()))
}

#[tauri::command]
async fn select_backup_directory(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let selected = app.dialog().file().set_title("选择备份目录").blocking_pick_folder();
    selected.map(|value| value.into_path()
        .map(|path| path.to_string_lossy().into_owned())
        .map_err(|error| format!("无法读取备份目录路径：{error}"))).transpose()
}

#[tauri::command]
async fn select_legacy_directory(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let state = app.state::<OpenLocationState>();
    let mut location = state.0.lock().map_err(|_| "文件目录状态不可用")?;
    let mut dialog = app.dialog().file().set_title("选择程序或数据目录");
    if let Some(directory) = location.directory() { dialog = dialog.set_directory(directory); }
    let selected = dialog.blocking_pick_folder().map(|value| value.into_path()
        .map_err(|error| format!("无法读取目录路径：{error}"))).transpose()?;
    location.remember(selected.as_deref());
    Ok(selected.map(|path| path.to_string_lossy().into_owned()))
}

#[tauri::command]
async fn select_legacy_files(app: tauri::AppHandle, extensions: Vec<String>, multiple: bool) -> Result<Vec<String>, String> {
    let allowed = ["mtd", "cdt", "cmt", "edt", "wdt", "pdt", "dat", "sam", "txt"];
    if extensions.is_empty() || extensions.iter().any(|ext| !allowed.contains(&ext.as_str())) {
        return Err("不支持的文件类型".to_string());
    }
    let filters: Vec<&str> = extensions.iter().map(String::as_str).collect();
    select_files(&app, &filters, multiple)
}

fn select_files(app: &tauri::AppHandle, extensions: &[&str], multiple: bool) -> Result<Vec<String>, String> {
    let state = app.state::<OpenLocationState>();
    let mut location = state.0.lock().map_err(|_| "文件目录状态不可用")?;
    let mut dialog = app.dialog().file().set_title("打开文件").add_filter("兼容数据文件", extensions);
    if let Some(directory) = location.directory() { dialog = dialog.set_directory(directory); }
    let selected = if multiple { dialog.blocking_pick_files().unwrap_or_default() }
        else { dialog.blocking_pick_file().into_iter().collect() };
    let paths: Vec<std::path::PathBuf> = selected.into_iter().map(|file| file.into_path()
        .map_err(|error| format!("无法读取文件路径：{error}"))).collect::<Result<_, _>>()?;
    location.remember(paths.last().map(|path| path.as_path()));
    Ok(paths.into_iter()
        .map(|path| path.to_string_lossy().into_owned())
        .collect())
}

#[derive(serde::Serialize)]
struct SampleFile { name: String, bytes: Vec<u8>, last_modified: u64 }

const SAMPLE_FILE_EXTENSIONS: &[&str] = &["sam", "txt", "xlsx"];

#[tauri::command]
async fn select_sample_file(app: tauri::AppHandle) -> Result<Option<SampleFile>, String> {
    let paths = select_files(&app, SAMPLE_FILE_EXTENSIONS, false)?;
    let Some(selected) = paths.first() else { return Ok(None) };
    read_sample_file(Path::new(selected)).map(Some)
}

fn read_sample_file(path: &Path) -> Result<SampleFile, String> {
    let extension = path.extension().and_then(|value| value.to_str()).unwrap_or_default().to_ascii_lowercase();
    if !SAMPLE_FILE_EXTENSIONS.contains(&extension.as_str()) { return Err("请选择 Excel、SAM 或 TXT 样品号文件".into()); }
    let metadata = path.metadata().map_err(|error| format!("无法读取样品号文件：{error}"))?;
    let limit = if extension == "xlsx" { 5_000_000 } else { MAX_EXPORT_BYTES };
    if metadata.len() > limit as u64 { return Err("样品号文件过大".into()); }
    let bytes = std::fs::read(path).map_err(|error| format!("无法读取样品号文件：{error}"))?;
    if bytes.len() > limit { return Err("样品号文件过大".into()); }
    let last_modified = metadata.modified().ok()
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|duration| duration.as_millis() as u64).unwrap_or(0);
    Ok(SampleFile { name: path.file_name().unwrap_or_default().to_string_lossy().into_owned(), bytes, last_modified })
}

fn reserve_loopback_port() -> Result<u16, std::io::Error> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

#[cfg(debug_assertions)]
fn parse_development_api_base(value: &str) -> Result<String, String> {
    let normalized = value.trim().trim_end_matches('/');
    let port = normalized
        .strip_prefix("http://127.0.0.1:")
        .ok_or_else(|| "GEOSPECTRUM_DEV_API_BASE must use http://127.0.0.1:<port>".to_string())?
        .parse::<u16>()
        .map_err(|_| "GEOSPECTRUM_DEV_API_BASE must contain a valid non-zero port".to_string())?;
    if port == 0 {
        return Err("GEOSPECTRUM_DEV_API_BASE must contain a valid non-zero port".to_string());
    }
    Ok(format!("http://127.0.0.1:{port}"))
}

#[cfg(debug_assertions)]
fn development_api_base() -> Result<Option<String>, String> {
    match std::env::var("GEOSPECTRUM_DEV_API_BASE") {
        Ok(value) => parse_development_api_base(&value).map(Some),
        Err(std::env::VarError::NotPresent) => Ok(None),
        Err(error) => Err(format!("unable to read GEOSPECTRUM_DEV_API_BASE: {error}")),
    }
}

#[cfg(not(debug_assertions))]
fn development_api_base() -> Result<Option<String>, String> {
    Ok(None)
}

fn stop_response(response: &str) -> Result<(), String> {
    #[derive(serde::Deserialize)]
    struct StopResponse {
        safe_to_exit: bool,
        #[serde(default)]
        errors: Vec<serde_json::Value>,
    }

    let (headers, body) = response.split_once("\r\n\r\n").ok_or("设备停止响应不完整")?;
    let mut lines = headers.lines();
    let mut status = lines.next().unwrap_or("").split_ascii_whitespace();
    if !matches!(status.next(), Some("HTTP/1.1" | "HTTP/1.0")) || status.next() != Some("200") {
        return Err("本地服务未确认设备停止".into());
    }
    for (key, value) in lines.filter_map(|line| line.split_once(':')) {
        if key.eq_ignore_ascii_case("content-length") && value.trim().parse::<usize>() != Ok(body.len()) {
            return Err("设备停止响应不完整".into());
        }
    }
    let result: StopResponse = serde_json::from_str(body).map_err(|_| "设备停止响应无效")?;
    if result.safe_to_exit && result.errors.is_empty() {
        Ok(())
    } else {
        Err(format!("设备停止未确认：{}", serde_json::Value::Array(result.errors)))
    }
}

fn decide_exit(config: &RuntimeConfig, has_child: bool, prepare: impl FnOnce() -> Result<(), String>) -> ExitDecision {
    if config.process_key.is_empty() {
        return if has_child {
            ExitDecision::CheckInstrument("无法验证配对后端的停机回执".into())
        } else {
            ExitDecision::Exit(ExitAuthorization::NoOwnedSidecar)
        };
    }
    match prepare() {
        Ok(()) => ExitDecision::Exit(ExitAuthorization::DeviceStopConfirmed),
        Err(error) => ExitDecision::CheckInstrument(error),
    }
}

const FORCE_EXIT_BUTTON: &str = "仍要强制退出";

fn operator_exit(result: MessageDialogResult) -> Option<ExitAuthorization> {
    match result {
        MessageDialogResult::Custom(label) if label == FORCE_EXIT_BUTTON => Some(ExitAuthorization::ForcedByOperator),
        _ => None,
    }
}

fn prepare_device_exit(config: &RuntimeConfig) -> Result<(), String> {
    let address = config.api_base.strip_prefix("http://").ok_or("本地服务地址无效")?
        .parse::<std::net::SocketAddr>().map_err(|_| "本地服务地址无效")?;
    if !address.ip().is_loopback() { return Err("本地服务地址必须为回环地址".into()); }
    let mut stream = std::net::TcpStream::connect_timeout(&address, Duration::from_secs(2))
        .map_err(|_| "本地服务不可用，请检查仪器是否已经停止")?;
    stream.set_read_timeout(Some(Duration::from_secs(180))).map_err(|error| error.to_string())?;
    stream.set_write_timeout(Some(Duration::from_secs(2))).map_err(|error| error.to_string())?;
    write!(stream, "POST /api/v1/devices/prepare-exit HTTP/1.1\r\nHost: {}\r\nX-GeoSpectrum-Process-Key: {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", address, config.process_key)
        .map_err(|error| error.to_string())?;
    const MAX_RESPONSE: usize = 65536;
    let mut response = String::new();
    stream.take((MAX_RESPONSE + 1) as u64).read_to_string(&mut response)
        .map_err(|_| "无法读取设备停止回执或等待超时")?;
    if response.len() > MAX_RESPONSE {
        return Err("设备停止响应超出长度限制".into());
    }
    stop_response(&response)
}

fn request_safe_exit(app: &tauri::AppHandle) {
    {
        let state = app.state::<Mutex<ExitState>>();
        let mut state = state.lock().unwrap();
        if !matches!(*state, ExitState::Idle) {
            return;
        }
        *state = ExitState::Checking;
    }
    let handle = app.clone();
    let config = app.state::<RuntimeConfig>().inner().clone();
    let has_child = app.state::<SidecarState>().0.lock().unwrap().is_some();
    std::thread::spawn(move || {
        let authorization = match decide_exit(&config, has_child, || prepare_device_exit(&config)) {
            ExitDecision::Exit(authorization) => Some(authorization),
            ExitDecision::CheckInstrument(error) => {
                let mut dialog = handle.dialog()
                    .message(format!("{error}\n请先在现场独立确认仪器已停机，再选择是否强制退出。"))
                    .title("无法确认设备已停止")
                    .kind(MessageDialogKind::Warning)
                    .buttons(MessageDialogButtons::YesNoCancelCustom(
                        "返回检查（默认）".into(), FORCE_EXIT_BUTTON.into(), "取消关闭".into(),
                    ));
                if let Some(window) = handle.get_webview_window("main") {
                    dialog = dialog.parent(&window);
                }
                operator_exit(dialog.blocking_show_with_result())
            }
        };
        let state = handle.state::<Mutex<ExitState>>();
        if let Some(authorization) = authorization {
            *state.lock().unwrap() = ExitState::Authorized(authorization);
            handle.exit(0);
        } else {
            *state.lock().unwrap() = ExitState::Idle;
        }
    });
}

fn stop_sidecar(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<SidecarState>() {
        if let Some(child) = state.0.lock().unwrap().take() {
            #[cfg(target_os = "windows")]
            {
                use std::os::windows::process::CommandExt;

                const CREATE_NO_WINDOW: u32 = 0x08000000;
                let pid = child.pid().to_string();
                let tree_stopped = std::process::Command::new("taskkill")
                    .args(["/PID", pid.as_str(), "/T", "/F"])
                    .creation_flags(CREATE_NO_WINDOW)
                    .status()
                    .map(|status| status.success())
                    .unwrap_or(false);
                if !tree_stopped {
                    let _ = child.kill();
                }
            }

            #[cfg(not(target_os = "windows"))]
            {
                let _ = child.kill();
            }
        }
    }
}

fn main() {
    let development_api_base =
        development_api_base().expect("invalid GeoSpectrum development API base");
    let (port, process_key, api_base) = match development_api_base {
        Some(api_base) => (None, String::new(), api_base),
        None => {
            // 绑定端口 0 让 Windows 分配空闲回环端口。监听器会在启动 sidecar 前释放，
            // 因此即使其他进程在短暂竞态中先占用端口，进程密钥仍是授权边界。
            let port = reserve_loopback_port().expect("unable to reserve a loopback port");
            (
                Some(port),
                Uuid::new_v4().as_simple().to_string(),
                format!("http://127.0.0.1:{port}"),
            )
        }
    };
    let runtime = RuntimeConfig {
        api_base,
        process_key: process_key.clone(),
    };
    tauri::Builder::default()
        .manage(SidecarState(Mutex::new(None)))
        .manage(Mutex::new(ExitState::default()))
        .manage(runtime)
        .invoke_handler(tauri::generate_handler![runtime_config, save_export_file, select_backup_directory, select_legacy_directory, select_legacy_files, select_sample_file, open_bluetooth_settings])
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            let preferences_dir = std::env::var_os("SPECTRUM_DATA_DIR").map(std::path::PathBuf::from)
                .unwrap_or(app.path().app_local_data_dir()?);
            app.manage(OpenLocationState(Mutex::new(OpenLocation::load(&preferences_dir))));
            let Some(port) = port else {
                return Ok(());
            };
            let port_argument = port.to_string();
            let explicit_data_dir = std::env::var_os("SPECTRUM_DATA_DIR");
            let data_dir = match explicit_data_dir.as_ref() {
                Some(path) => std::path::PathBuf::from(path),
                None => app.path().app_local_data_dir()?,
            };
            let mut sidecar_command = app
                .shell()
                .sidecar("geospectrum-backend")?
                .args(["--host", "127.0.0.1", "--port", port_argument.as_str()])
                .env("SPECTRUM_DATA_DIR", data_dir);
            if explicit_data_dir.is_none() {
                let legacy_data_dir = app.path().local_data_dir()?.join("GeoSpectrum");
                sidecar_command =
                    sidecar_command.env("GEOSPECTRUM_LEGACY_DATA_DIR", legacy_data_dir);
            }
            match sidecar_command.spawn() {
                Ok((_receiver, mut child)) => {
                    // 通过标准输入传递本次启动的密钥，避免它出现在进程命令行或持久化配置中。
                    if let Err(error) = child.write(format!("{process_key}\n").as_bytes()) {
                        let _ = child.kill();
                        return Err(error.into());
                    }
                    *app.state::<SidecarState>().0.lock().unwrap() = Some(child);
                }
                Err(error) => {
                    return Err(error.into());
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building GeoSpectrum")
        .run(|app, event| match event {
            RunEvent::WindowEvent { label, event, .. }
                if label == "main"
                    && matches!(event, tauri::WindowEvent::CloseRequested { .. }) =>
            {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    request_safe_exit(app);
                }
            }
            RunEvent::ExitRequested { api, .. } => {
                let state = app.state::<Mutex<ExitState>>();
                let authorization = match *state.lock().unwrap() {
                    ExitState::Authorized(authorization) => Some(authorization),
                    _ => None,
                };
                match authorization {
                    Some(ExitAuthorization::DeviceStopConfirmed | ExitAuthorization::ForcedByOperator) => stop_sidecar(app),
                    Some(ExitAuthorization::NoOwnedSidecar) => {}
                    None => {
                        api.prevent_exit();
                        request_safe_exit(app);
                    }
                }
            }
            RunEvent::Exit => stop_sidecar(app),
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::{decide_exit, operator_exit, parse_development_api_base, read_sample_file, stop_response,
                validate_export, write_export_file, ExitAuthorization, ExitDecision, RuntimeConfig,
                FORCE_EXIT_BUTTON, MAX_EXPORT_BYTES};
    use tauri_plugin_dialog::MessageDialogResult;
    use uuid::Uuid;

    #[test]
    fn development_api_base_accepts_only_explicit_ipv4_loopback() {
        assert_eq!(
            parse_development_api_base(" http://127.0.0.1:8787/ ").unwrap(),
            "http://127.0.0.1:8787"
        );
        assert!(parse_development_api_base("http://localhost:8787").is_err());
        assert!(parse_development_api_base("http://192.168.1.10:8787").is_err());
        assert!(parse_development_api_base("https://127.0.0.1:8787").is_err());
        assert!(parse_development_api_base("http://127.0.0.1:0").is_err());
    }

    #[test]
    fn native_exit_requires_an_explicit_successful_device_stop_response() {
        assert!(stop_response("HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{\"safe_to_exit\":true,\"errors\":[]}").is_ok());
        assert!(stop_response("HTTP/1.1 200 OK\r\n\r\n{\"safe_to_exit\":false,\"errors\":[\"stop_unconfirmed\"]}").is_err());
        assert!(stop_response("HTTP/1.1 403 Forbidden\r\n\r\n{\"safe_to_exit\":true}").is_err());
        assert!(stop_response("HTTP/1.1 200 OK\r\n\r\n{}").is_err());
        assert!(stop_response("HTTP/1.1 200 OK\r\n\r\npartial").is_err());
        assert!(stop_response("HTTP/1.1 200\r\n\r\n{\"safe_to_exit\":true}").is_ok());
        assert!(stop_response("HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{\"safe_to_exit\":true}").is_err());
        assert!(stop_response("HTTP/1.1 200 OK\r\n\r\n{\"safe_to_exit\":\"true\"}").is_err());
        assert!(stop_response("HTTP/1.1 200 OK\r\n\r\n{\"safe_to_exit\":true,\"errors\":[{}]}").is_err());
        assert!(stop_response("HTTP/1.1 200 OK\r\n\r\n{\"safe_to_exit\":false,\"safe_to_exit\":true}").is_err());
    }

    #[test]
    fn native_exit_distinguishes_external_safe_and_operator_forced_exit() {
        let mut config = RuntimeConfig { api_base: String::new(), process_key: String::new() };
        assert!(matches!(decide_exit(&config, false, || panic!("external backend called")),
                         ExitDecision::Exit(ExitAuthorization::NoOwnedSidecar)));
        assert!(matches!(decide_exit(&config, true, || panic!("missing process key")),
                         ExitDecision::CheckInstrument(_)));
        config.process_key = "owned".into();
        assert!(matches!(decide_exit(&config, true, || Ok(())),
                         ExitDecision::Exit(ExitAuthorization::DeviceStopConfirmed)));
        assert!(matches!(decide_exit(&config, true, || Err("timeout".into())),
                         ExitDecision::CheckInstrument(error) if error == "timeout"));
        for response in [MessageDialogResult::Cancel, MessageDialogResult::No,
                         MessageDialogResult::Custom("返回检查（默认）".into())] {
            assert_eq!(operator_exit(response), None);
        }
        assert_eq!(operator_exit(MessageDialogResult::Custom(FORCE_EXIT_BUTTON.into())),
                   Some(ExitAuthorization::ForcedByOperator));
    }

    #[test]
    fn export_validates_leaf_name_extension_size_and_pdf_header() {
        assert!(validate_export("curve.pdf", "application/pdf", b"%PDF-1.4\ncontent").is_ok());
        for name in ["", ".", "..", "../curve.pdf", "folder\\curve.pdf", "bad:name.pdf"] {
            assert!(validate_export(name, "application/pdf", b"%PDF-1.4\ncontent").is_err(), "{name:?}");
        }
        assert!(validate_export("curve.pdf", "application/pdf", b"not a pdf").is_err());
        assert!(validate_export("data.exe", "text/plain", b"data").is_err());
        assert!(validate_export("empty.csv", "text/csv", b"").is_err());
        let bytes = vec![0; MAX_EXPORT_BYTES + 1];
        assert!(validate_export("limit.csv", "text/csv", &bytes[..MAX_EXPORT_BYTES]).is_ok());
        assert!(validate_export("oversize.csv", "text/csv", &bytes).is_err());
    }

    #[test]
    fn non_pdf_exports_accept_payloads_without_inspecting_content() {
        for extension in ["csv", "json", "xls", "xlsx", "txt", "log", "sam"] {
            let file_name = format!("export.{}", extension.to_ascii_uppercase());
            assert_eq!(
                validate_export(&file_name, "application/octet-stream", b"export\0bytes").unwrap(),
                extension
            );
        }
    }

    #[test]
    fn export_writer_persists_exact_bytes() {
        let path = std::env::temp_dir().join(format!(
            "geospectrum-export-{}.txt",
            Uuid::new_v4().as_simple()
        ));
        let content = b"GeoSpectrum export\r\n";
        validate_export("export.txt", "text/plain", content).unwrap();
        write_export_file(&path, content).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), content);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn sample_reader_preserves_source_and_rejects_wrong_type_or_oversize() {
        let root = std::env::temp_dir().join(format!("geospectrum-sample-{}", Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let path = root.join("样品.SAM");
        let bytes = "样品甲,2\r\n".as_bytes();
        std::fs::write(&path, bytes).unwrap();
        let before = path.metadata().unwrap().modified().unwrap();
        let file = read_sample_file(&path).unwrap();
        assert_eq!(file.name, "样品.SAM"); assert_eq!(file.bytes, bytes);
        assert_eq!(path.metadata().unwrap().modified().unwrap(), before);
        assert_eq!(file.last_modified, before.duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as u64);
        assert!(read_sample_file(&root.join("other.json")).is_err());
        std::fs::File::create(&path).unwrap().set_len(MAX_EXPORT_BYTES as u64 + 1).unwrap();
        assert!(read_sample_file(&path).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
