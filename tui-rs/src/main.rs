use color_eyre::Result;
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind, KeyModifiers},
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
    ExecutableCommand,
};
use ratatui::{prelude::*, widgets::*};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

// ── JSON-RPC types ──────────────────────────────────────────────────────────

#[derive(Serialize)]
struct JsonRpcRequest {
    jsonrpc: String,
    method: String,
    params: serde_json::Value,
    id: u64,
}

#[derive(Deserialize, Debug)]
struct JsonRpcResponse {
    id: Option<u64>,
    result: Option<serde_json::Value>,
    error: Option<JsonRpcError>,
}

#[derive(Deserialize, Debug)]
#[allow(dead_code)]
struct JsonRpcError {
    code: i64,
    message: String,
}

#[derive(Deserialize, Debug)]
struct JsonRpcNotify {
    #[serde(default)]
    method: String,
    #[serde(default)]
    params: Option<serde_json::Value>,
}

#[derive(Debug)]
enum GatewayMsg {
    Response { id: u64, data: serde_json::Value },
    Error { id: u64, message: String },
    Event { event_type: String, session_id: Option<String>, payload: Option<serde_json::Value> },
    Disconnected,
}

// ── Gateway process manager ─────────────────────────────────────────────────

#[allow(dead_code)]
struct GatewayProcess {
    child: Child,
    cmd_tx: mpsc::Sender<String>,
    msg_rx: mpsc::Receiver<GatewayMsg>,
}

impl GatewayProcess {
    fn spawn() -> Result<Self> {
        let home = dirs::home_dir().unwrap_or_default();
        let project_root = home.join(".rewired").join("rewired");
        let venv_python = project_root.join("venv").join("bin").join("python3");

        let mut child = Command::new(&venv_python)
            .arg("-m")
            .arg("tui_gateway.entry")
            .current_dir(&project_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .env("REWIRED_HOME", home.join(".rewired"))
            .env("PYTHONPATH", &project_root)
            .spawn()
            .map_err(|e| color_eyre::eyre::eyre!("Failed to spawn gateway: {}", e))?;

        let child_stdin = child.stdin.take().unwrap();
        let child_stdout = child.stdout.take().unwrap();

        let (cmd_tx, cmd_rx): (mpsc::Sender<String>, mpsc::Receiver<String>) = mpsc::channel();
        let (msg_tx, msg_rx): (mpsc::Sender<GatewayMsg>, mpsc::Receiver<GatewayMsg>) = mpsc::channel();

        // Thread: write commands to gateway stdin
        thread::spawn(move || {
            let mut stdin = child_stdin;
            for cmd in cmd_rx {
                if writeln!(stdin, "{}", cmd).is_err() {
                    break;
                }
                let _ = stdin.flush();
            }
        });

        // Thread: read JSON-RPC from gateway stdout
        thread::spawn(move || {
            let reader = BufReader::new(child_stdout);
            for line in reader.lines() {
                let line = match line {
                    Ok(l) => l,
                    Err(_) => break,
                };
                let trimmed = line.trim().to_string();
                if trimmed.is_empty() {
                    continue;
                }

                if let Ok(resp) = serde_json::from_str::<JsonRpcResponse>(&trimmed) {
                    if let Some(id) = resp.id {
                        if let Some(data) = resp.result {
                            let _ = msg_tx.send(GatewayMsg::Response { id, data });
                        } else if let Some(err) = resp.error {
                            let _ = msg_tx.send(GatewayMsg::Error { id, message: err.message });
                        }
                    }
                    continue;
                }

                if let Ok(notify) = serde_json::from_str::<JsonRpcNotify>(&trimmed) {
                    if notify.method == "event" {
                        if let Some(params) = notify.params {
                            let event_type = params.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
                            let session_id = params.get("session_id").and_then(|v| v.as_str()).map(|s| s.to_string());
                            let payload = params.get("payload").cloned();
                            let _ = msg_tx.send(GatewayMsg::Event { event_type, session_id, payload });
                        }
                    }
                }
            }
            let _ = msg_tx.send(GatewayMsg::Disconnected);
        });

        Ok(GatewayProcess { child, cmd_tx, msg_rx })
    }

    fn send(&self, method: &str, params: serde_json::Value, id: u64) {
        let req = JsonRpcRequest {
            jsonrpc: "2.0".to_string(),
            method: method.to_string(),
            params,
            id,
        };
        if let Ok(json) = serde_json::to_string(&req) {
            let _ = self.cmd_tx.send(json);
        }
    }

    fn try_recv(&self) -> Option<GatewayMsg> {
        self.msg_rx.try_recv().ok()
    }
}

// ── Chat types ──────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct ChatMessage {
    role: String,
    text: String,
}

#[derive(Debug, Clone)]
struct SessionInfo {
    id: String,
    title: String,
    preview: String,
    message_count: u64,
}

// ── App ─────────────────────────────────────────────────────────────────────

struct App {
    next_id: u64,
    pending_calls: HashMap<u64, String>,

    session_id: Option<String>,
    messages: Vec<ChatMessage>,
    input: String,
    cursor_pos: usize,

    sessions: Vec<SessionInfo>,
    show_sessions: bool,
    session_cursor: usize,
    session_filter: String,

    voice_recording: bool,
    voice_pending: bool,
    show_voice_modal: bool,
    voice_mic_available: Option<bool>,
    voice_modal_cursor: usize,
    voice_url: Option<String>,
    status: String,
    streaming_text: String,
    exit: bool,
}

impl App {
    fn new() -> Self {
        App {
            next_id: 1,
            pending_calls: HashMap::new(),
            session_id: None,
            messages: Vec::new(),
            input: String::new(),
            cursor_pos: 0,
            sessions: vec![],
            show_sessions: false,
            session_cursor: 0,
            session_filter: String::new(),
            voice_recording: false,
            voice_pending: false,
            show_voice_modal: false,
            voice_mic_available: None,
            voice_modal_cursor: 0,
            voice_url: None,
            status: "Starting...".into(),
            streaming_text: String::new(),
            exit: false,
        }
    }

    fn rpc_id(&mut self) -> u64 {
        let id = self.next_id;
        self.next_id += 1;
        id
    }

    fn send(&mut self, gw: &GatewayProcess, method: &str, params: serde_json::Value) -> u64 {
        let id = self.rpc_id();
        self.pending_calls.insert(id, method.to_string());
        gw.send(method, params, id);
        id
    }

    fn create_session(&mut self, gw: &GatewayProcess) {
        self.send(gw, "session.create", serde_json::json!({}));
        self.status = "Creating session...".into();
    }

    fn submit_prompt(&mut self, gw: &GatewayProcess) {
        let text = self.input.trim().to_string();
        if text.is_empty() {
            return;
        }

        if text.starts_with('/') {
            self.handle_slash(gw, &text);
            return;
        }

        self.input.clear();
        self.cursor_pos = 0;
        self.streaming_text.clear();

        self.messages.push(ChatMessage {
            role: "user".into(),
            text: text.clone(),
        });

        if let Some(ref sid) = self.session_id.clone() {
            self.send(gw, "prompt.submit", serde_json::json!({
                "session_id": sid,
                "text": text,
            }));
            self.status = "Waiting for response...".into();
        }
    }

    fn handle_slash(&mut self, gw: &GatewayProcess, cmd: &str) {
        let parts: Vec<&str> = cmd.split_whitespace().collect();
        let command = parts[0].to_lowercase();

        match command.as_str() {
            "/help" | "/h" => {
                self.messages.push(ChatMessage {
                    role: "system".into(),
                    text: "Commands:\n  /sessions  Browse previous sessions\n  /voice     Toggle voice mode\n  /clear     Clear chat\n  /quit      Exit\n  /help      Show this help".into(),
                });
            }
            "/sessions" | "/s" => {
                self.send(gw, "session.list", serde_json::json!({"limit": 50}));
                self.show_sessions = true;
                self.session_cursor = 0;
                self.session_filter.clear();
            }
            "/voice" | "/v" => {
                self.input.clear();
                self.cursor_pos = 0;
                self.voice_url = None;
                self.voice_mic_available = None;
                self.show_voice_modal = true;
                self.voice_modal_cursor = 0;
                self.status = "Checking microphone...".into();
                self.send(gw, "voice.toggle", serde_json::json!({"action": "status"}));
            }
            "/clear" => {
                self.messages.clear();
            }
            "/quit" | "/exit" | "/q" => {
                self.exit = true;
            }
            _ => {
                if let Some(ref sid) = self.session_id.clone() {
                    self.send(gw, "slash.exec", serde_json::json!({
                        "session_id": sid,
                        "command": cmd,
                    }));
                }
            }
        }
    }

    fn toggle_voice(&mut self, gw: &GatewayProcess) {
        if self.voice_pending {
            return;
        }
        self.voice_recording = !self.voice_recording;
        let action = if self.voice_recording { "start" } else { "stop" };
        let sid = self.session_id.clone();
        self.send(gw, "voice.record", serde_json::json!({
            "action": action,
            "session_id": sid,
        }));
        if self.voice_recording {
            self.status = "🎤 Listening...".into();
        } else {
            self.voice_pending = true;
            self.status = "Processing voice...".into();
        }
    }

    fn refresh_sessions(&mut self, gw: &GatewayProcess) {
        self.send(gw, "session.list", serde_json::json!({"limit": 50}));
    }

    fn resume_session(&mut self, gw: &GatewayProcess, session_id: &str) {
        self.show_sessions = false;
        self.send(gw, "session.resume", serde_json::json!({
            "session_id": session_id,
        }));
        let short = &session_id[..session_id.len().min(8)];
        self.status = format!("Resuming session {}...", short);
    }
}

// ── UI ──────────────────────────────────────────────────────────────────────

fn ui(frame: &mut Frame, app: &App) {
    if app.messages.is_empty() {
        render_centered(frame, app);
    } else {
        render_chat(frame, app);
    }
    if app.show_sessions {
        render_sessions_overlay(frame, app);
    }
    if app.show_voice_modal {
        // Dim the background
        let area = frame.area();
        frame.render_widget(
            Paragraph::new("").style(Style::default().bg(Color::Rgb(10, 10, 18))),
            area,
        );
        render_voice_modal(frame, app);
    }
}

fn render_centered(frame: &mut Frame, app: &App) {
    let area = frame.area();

    let prefix = if app.voice_recording { "🎤 " } else { "> " };
    let display = format!("{}{}", prefix, app.input);
    let input_width = display.len().min(80) as u16;
    let input_x = (area.width.saturating_sub(input_width)) / 2;
    let input_y = area.height / 2;

    // Small brand above input
    let brand = "rewired";
    let brand_x = (area.width.saturating_sub(brand.len() as u16)) / 2;
    let brand_y = input_y.saturating_sub(3);
    let brand_area = Rect { x: brand_x, y: brand_y, width: brand.len() as u16, height: 1 };
    frame.render_widget(
        Paragraph::new(Line::from(Span::styled(brand, Style::default().fg(Color::Cyan).bold()))),
        brand_area,
    );

    // Input line — bare, no border
    let input_area = Rect { x: input_x, y: input_y, width: input_width, height: 1 };
    frame.render_widget(
        Paragraph::new(display.as_str()).style(Style::default().fg(Color::White)),
        input_area,
    );

    // Cursor
    let cursor_x = input_x + prefix.len() as u16 + app.cursor_pos as u16;
    frame.set_cursor_position(Position::new(cursor_x, input_y));

    // Hint
    let hint = "type a message  |  /help for commands  |  Tab: sessions  |  Ctrl+C: quit";
    let hint_x = (area.width.saturating_sub(hint.len() as u16)) / 2;
    let hint_y = input_y + 2;
    frame.render_widget(
        Paragraph::new(Line::from(Span::styled(hint, Style::default().fg(Color::DarkGray)))),
        Rect { x: hint_x, y: hint_y, width: hint.len() as u16, height: 1 },
    );
}

fn render_chat(frame: &mut Frame, app: &App) {
    let area = frame.area();

    let vert = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(1),
        Constraint::Length(1),
    ]);
    let parts = vert.split(area);

    // Chat messages
    let chat_lines: Vec<Line> = app
        .messages
        .iter()
        .flat_map(|m| {
            let style = match m.role.as_str() {
                "user" => Style::default().fg(Color::Green),
                "assistant" => Style::default().fg(Color::White),
                _ => Style::default().fg(Color::DarkGray),
            };
            let prefix = match m.role.as_str() {
                "user" => "> ",
                "assistant" => "  ",
                _ => "",
            };
            vec![Line::from(vec![
                Span::styled(prefix, style),
                Span::styled(&m.text, style),
            ])]
        })
        .collect();

    frame.render_widget(Paragraph::new(chat_lines), parts[0]);

    // Separator
    let sep = "─".repeat(area.width as usize);
    frame.render_widget(
        Paragraph::new(Line::from(Span::styled(sep, Style::default().fg(Color::DarkGray)))),
        parts[1],
    );

    // Input line — bare, no border, at bottom
    let prefix = if app.voice_recording { "🎤 " } else { "> " };
    let display = format!("{}{}", prefix, app.input);
    frame.render_widget(
        Paragraph::new(display.as_str()).style(Style::default().fg(Color::White)),
        parts[2],
    );

    // Cursor
    let cursor_x = 0 + prefix.len() as u16 + app.cursor_pos as u16;
    let cursor_y = parts[2].y;
    frame.set_cursor_position(Position::new(cursor_x.min(area.width), cursor_y));
}

fn render_voice_modal(frame: &mut Frame, app: &App) {
    let area = frame.area();

    let (items, title_str, title_color) = match app.voice_mic_available {
        None => (
            vec!["Cancel"],
            " Checking microphone... ",
            Color::Yellow,
        ),
        Some(true) => (
            vec!["Start recording", "Close"],
            " Microphone detected ",
            Color::Green,
        ),
        Some(false) => (
            vec!["Start remote voice relay", "Close"],
            " No local microphone ",
            Color::Yellow,
        ),
    };

    let w = 56.min(area.width.saturating_sub(4));
    let h = items.len() as u16 + 6;
    let x = (area.width - w) / 2;
    let y = (area.height - h) / 2;

    let bg = Paragraph::new("").style(Style::default().bg(Color::Rgb(20, 20, 30)));
    frame.render_widget(bg, Rect { x, y, width: w, height: h });

    let title = Line::from(Span::styled(
        title_str,
        Style::default().fg(title_color).bold(),
    ));
    frame.render_widget(&title, Rect { x: x + 2, y: y + 1, width: w.saturating_sub(4), height: 1 });

    for (i, item) in items.iter().enumerate() {
        let style = if i == app.voice_modal_cursor {
            Style::default().fg(Color::Black).bg(Color::Cyan)
        } else {
            Style::default().fg(Color::White)
        };
        frame.render_widget(
            Paragraph::new(Line::from(Span::styled(
                format!("  {}  ", item),
                style,
            ))),
            Rect {
                x: x + 2,
                y: y + 3 + i as u16,
                width: w.saturating_sub(4),
                height: 1,
            },
        );
    }

    let hint = Line::from(Span::styled(
        "↑↓ navigate  |  Enter select  |  Esc close",
        Style::default().fg(Color::DarkGray),
    ));
    frame.render_widget(hint, Rect {
        x: x + 2,
        y: y + h.saturating_sub(2),
        width: w.saturating_sub(4),
        height: 1,
    });
}

fn render_sessions_overlay(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let overlay_w = area.width.saturating_sub(10).min(60);
    let overlay_h = area.height.saturating_sub(6).min(20);
    let overlay_x = (area.width - overlay_w) / 2;
    let overlay_y = (area.height - overlay_h) / 2;
    let overlay_area = Rect { x: overlay_x, y: overlay_y, width: overlay_w, height: overlay_h };

    // Dim background
    frame.render_widget(
        Paragraph::new("").style(Style::default().bg(Color::Rgb(10, 10, 18))),
        area,
    );

    let bg = Paragraph::new("").style(Style::default().bg(Color::Rgb(20, 20, 30)));
    frame.render_widget(bg, overlay_area);

    let title = Line::from(Span::styled(
        " Sessions ",
        Style::default().fg(Color::Cyan).bold(),
    ));
    frame.render_widget(&title, Rect {
        x: overlay_x + 2,
        y: overlay_y + 1,
        width: overlay_w.saturating_sub(4),
        height: 1,
    });

    let rows: Vec<Row> = app.sessions.iter().enumerate().map(|(i, s)| {
        let style = if i == app.session_cursor {
            Style::default().fg(Color::Black).bg(Color::Cyan)
        } else {
            Style::default().fg(Color::White)
        };
        let title = if s.title.is_empty() { &s.preview } else { &s.title };
        let t: String = title.chars().take(30).collect();
        let id: String = s.id.chars().take(12).collect();
        Row::new(vec![
            Cell::from(Span::styled(format!("{:>3}", i + 1), style)),
            Cell::from(Span::styled(t, style)),
            Cell::from(Span::styled(format!("{} msgs", s.message_count), style)),
            Cell::from(Span::styled(id, style)),
        ])
    }).collect();

    let header = ["  #", "Title", "Msgs", "ID"];
    let hc: Vec<Cell> = header.iter().map(|h|
        Cell::from(Span::styled(*h, Style::default().fg(Color::Cyan).bold()))
    ).collect();

    let mut all = vec![Row::new(hc).style(Style::default().bg(Color::Rgb(20, 20, 40)))];
    all.extend(rows);

    let table = Table::new(all, [
        Constraint::Length(4), Constraint::Min(10), Constraint::Length(10), Constraint::Length(14),
    ]);

    frame.render_widget(table, Rect {
        x: overlay_x + 2,
        y: overlay_y + 3,
        width: overlay_w.saturating_sub(4),
        height: overlay_h.saturating_sub(4),
    });
}

// ── Event processing ────────────────────────────────────────────────────────

fn process_gateway_msg(app: &mut App, msg: GatewayMsg) {
    match msg {
        GatewayMsg::Response { id, data } => {
            let method = app.pending_calls.remove(&id).unwrap_or_default();
            match method.as_str() {
                "session.create" | "session.resume" => {
                    if let Some(sid) = data.get("session_id").and_then(|v| v.as_str()) {
                        app.session_id = Some(sid.to_string());
                        app.status = "Ready".into();
                    }
                }
                "session.list" => {
                    if let Some(sessions) = data.get("sessions").and_then(|v| v.as_array()) {
                        app.sessions = sessions
                            .iter()
                            .filter_map(|s| {
                                Some(SessionInfo {
                                    id: s.get("id")?.as_str()?.to_string(),
                                    title: s.get("title").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                    preview: s.get("preview").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                    message_count: s.get("message_count").and_then(|v| v.as_u64()).unwrap_or(0),
                                })
                            })
                            .collect();
                        if app.sessions.is_empty() {
                            app.status = "No sessions found".into();
                        }
                    }
                }
                "slash.exec" => {
                    if let Some(output) = data.get("output").and_then(|v| v.as_str()) {
                        if !output.is_empty() {
                            app.messages.push(ChatMessage {
                                role: "system".into(),
                                text: output.to_string(),
                            });
                        }
                    }
                }
                "voice.toggle" => {
                    app.voice_mic_available = data.get("audio_available").and_then(|v| v.as_bool());
                    if app.show_voice_modal {
                        app.status = "Voice ready".into();
                    }
                }
                "voice.remote" => {
                    if let Some(url) = data.get("url").and_then(|v| v.as_str()) {
                        let host_port = data.get("host_port").and_then(|v| v.as_str()).unwrap_or(url);
                        app.voice_url = Some(url.to_string());
                        app.messages.push(ChatMessage {
                            role: "system".into(),
                            text: format!("🌐 Remote voice relay started!\n\nRun on your local machine:\n  rewired-voice-client {}", host_port),
                        });
                        app.status = "Remote voice ready".into();
                    } else if let Some(err) = data.get("error").and_then(|v| v.as_str()) {
                        app.status = format!("Remote voice error: {}", err);
                    }
                }
                _ => {}
            }
        }
        GatewayMsg::Error { id, message } => {
            app.pending_calls.remove(&id);
            app.status = format!("Error: {}", message);
        }
        GatewayMsg::Event { event_type, session_id: _sid, payload } => {
            match event_type.as_str() {
                "gateway.ready" => {
                    app.status = "Connected!".into();
                }
                "message.start" => {
                    app.streaming_text.clear();
                }
                "message.delta" => {
                    if let Some(ref p) = payload {
                        if let Some(text) = p.get("text").and_then(|v| v.as_str()) {
                            app.streaming_text.push_str(text);
                            let s = app.streaming_text.clone();
                            if let Some(last) = app.messages.last_mut() {
                                if last.role == "assistant" {
                                    last.text = s;
                                }
                            } else {
                                app.messages.push(ChatMessage {
                                    role: "assistant".into(),
                                    text: s,
                                });
                            }
                        }
                    }
                }
                "message.complete" => {
                    let final_text = app.streaming_text.clone();
                    if !final_text.is_empty() {
                        if let Some(last) = app.messages.last_mut() {
                            if last.role == "assistant" {
                                last.text = final_text;
                            }
                        }
                    } else if let Some(ref p) = payload {
                        if let Some(text) = p.get("text").and_then(|v| v.as_str()) {
                            app.messages.push(ChatMessage {
                                role: "assistant".into(),
                                text: text.to_string(),
                            });
                        }
                    }
                    app.streaming_text.clear();
                    app.status = "Ready".into();
                }
                "voice.transcript" => {
                    if let Some(ref p) = payload {
                        if let Some(text) = p.get("text").and_then(|v| v.as_str()) {
                            app.input = text.to_string();
                            // Will be submitted on next event loop tick
                        } else if p.get("no_speech_limit").is_some() {
                            app.status = "No speech detected".into();
                        }
                    }
                }
                "voice.status" => {
                    if let Some(ref p) = payload {
                        let state = p.get("state").and_then(|v| v.as_str()).unwrap_or("");
                        app.status = format!("🎤 {}", state);
                    }
                }
                "session.info" => {
                    let model = payload
                        .as_ref()
                        .and_then(|p| p.get("model").and_then(|v| v.as_str()))
                        .unwrap_or("unknown");
                    app.status = format!("Ready ({})", model);
                }
                "error" => {
                    let msg = payload
                        .as_ref()
                        .and_then(|p| p.get("message").and_then(|v| v.as_str()))
                        .unwrap_or("unknown error");
                    app.status = format!("Error: {}", msg);
                }
                _ => {}
            }
        }
        GatewayMsg::Disconnected => {
            app.status = "Gateway disconnected".into();
            app.exit = true;
        }
    }
}

fn handle_key(app: &mut App, gw: &GatewayProcess, key: crossterm::event::KeyEvent) {
    if app.show_voice_modal {
        let max_index = match app.voice_mic_available {
            None => 0,
            Some(_) => 1,
        };
        match key.code {
            KeyCode::Up => {
                app.voice_modal_cursor = app.voice_modal_cursor.saturating_sub(1);
            }
            KeyCode::Down => {
                if app.voice_modal_cursor < max_index {
                    app.voice_modal_cursor += 1;
                }
            }
            KeyCode::Enter => {
                match app.voice_mic_available {
                    None => {
                        // Still checking — close
                        app.show_voice_modal = false;
                    }
                    Some(true) => {
                        match app.voice_modal_cursor {
                            0 => {
                                // Start local recording
                                app.show_voice_modal = false;
                                app.toggle_voice(gw);
                            }
                            1 => {
                                // Close
                                app.show_voice_modal = false;
                            }
                            _ => {}
                        }
                    }
                    Some(false) => {
                        match app.voice_modal_cursor {
                            0 => {
                                // Start remote voice relay
                                app.show_voice_modal = false;
                                app.status = "Starting remote voice relay...".into();
                                app.send(gw, "voice.remote", serde_json::json!({
                                    "session_id": app.session_id,
                                }));
                            }
                            1 => {
                                // Close
                                app.show_voice_modal = false;
                            }
                            _ => {}
                        }
                    }
                }
            }
            KeyCode::Esc => {
                app.show_voice_modal = false;
            }
            _ => {}
        }
        return;
    }
    if app.show_sessions {
        match key.code {
            KeyCode::Up => {
                app.session_cursor = app.session_cursor.saturating_sub(1);
            }
            KeyCode::Down => {
                let max = app.sessions.len().saturating_sub(1);
                if app.session_cursor < max {
                    app.session_cursor += 1;
                }
            }
            KeyCode::Enter => {
                let session_id = app.sessions.get(app.session_cursor).map(|s| s.id.clone());
                if let Some(sid) = session_id {
                    app.resume_session(gw, &sid);
                }
            }
            KeyCode::Esc => {
                app.show_sessions = false;
            }
            KeyCode::Char(c) => {
                app.session_filter.push(c);
                let filter = app.session_filter.to_lowercase();
                if let Some(pos) = app.sessions.iter().position(|s| {
                    s.title.to_lowercase().contains(&filter)
                        || s.id.to_lowercase().contains(&filter)
                }) {
                    app.session_cursor = pos;
                }
            }
            KeyCode::Backspace => {
                app.session_filter.pop();
            }
            _ => {}
        }
        return;
    }

    match key.code {
        KeyCode::Char(c) => {
            if c == 'c' && key.modifiers.contains(KeyModifiers::CONTROL) {
                app.exit = true;
                return;
            }
            app.input.insert(app.cursor_pos, c);
            app.cursor_pos += 1;
        }
        KeyCode::Backspace => {
            if app.cursor_pos > 0 {
                app.cursor_pos -= 1;
                app.input.remove(app.cursor_pos);
            }
        }
        KeyCode::Delete => {
            if app.cursor_pos < app.input.len() {
                app.input.remove(app.cursor_pos);
            }
        }
        KeyCode::Left => {
            app.cursor_pos = app.cursor_pos.saturating_sub(1);
        }
        KeyCode::Right => {
            if app.cursor_pos < app.input.len() {
                app.cursor_pos += 1;
            }
        }
        KeyCode::Home => {
            app.cursor_pos = 0;
        }
        KeyCode::End => {
            app.cursor_pos = app.input.len();
        }
        KeyCode::Enter => {
            app.submit_prompt(gw);
        }
        KeyCode::Esc => {
            if app.input.is_empty() {
                app.exit = true;
            } else {
                app.input.clear();
                app.cursor_pos = 0;
            }
        }
        KeyCode::Tab => {
            app.handle_slash(gw, "/sessions");
        }
        _ => {}
    }
}

// ── Main ────────────────────────────────────────────────────────────────────

fn main() -> Result<()> {
    color_eyre::install()?;
    enable_raw_mode()?;
    let mut stdout = std::io::stdout();
    stdout.execute(EnterAlternateScreen)?;

    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    terminal.clear()?;

    let mut app = App::new();

    let gw = match GatewayProcess::spawn() {
        Ok(g) => {
            app.status = "Connected to gateway".into();
            g
        }
        Err(e) => {
            app.messages.push(ChatMessage {
                role: "system".into(),
                text: format!("Failed to start gateway: {}.", e),
            });
            app.status = "No gateway".into();
            let res = run_offline(&mut terminal, &mut app);
            disable_raw_mode()?;
            terminal.backend_mut().execute(LeaveAlternateScreen)?;
            terminal.show_cursor()?;
            return res;
        }
    };

    let res = run(&mut terminal, &mut app, &gw);

    disable_raw_mode()?;
    terminal.backend_mut().execute(LeaveAlternateScreen)?;
    terminal.show_cursor()?;

    if let Some(ref sid) = app.session_id {
        gw.send("session.close", serde_json::json!({"session_id": sid}), app.rpc_id());
    }

    println!("Goodbye!");
    res
}

fn run<B: Backend>(terminal: &mut Terminal<B>, app: &mut App, gw: &GatewayProcess) -> Result<()> {
    // Create session on startup
    app.create_session(gw);

    while !app.exit {
        terminal.draw(|frame| ui(frame, app))?;

        // Process gateway messages
        while let Some(msg) = gw.try_recv() {
            process_gateway_msg(app, msg);
        }

        // Handle voice auto-submit after recording stops
        if app.voice_pending {
            if !app.input.is_empty() {
                app.submit_prompt(gw);
            }
            app.voice_pending = false;
            app.voice_recording = false;
        }

        // Keyboard input
        if event::poll(Duration::from_millis(50))? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    handle_key(app, gw, key);
                }
            }
        }
    }
    Ok(())
}

fn run_offline<B: Backend>(terminal: &mut Terminal<B>, app: &mut App) -> Result<()> {
    while !app.exit {
        terminal.draw(|frame| ui(frame, app))?;
        if event::poll(Duration::from_millis(50))? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    match key.code {
                        KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                            app.exit = true;
                        }
                        KeyCode::Esc => {
                            app.exit = true;
                        }
                        _ => {}
                    }
                }
            }
        }
    }
    Ok(())
}
