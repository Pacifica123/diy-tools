use anyhow::{Context, Result};
use clap::Parser;
use regex::Regex;
use serde::Serialize;
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Instant;

const ANY: &str = "<*>";

#[derive(Parser, Debug)]
#[command(name = "log-miner")]
#[command(about = "Streaming log template miner for huge unknown log files")]
struct Cli {
    /// Путь к лог-файлу
    path: PathBuf,

    /// Порог похожести строки на уже найденный шаблон
    #[arg(long, default_value_t = 0.62)]
    threshold: f32,

    /// Максимальное число шаблонов, чтобы память не раздувалась бесконечно
    #[arg(long, default_value_t = 20_000)]
    max_patterns: usize,

    /// Сколько примеров строк хранить для каждого шаблона
    #[arg(long, default_value_t = 3)]
    examples: usize,

    /// Сколько самых частых шаблонов вывести в консоль
    #[arg(long, default_value_t = 50)]
    top: usize,

    /// Путь для JSON-отчёта
    #[arg(long)]
    json: Option<PathBuf>,

    /// Прогресс каждые N строк. 0 — отключить.
    #[arg(long, default_value_t = 1_000_000)]
    progress_lines: u64,
}

#[derive(Debug)]
struct Pattern {
    id: usize,
    tokens: Vec<String>,
    count: u64,
    first_line: u64,
    last_line: u64,
    examples: Vec<String>,
}

#[derive(Serialize)]
struct ReportPattern {
    id: usize,
    template: String,
    count: u64,
    first_line: u64,
    last_line: u64,
    examples: Vec<String>,
}

#[derive(Serialize)]
struct Report {
    file: String,
    total_lines: u64,
    total_bytes: u64,
    unique_patterns: usize,
    patterns: Vec<ReportPattern>,
}

struct Miner {
    threshold: f32,
    max_patterns: usize,
    examples_limit: usize,
    patterns: Vec<Pattern>,
    by_len: HashMap<usize, Vec<usize>>,
    overflow_pattern_id: Option<usize>,
}

impl Miner {
    fn new(threshold: f32, max_patterns: usize, examples_limit: usize) -> Self {
        Self {
            threshold,
            max_patterns,
            examples_limit,
            patterns: Vec::new(),
            by_len: HashMap::new(),
            overflow_pattern_id: None,
        }
    }

    fn observe(&mut self, line_no: u64, line: &str) {
        let tokens = tokenize(line);

        if tokens.is_empty() {
            return;
        }

        if let Some(id) = self.find_best_pattern(&tokens) {
            self.update_pattern(id, line_no, line, &tokens);
            return;
        }

        if self.patterns.len() < self.max_patterns {
            self.create_pattern(tokens, line_no, line);
        } else {
            let id = self.get_or_create_overflow_pattern(line_no, line);
            self.update_overflow_pattern(id, line_no, line);
        }
    }

    fn find_best_pattern(&self, tokens: &[String]) -> Option<usize> {
        let candidates = self.by_len.get(&tokens.len())?;
        let mut best: Option<(usize, f32)> = None;

        for &id in candidates {
            let p = &self.patterns[id];
            let score = similarity(&p.tokens, tokens);

            if score >= self.threshold {
                match best {
                    None => best = Some((id, score)),
                    Some((_, best_score)) if score > best_score => {
                        best = Some((id, score));
                    }
                    _ => {}
                }
            }
        }

        best.map(|(id, _)| id)
    }

    fn create_pattern(&mut self, tokens: Vec<String>, line_no: u64, line: &str) {
        let id = self.patterns.len();

        let mut examples = Vec::new();
        if self.examples_limit > 0 {
            examples.push(line.to_string());
        }

        self.patterns.push(Pattern {
            id,
            tokens: tokens.clone(),
            count: 1,
            first_line: line_no,
            last_line: line_no,
            examples,
        });

        self.by_len.entry(tokens.len()).or_default().push(id);
    }

    fn update_pattern(&mut self, id: usize, line_no: u64, line: &str, tokens: &[String]) {
        let p = &mut self.patterns[id];

        p.count += 1;
        p.last_line = line_no;

        for (dst, src) in p.tokens.iter_mut().zip(tokens.iter()) {
            if dst == src {
                continue;
            }

            if dst == ANY {
                continue;
            }

            *dst = ANY.to_string();
        }

        if p.examples.len() < self.examples_limit {
            p.examples.push(line.to_string());
        }
    }

    fn get_or_create_overflow_pattern(&mut self, line_no: u64, line: &str) -> usize {
        if let Some(id) = self.overflow_pattern_id {
            return id;
        }

        let id = self.patterns.len();

        let mut examples = Vec::new();
        if self.examples_limit > 0 {
            examples.push(line.to_string());
        }

        self.patterns.push(Pattern {
            id,
            tokens: vec!["<UNCLASSIFIED_AFTER_LIMIT>".to_string()],
            count: 0,
            first_line: line_no,
            last_line: line_no,
            examples,
        });

        self.overflow_pattern_id = Some(id);
        id
    }

    fn update_overflow_pattern(&mut self, id: usize, line_no: u64, line: &str) {
        let p = &mut self.patterns[id];

        p.count += 1;
        p.last_line = line_no;

        if p.examples.len() < self.examples_limit {
            p.examples.push(line.to_string());
        }
    }

    fn into_report_patterns(self) -> Vec<ReportPattern> {
        let mut out: Vec<_> = self
            .patterns
            .into_iter()
            .map(|p| ReportPattern {
                id: p.id,
                template: p.tokens.join(" "),
                count: p.count,
                first_line: p.first_line,
                last_line: p.last_line,
                examples: p.examples,
            })
            .collect();

        out.sort_by(|a, b| {
            b.count
                .cmp(&a.count)
                .then_with(|| a.template.cmp(&b.template))
        });

        out
    }
}

fn similarity(template: &[String], line: &[String]) -> f32 {
    if template.len() != line.len() || template.is_empty() {
        return 0.0;
    }

    let mut matched = 0usize;

    for (a, b) in template.iter().zip(line.iter()) {
        if a == ANY || a == b {
            matched += 1;
        }
    }

    matched as f32 / template.len() as f32
}

fn tokenize(line: &str) -> Vec<String> {
    line.split_whitespace().map(normalize_token).collect()
}

fn normalize_token(raw: &str) -> String {
    let token = raw.trim_matches(|c: char| matches!(c, ',' | ';' | '"' | '\''));

    if token.is_empty() {
        return ANY.to_string();
    }

    if let Some((key, value)) = token.split_once('=') {
        if looks_like_key(key) {
            if is_variable(value) {
                return format!("{}={}", key.to_ascii_lowercase(), ANY);
            }

            return format!(
                "{}={}",
                key.to_ascii_lowercase(),
                normalize_stable_word(value)
            );
        }
    }

    if is_timestamp(token) {
        return "<TS>".to_string();
    }

    if is_ipv4(token) {
        return "<IP>".to_string();
    }

    if is_uuid(token) {
        return "<UUID>".to_string();
    }

    if is_number(token) {
        return "<NUM>".to_string();
    }

    if is_hex_id(token) {
        return "<HEX>".to_string();
    }

    if is_url(token) {
        return "<URL>".to_string();
    }

    if is_path(token) {
        return "<PATH>".to_string();
    }

    if looks_like_mixed_id(token) {
        return "<ID>".to_string();
    }

    normalize_stable_word(token)
}

fn normalize_stable_word(s: &str) -> String {
    s.trim_matches(|c: char| matches!(c, '[' | ']' | '(' | ')' | '{' | '}'))
        .to_ascii_lowercase()
}

fn looks_like_key(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 40
        && s.chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == '.')
}

fn is_variable(s: &str) -> bool {
    is_timestamp(s)
        || is_ipv4(s)
        || is_uuid(s)
        || is_number(s)
        || is_hex_id(s)
        || is_url(s)
        || is_path(s)
        || looks_like_mixed_id(s)
}

fn is_timestamp(s: &str) -> bool {
    static RE: OnceLock<Regex> = OnceLock::new();

    RE.get_or_init(|| {
        Regex::new(
            r"(?x)
            ^\[?
            (
                \d{4}-\d{2}-\d{2}([tT ][0-9:.+-]+Z?)? |
                \d{2}:\d{2}:\d{2}([.,]\d+)? |
                \d{2}/\d{2}/\d{4}
            )
            \]?$
            ",
        )
        .unwrap()
    })
    .is_match(s)
}

fn is_ipv4(s: &str) -> bool {
    static RE: OnceLock<Regex> = OnceLock::new();

    RE.get_or_init(|| Regex::new(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$").unwrap())
        .is_match(s)
}

fn is_uuid(s: &str) -> bool {
    static RE: OnceLock<Regex> = OnceLock::new();

    RE.get_or_init(|| {
        Regex::new(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        )
        .unwrap()
    })
    .is_match(s)
}

fn is_number(s: &str) -> bool {
    static RE: OnceLock<Regex> = OnceLock::new();

    RE.get_or_init(|| Regex::new(r"^[+-]?\d+([.,]\d+)?(ms|s|m|h|kb|mb|gb|%)?$").unwrap())
        .is_match(s)
}

fn is_hex_id(s: &str) -> bool {
    static RE: OnceLock<Regex> = OnceLock::new();

    RE.get_or_init(|| Regex::new(r"^(0x)?[0-9a-fA-F]{8,}$").unwrap())
        .is_match(s)
}

fn is_url(s: &str) -> bool {
    s.starts_with("http://") || s.starts_with("https://")
}

fn is_path(s: &str) -> bool {
    let has_sep = s.contains('/') || s.contains('\\');
    has_sep && (s.len() > 12 || s.chars().any(|c| c.is_ascii_digit()))
}

fn looks_like_mixed_id(s: &str) -> bool {
    if s.len() < 6 || s.len() > 80 {
        return false;
    }

    let has_digit = s.chars().any(|c| c.is_ascii_digit());
    let has_alpha = s.chars().any(|c| c.is_ascii_alphabetic());

    let mostly_id_chars = s
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | ':' | '.'));

    has_digit && has_alpha && mostly_id_chars
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let started = Instant::now();

    if !(0.0..=1.0).contains(&cli.threshold) {
        anyhow::bail!("--threshold must be between 0.0 and 1.0");
    }

    if cli.max_patterns == 0 {
        anyhow::bail!("--max-patterns must be greater than zero");
    }

    let file = File::open(&cli.path)
        .with_context(|| format!("failed to open {}", cli.path.display()))?;

    let mut reader = BufReader::with_capacity(1024 * 1024, file);
    let mut buf = Vec::with_capacity(16 * 1024);

    let mut miner = Miner::new(cli.threshold, cli.max_patterns, cli.examples);

    let mut total_lines = 0u64;
    let mut total_bytes = 0u64;

    loop {
        buf.clear();

        let n = reader.read_until(b'\n', &mut buf)?;

        if n == 0 {
            break;
        }

        total_lines += 1;
        total_bytes += n as u64;

        while matches!(buf.last().copied(), Some(b'\n' | b'\r')) {
            buf.pop();
        }

        let line = String::from_utf8_lossy(&buf);
        miner.observe(total_lines, &line);

        if cli.progress_lines > 0 && total_lines % cli.progress_lines == 0 {
            eprintln!(
                "processed={} patterns={} elapsed={:.1}s",
                total_lines,
                miner.patterns.len(),
                started.elapsed().as_secs_f32()
            );
        }
    }

    let patterns = miner.into_report_patterns();

    println!("file: {}", cli.path.display());
    println!("lines: {total_lines}");
    println!("bytes: {total_bytes}");
    println!("patterns: {}", patterns.len());
    println!();
    println!("Top {} patterns:", cli.top.min(patterns.len()));

    for p in patterns.iter().take(cli.top) {
        println!(
            "#{} count={} first={} last={}",
            p.id, p.count, p.first_line, p.last_line
        );

        println!("  {}", p.template);

        if let Some(example) = p.examples.first() {
            println!("  example: {}", example);
        }

        println!();
    }

    if let Some(json_path) = cli.json {
        let report = Report {
            file: cli.path.display().to_string(),
            total_lines,
            total_bytes,
            unique_patterns: patterns.len(),
            patterns,
        };

        let out = File::create(&json_path)
            .with_context(|| format!("failed to create {}", json_path.display()))?;

        let mut writer = BufWriter::new(out);
        serde_json::to_writer_pretty(&mut writer, &report)?;
        writer.write_all(b"\n")?;

        eprintln!("json report written to {}", json_path.display());
    }

    Ok(())
}