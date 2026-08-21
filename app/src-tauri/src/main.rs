#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use std::path::Path;
use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use uuid::Uuid;

struct SidecarState(Mutex<Option<CommandChild>>);

#[derive(Clone, serde::Serialize)]
struct RuntimeConfig {
    api_base: String,
    process_key: String,
}

#[tauri::command]
fn runtime_config(config: tauri::State<'_, RuntimeConfig>) -> RuntimeConfig {
    config.inner().clone()
}

const MAX_EXPORT_BYTES: usize = 64 * 1024 * 1024;

fn write_export_file(path: &Path, bytes: &[u8]) -> Result<(), String> {
    std::fs::write(path, bytes).map_err(|error| format!("无法保存文件：{error}"))
}

fn validate_export(file_name: &str, content_type: &str, bytes: &[u8]) -> Result<String, String> {
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
    let expected_type = match extension.as_str() {
        "pdf" => "application/pdf",
        "csv" => "text/csv",
        "txt" | "log" | "sam" => "text/plain",
        _ => return Err("只允许保存 PDF、CSV、TXT、LOG 或 SAM 文件".to_string()),
    };
    if content_type != expected_type {
        return Err("文件扩展名与内容类型不匹配".to_string());
    }
    if bytes.is_empty() || bytes.len() > MAX_EXPORT_BYTES {
        return Err("文件内容为空或超过 64 MiB 限制".to_string());
    }
    if extension == "pdf" && !bytes.starts_with(b"%PDF-") {
        return Err("PDF 文件头无效".to_string());
    }
    if extension != "pdf" && bytes.contains(&0) {
        return Err("文本导出包含不允许的 NUL 字节".to_string());
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
        .manage(runtime)
        .invoke_handler(tauri::generate_handler![runtime_config, save_export_file])
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
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
                stop_sidecar(app);
                app.exit(0);
            }
            RunEvent::ExitRequested { .. } | RunEvent::Exit => stop_sidecar(app),
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::{parse_development_api_base, validate_export, write_export_file};
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
    fn export_rejects_paths_mismatched_types_and_invalid_content() {
        assert!(validate_export("curve.pdf", "application/pdf", b"%PDF-1.4\ncontent").is_ok());
        assert!(validate_export("values.csv", "text/csv", b"x,y\n1,2\n").is_ok());
        assert!(validate_export("queue.sam", "text/plain", b"sample\r\n").is_ok());
        assert!(validate_export("../curve.pdf", "application/pdf", b"%PDF-1.4\ncontent").is_err());
        assert!(validate_export("curve.txt", "application/pdf", b"%PDF-1.4\ncontent").is_err());
        assert!(validate_export("curve.pdf", "application/pdf", b"not a pdf").is_err());
        assert!(validate_export("data.exe", "text/plain", b"data").is_err());
        assert!(validate_export("empty.csv", "text/csv", b"").is_err());
    }

    #[test]
    fn export_writer_persists_exact_bytes() {
        let path = std::env::temp_dir().join(format!(
            "geospectrum-export-{}.txt",
            Uuid::new_v4().as_simple()
        ));
        let content = b"GeoSpectrum export\r\n";
        write_export_file(&path, content).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), content);
        std::fs::remove_file(path).unwrap();
    }
}
