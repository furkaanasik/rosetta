//! Rosetta desktop shell: spawns the Python engine sidecar and hands its address to the UI.

use std::sync::Mutex;

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

#[derive(Default)]
struct EngineState {
    info: Mutex<Option<EngineInfo>>,
    error: Mutex<Option<String>>,
    child: Mutex<Option<CommandChild>>,
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

/// Dev override: ROSETTA_ENGINE_URL (+ ROSETTA_ENGINE_TOKEN) points at a manually started engine.
fn dev_override() -> Option<EngineInfo> {
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
    let command = match app.shell().sidecar("rosetta-engine") {
        Ok(c) => c.args(["serve", "--port", "0", "--token", token.as_str()]),
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
                    set_error(&handle, format!("Motor durdu (kod {:?})", status.code));
                    break;
                }
                _ => {}
            }
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(EngineState::default())
        .invoke_handler(tauri::generate_handler![engine_info])
        .setup(|app| {
            start_engine(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Rosetta başlatılamadı")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                let child = app
                    .state::<EngineState>()
                    .child
                    .lock()
                    .ok()
                    .and_then(|mut c| c.take());
                if let Some(child) = child {
                    let _ = child.kill();
                }
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
    fn token_is_64_hex_chars() {
        let t = random_token();
        assert_eq!(t.len(), 64);
        assert!(t.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(t, random_token());
    }
}
