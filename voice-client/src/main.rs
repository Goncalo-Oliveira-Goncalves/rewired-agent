use clap::Parser;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::Arc;
use std::time::Duration;

const SAMPLE_RATE: u32 = 16000;
const CHANNELS: u16 = 1;

#[derive(Parser)]
#[command(name = "rewired-voice-client", about = "Stream mic audio to a Rewired server")]
struct Args {
    /// Server address (host:port)
    server: String,
}

fn main() {
    let args = Args::parse();

    eprintln!("🎤 Initializing microphone...");

    let host = cpal::default_host();
    let device = match host.default_input_device() {
        Some(d) => d,
        None => {
            eprintln!("No input device found.");
            std::process::exit(1);
        }
    };

    let config = match device.default_input_config() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Failed to get default input config: {}", e);
            std::process::exit(1);
        }
    };

    eprintln!("Device: {}", device.name().unwrap_or_default());
    eprintln!("Press Enter to start recording, then press Enter again to stop and transcribe.");

    let mut input = String::new();
    std::io::stdin().read_line(&mut input).unwrap();

    eprintln!("🎤 Recording... Press Enter to stop.");

    let (tx, rx) = mpsc::channel::<Vec<i16>>();
    let running = Arc::new(AtomicBool::new(true));

    let stream = match config.sample_format() {
        cpal::SampleFormat::I16 => {
            device.build_input_stream(
                &config.into(),
                move |data: &[i16], _: &_| {
                    let _ = tx.send(data.to_vec());
                },
                |err| eprintln!("Audio error: {}", err),
                None,
            )
        }
        cpal::SampleFormat::F32 => {
            device.build_input_stream(
                &config.into(),
                move |data: &[f32], _: &_| {
                    let samples: Vec<i16> = data.iter().map(|&s| (s * 32767.0) as i16).collect();
                    let _ = tx.send(samples);
                },
                |err| eprintln!("Audio error: {}", err),
                None,
            )
        }
        _ => {
            eprintln!("Unsupported sample format");
            std::process::exit(1);
        }
    };

    match stream {
        Ok(s) => {
            s.play().unwrap();
            let _keep = s; // keep alive while recording

            let mut all_samples: Vec<i16> = Vec::new();

            // Read stdin on a background thread to detect Enter
            let running_clone = running.clone();
            std::thread::spawn(move || {
                let mut buf = String::new();
                std::io::stdin().read_line(&mut buf).unwrap();
                running_clone.store(false, Ordering::SeqCst);
            });

            // Collect samples until Enter is pressed
            while running.load(Ordering::SeqCst) {
                match rx.recv_timeout(Duration::from_millis(100)) {
                    Ok(samples) => all_samples.extend(samples),
                    Err(mpsc::RecvTimeoutError::Timeout) => {}
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }

            eprintln!(" Encoding and sending...");

            // Encode to WAV in memory
            let mut wav_data: Vec<u8> = Vec::new();
            {
                let spec = hound::WavSpec {
                    channels: CHANNELS,
                    sample_rate: SAMPLE_RATE,
                    bits_per_sample: 16,
                    sample_format: hound::SampleFormat::Int,
                };
                let mut writer = hound::WavWriter::new(std::io::Cursor::new(&mut wav_data), spec).unwrap();
                for &sample in &all_samples {
                    writer.write_sample(sample).unwrap();
                }
                writer.finalize().unwrap();
            }

            eprintln!(" WAV size: {} bytes, duration: {:.1}s", wav_data.len(), all_samples.len() as f64 / SAMPLE_RATE as f64);

            // Connect to server and send WAV via HTTP POST
            match TcpStream::connect(&args.server) {
                Ok(mut stream) => {
                    stream.set_read_timeout(Some(Duration::from_secs(30))).ok();
                    stream.set_write_timeout(Some(Duration::from_secs(10))).ok();

                    let request = format!(
                        "POST /transcribe HTTP/1.1\r\n\
                         Host: {}\r\n\
                         Content-Type: audio/wav\r\n\
                         Content-Length: {}\r\n\
                         Connection: close\r\n\
                         \r\n",
                        args.server, wav_data.len()
                    );

                    if let Err(e) = stream.write_all(request.as_bytes()) {
                        eprintln!(" Failed to send request: {}", e);
                        std::process::exit(1);
                    }
                    if let Err(e) = stream.write_all(&wav_data) {
                        eprintln!(" Failed to send audio: {}", e);
                        std::process::exit(1);
                    }
                    if let Err(e) = stream.flush() {
                        eprintln!(" Failed to flush: {}", e);
                        std::process::exit(1);
                    }

                    // Read response
                    let mut response = Vec::new();
                    match stream.read_to_end(&mut response) {
                        Ok(_) => {
                            let response_str = String::from_utf8_lossy(&response);
                            // Extract body after headers
                            if let Some(body_start) = response_str.find("\r\n\r\n") {
                                let body = &response_str[body_start + 4..];
                                println!("{}", body.trim());
                            } else {
                                eprintln!(" Unexpected response format");
                            }
                        }
                        Err(e) => {
                            eprintln!(" Failed to read response: {}", e);
                            std::process::exit(1);
                        }
                    }
                }
                Err(e) => {
                    eprintln!(" Failed to connect to {}: {}", args.server, e);
                    std::process::exit(1);
                }
            }
        }
        Err(e) => {
            eprintln!(" Failed to create audio stream: {}", e);
            std::process::exit(1);
        }
    }
}
