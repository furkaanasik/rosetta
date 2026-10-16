//! Rosetta desktop shell: spawns the Python engine sidecar and hands its address to the UI.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Where the frontend reaches the engine.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineInfo {
    pub base_url: String,
    pub token: String,
}

/// First PDF given on the command line (`rosetta kitap.pdf`, or `%f` from the .desktop file).
pub fn pdf_from_args<I, S>(args: I, cwd: &std::path::Path) -> Option<String>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    args.into_iter().skip(1).find_map(|raw| {
        let raw = raw.as_ref();
        let decoded;
        let raw = match raw.strip_prefix("file://") {
            Some(rest) => {
                // file:///p or file://localhost/p; percent-encoded per RFC 8089.
                let rest = rest.strip_prefix("localhost").unwrap_or(rest);
                decoded = percent_decode(rest);
                decoded.as_str()
            }
            None => raw,
        };
        if raw.starts_with('-') || !raw.to_ascii_lowercase().ends_with(".pdf") {
            return None;
        }
        let path = std::path::Path::new(raw);
        let abs = if path.is_absolute() { path.to_path_buf() } else { cwd.join(path) };
        abs.is_file().then(|| abs.to_string_lossy().into_owned())
    })
}

/// Decodes `%XX` escapes (UTF-8); malformed escapes are kept as-is.
pub fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).ok();
            if let Some(b) = hex.and_then(|h| u8::from_str_radix(h, 16).ok()) {
                out.push(b);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// PDF waiting to be opened: the launch argument, then the latest second-instance hand-over.
/// The frontend drains it on startup and whenever it receives the `open-pdf` signal, so a
/// hand-over that arrives before the frontend listens is never lost.
#[derive(Default)]
struct OpenState {
    pending: Mutex<Option<String>>,
}

/// The PDF waiting to be opened (taken once).
#[tauri::command]
fn initial_pdf(state: State<'_, OpenState>) -> Option<String> {
    state.pending.lock().ok().and_then(|mut p| p.take())
}

/// Rosetta's own folders that "Klasörü aç" may open: data and config dirs (XDG or overridden by
/// ROSETTA_DATA_DIR / ROSETTA_CONFIG_DIR), and anything below them. Nothing else.
pub fn allowed_folder_roots() -> Vec<std::path::PathBuf> {
    use std::path::PathBuf;
    let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default();
    let xdg = |var: &str, fallback: &str| {
        std::env::var_os(var)
            .map(PathBuf::from)
            .filter(|p| p.is_absolute())
            .unwrap_or_else(|| home.join(fallback))
    };
    let mut roots = vec![
        xdg("XDG_DATA_HOME", ".local/share").join("rosetta"),
        xdg("XDG_CONFIG_HOME", ".config").join("rosetta"),
    ];
    for var in ["ROSETTA_DATA_DIR", "ROSETTA_CONFIG_DIR"] {
        if let Some(p) = std::env::var_os(var).map(PathBuf::from).filter(|p| p.is_absolute()) {
            roots.push(p);
        }
    }
    roots
}

/// True when `path` (canonicalised) is an existing directory inside one of `roots`.
pub fn folder_allowed(path: &std::path::Path, roots: &[std::path::PathBuf]) -> bool {
    let Ok(real) = path.canonicalize() else { return false };
    real.is_dir()
        && roots
            .iter()
            .filter_map(|r| r.canonicalize().ok())
            .any(|root| real.starts_with(root))
}

/// Opens one of Rosetta's own folders in the file manager (xdg-open).
#[tauri::command]
fn open_folder(path: String) -> Result<(), String> {
    let p = std::path::Path::new(&path);
    if !folder_allowed(p, &allowed_folder_roots()) {
        return Err("Bu klasör açılamaz".into());
    }
    std::process::Command::new("xdg-open")
        .arg(p)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("Dosya yöneticisi açılamadı: {e}"))
}

#[derive(Default)]
struct EngineState {
    info: Mutex<Option<EngineInfo>>,
    error: Mutex<Option<String>>,
    child: Mutex<Option<CommandChild>>,
    terminated: AtomicBool,
    exiting: AtomicBool,
}

#[derive(Deserialize)]
struct ReadyLine {
    port: u16,
    token: String,
}

/// Parses the sidecar's first stdout line: `{"port": 41234, "token": "..."}`.
pub fn parse_ready_line(line: &str) -> Option<EngineInfo> {
    let ready: ReadyLine = serde_json::from_str(line.trim()).ok()?;
    if ready.port == 0 {
        return None;
    }
    Some(EngineInfo {
        base_url: format!("http://127.0.0.1:{}", ready.port),
        token: ready.token,
    })
}

/// 32 random bytes, hex encoded.
pub fn random_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::fill(&mut buf).expect("OS random source unavailable");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

/// Dev override (debug builds only): ROSETTA_ENGINE_URL (+ ROSETTA_ENGINE_TOKEN) points at a
/// manually started engine.
fn dev_override() -> Option<EngineInfo> {
    if !cfg!(debug_assertions) {
        return None;
    }
    let url = std::env::var("ROSETTA_ENGINE_URL").ok()?;
    Some(EngineInfo {
        base_url: url.trim_end_matches('/').to_string(),
        token: std::env::var("ROSETTA_ENGINE_TOKEN").unwrap_or_default(),
    })
}

#[tauri::command]
fn engine_info(state: State<'_, EngineState>) -> Result<Option<EngineInfo>, String> {
    if let Some(err) = state.error.lock().map_err(|e| e.to_string())?.clone() {
        return Err(err);
    }
    Ok(state.info.lock().map_err(|e| e.to_string())?.clone())
}

fn set_error(app: &AppHandle, msg: String) {
    if app.state::<EngineState>().exiting.load(Ordering::SeqCst) {
        return;
    }
    eprintln!("rosetta: {msg}");
    if let Ok(mut e) = app.state::<EngineState>().error.lock() {
        *e = Some(msg.clone());
    }
    let _ = app.emit("engine-error", msg);
}

fn set_info(app: &AppHandle, info: EngineInfo) {
    if let Ok(mut slot) = app.state::<EngineState>().info.lock() {
        *slot = Some(info.clone());
    }
    let _ = app.emit("engine-ready", info);
}

fn start_engine(app: &AppHandle) {
    if let Some(info) = dev_override() {
        set_info(app, info);
        return;
    }
    let token = random_token();
    // The token goes through the environment (owner-only /proc/<pid>/environ), never argv.
    // A process group lets shutdown reach the Python process behind the PyInstaller bootloader;
    // the engine also exits on its own when our end of its stdin closes (e.g. if we crash).
    let command = match app.shell().sidecar("rosetta-engine") {
        Ok(c) => c
            .args(["serve", "--port", "0"])
            .env("ROSETTA_SERVE_TOKEN", token.as_str())
            .set_process_group(true),
        Err(e) => return set_error(app, format!("Motor bulunamadı: {e}")),
    };
    let (mut rx, child) = match command.spawn() {
        Ok(pair) => pair,
        Err(e) => return set_error(app, format!("Motor başlatılamadı: {e}")),
    };
    if let Ok(mut slot) = app.state::<EngineState>().child.lock() {
        *slot = Some(child);
    }

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut pending = String::new();
        let mut ready = false;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    pending.push_str(&String::from_utf8_lossy(&bytes));
                    if !pending.ends_with('\n') && !ready && parse_ready_line(&pending).is_none() {
                        continue;
                    }
                    for line in pending.lines() {
                        if ready {
                            continue;
                        }
                        if let Some(info) = parse_ready_line(line) {
                            if info.token != token {
                                set_error(&handle, "Motor beklenmeyen bir token bildirdi".into());
                            } else {
                                ready = true;
                                set_info(&handle, info);
                            }
                        }
                    }
                    pending.clear();
                }
                CommandEvent::Stderr(bytes) => {
                    eprint!("rosetta-engine: {}", String::from_utf8_lossy(&bytes));
                }
                CommandEvent::Error(e) => set_error(&handle, format!("Motor hatası: {e}")),
                CommandEvent::Terminated(status) => {
                    handle.state::<EngineState>().terminated.store(true, Ordering::SeqCst);
                    set_error(&handle, format!("Motor durdu (kod {:?})", status.code));
                    break;
                }
                _ => {}
            }
        }
    });
}

/// Graceful shutdown: SIGTERM to the engine's process group, a short wait, then SIGKILL.
fn stop_engine(app: &AppHandle) {
    let state = app.state::<EngineState>();
    state.exiting.store(true, Ordering::SeqCst);
    let Some(child) = state.child.lock().ok().and_then(|mut c| c.take()) else {
        return;
    };
    #[cfg(unix)]
    {
        let pgid = child.pid() as libc::pid_t;
        // SAFETY: plain signal delivery to the group we created for the sidecar.
        unsafe { libc::killpg(pgid, libc::SIGTERM) };
        let deadline = Instant::now() + Duration::from_millis(2000);
        while Instant::now() < deadline && !state.terminated.load(Ordering::SeqCst) {
            std::thread::sleep(Duration::from_millis(50));
        }
    }
    // Reaps the bootloader and SIGKILLs anything left in the group.
    let _ = child.kill();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let cwd = std::env::current_dir().unwrap_or_default();
    let initial = pdf_from_args(std::env::args(), &cwd);
    tauri::Builder::default()
        // A second launch (e.g. "Open with Rosetta" while running) hands its PDF to this window.
        .plugin(tauri_plugin_single_instance::init(|app, argv, cwd| {
            if let Some(path) = pdf_from_args(argv, std::path::Path::new(&cwd)) {
                if let Ok(mut slot) = app.state::<OpenState>().pending.lock() {
                    *slot = Some(path);
                }
                // Signal only; the frontend drains the path with `initial_pdf`.
                let _ = app.emit("open-pdf", ());
            }
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(EngineState::default())
        .manage(OpenState { pending: Mutex::new(initial) })
        .invoke_handler(tauri::generate_handler![engine_info, initial_pdf, open_folder])
        .setup(|app| {
            start_engine(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Rosetta başlatılamadı")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_engine(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_line() {
        let info = parse_ready_line("{\"port\": 41234, \"token\": \"abc\"}\n").unwrap();
        assert_eq!(info.base_url, "http://127.0.0.1:41234");
        assert_eq!(info.token, "abc");
    }

    #[test]
    fn rejects_garbage_and_port_zero() {
        assert!(parse_ready_line("INFO starting").is_none());
        assert!(parse_ready_line("{\"port\": 0, \"token\": \"x\"}").is_none());
    }

    #[test]
    fn pdf_from_args_picks_first_existing_pdf() {
        let dir = std::env::temp_dir().join(format!("rosetta-args-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("kitap.pdf"), b"%PDF-1.4").unwrap();
        let abs = dir.join("kitap.pdf").to_string_lossy().into_owned();

        assert_eq!(pdf_from_args(["rosetta", "kitap.pdf"], &dir), Some(abs.clone()));
        assert_eq!(pdf_from_args(["rosetta", &format!("file://{abs}")], &dir), Some(abs.clone()));
        assert_eq!(pdf_from_args(["rosetta", "--flag", "kitap.pdf"], &dir), Some(abs));
        assert_eq!(pdf_from_args(["rosetta", "yok.pdf"], &dir), None);
        assert_eq!(pdf_from_args(["rosetta", "notes.txt"], &dir), None);
        assert_eq!(pdf_from_args(["rosetta"], &dir), None);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn file_uri_is_percent_decoded() {
        let dir = std::env::temp_dir().join(format!("rosetta args sp {}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("Kitap Adı.pdf"), b"%PDF-1.4").unwrap();
        let abs = dir.join("Kitap Adı.pdf").to_string_lossy().into_owned();
        let uri = format!(
            "file://{}",
            abs.replace(' ', "%20").replace('ı', "%C4%B1")
        );
        assert_eq!(pdf_from_args(["rosetta", &uri], &dir), Some(abs.clone()));
        let localhost = uri.replacen("file://", "file://localhost", 1);
        assert_eq!(pdf_from_args(["rosetta", &localhost], &dir), Some(abs));
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn percent_decode_keeps_malformed_escapes() {
        assert_eq!(percent_decode("a%20b"), "a b");
        assert_eq!(percent_decode("100%"), "100%");
        assert_eq!(percent_decode("%zz%4"), "%zz%4");
    }

    #[test]
    fn token_is_64_hex_chars() {
        let t = random_token();
        assert_eq!(t.len(), 64);
        assert!(t.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(t, random_token());
    }

    #[test]
    fn open_folder_only_inside_rosetta_roots() {
        let base = std::env::temp_dir().join(format!("rosetta-roots-{}", std::process::id()));
        let root = base.join("data/rosetta");
        let inside = root.join("out");
        let outside = base.join("elsewhere");
        std::fs::create_dir_all(&inside).unwrap();
        std::fs::create_dir_all(&outside).unwrap();
        let roots = vec![root.clone()];
        assert!(folder_allowed(&root, &roots));
        assert!(folder_allowed(&inside, &roots));
        assert!(!folder_allowed(&outside, &roots));
        assert!(!folder_allowed(&inside.join("../../.."), &roots));
        assert!(!folder_allowed(&base.join("missing"), &roots));
        std::fs::remove_dir_all(&base).unwrap();
    }
}
