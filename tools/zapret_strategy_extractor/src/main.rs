use anyhow::{Context, Result};
use clap::Parser;
use regex::Regex;
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;
use std::sync::OnceLock;

#[derive(Parser, Debug)]
#[command(name = "zapret-strategy-extractor")]
#[command(about = "Extract successful/locked zapret 2 GUI orchestration strategies from huge logs")]
struct Cli {
    /// Path to the original orchestra_*.log file, not report.json.
    log: PathBuf,

    /// Output preset .txt file.
    #[arg(long, default_value = "locked_strategies_preset.txt")]
    preset_out: PathBuf,

    /// Output JSON stats file.
    #[arg(long, default_value = "strategy_stats.json")]
    stats_out: PathBuf,

    /// Output TSV event list. Useful for manual audit.
    #[arg(long, default_value = "strategy_events.tsv")]
    events_out: PathBuf,

    /// Existing preset/header file. If set, its content is copied before generated --new blocks.
    #[arg(long)]
    base_preset: Option<PathBuf>,

    /// Only include strategies with at least this many LOCK/LOCKED events.
    #[arg(long, default_value_t = 1)]
    min_locks: u64,

    /// Include strategies with SUCCESS even if they were never LOCKED.
    #[arg(long, default_value_t = false)]
    include_success_only: bool,

    /// Maximum number of strategy blocks generated in preset.
    #[arg(long, default_value_t = 100)]
    max_blocks: usize,

    /// Default TCP filter for generated sections.
    #[arg(long, default_value = "80,443")]
    tcp_filter: String,

    /// Default UDP filter for generated sections.
    #[arg(long, default_value = "443")]
    udp_filter: String,

    /// If true, do not emit --hostlist-domains=... lines; keep targets only as comments.
    #[arg(long, default_value_t = false)]
    no_hostlist_domains: bool,

    /// Progress every N lines. 0 disables progress.
    #[arg(long, default_value_t = 1_000_000)]
    progress_lines: u64,
}

#[derive(Debug, Clone, Serialize)]
struct ProfileLuaStep {
    profile_id: u32,
    func: String,
    params: BTreeMap<String, String>,
    range_in: Option<String>,
    range_out: Option<String>,
    payload_type: Option<String>,
    raw: String,
}

#[derive(Debug, Clone, Serialize)]
struct StrategyEvent {
    line: u64,
    event: String,
    strategy: u32,
    protocol: Option<String>,
    target: Option<String>,
    profile_id: Option<u32>,
    details: String,
}

#[derive(Debug, Clone, Default, Serialize)]
struct StrategyStats {
    strategy: u32,
    locks: u64,
    locked_successes: u64,
    plain_successes: u64,
    fails: u64,
    failure_overrides: u64,
    auto_unlocks: u64,
    first_line: Option<u64>,
    last_line: Option<u64>,
    protocols: BTreeMap<String, u64>,
    targets: BTreeMap<String, u64>,
    profiles: BTreeMap<u32, u64>,
    score: i64,
}

#[derive(Debug, Clone, Default)]
struct ContextState {
    last_profile_id: Option<u32>,
    current_strategy: Option<u32>,
    last_protocol: Option<String>,
    last_target: Option<String>,
}

#[derive(Serialize)]
struct Report {
    source_log: String,
    total_lines: u64,
    profile_lua_steps: usize,
    strategies: Vec<StrategyStats>,
    events: Vec<StrategyEvent>,
    generated_blocks: usize,
    notes: Vec<String>,
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    let file = File::open(&cli.log)
        .with_context(|| format!("failed to open log: {}", cli.log.display()))?;
    let reader = BufReader::with_capacity(1024 * 1024, file);

    let mut ctx = ContextState::default();
    let mut profiles: HashMap<u32, Vec<ProfileLuaStep>> = HashMap::new();
    let mut stats: HashMap<u32, StrategyStats> = HashMap::new();
    let mut events: Vec<StrategyEvent> = Vec::new();

    let mut total_lines = 0_u64;

    for line_result in reader.lines() {
        let line = line_result?;
        total_lines += 1;

        if cli.progress_lines > 0 && total_lines % cli.progress_lines == 0 {
            eprintln!(
                "processed={} strategies={} profile_steps={} events={}",
                total_lines,
                stats.len(),
                profiles.values().map(|v| v.len()).sum::<usize>(),
                events.len()
            );
        }

        if let Some(step) = parse_profile_lua_step(&line) {
            profiles.entry(step.profile_id).or_default().push(step);
            continue;
        }

        update_context_from_line(&mut ctx, &line);

        let found = parse_strategy_event(total_lines, &line, &ctx);
        if let Some(ev) = found {
            apply_event(&mut stats, &ev);
            events.push(ev);
        }
    }

    let mut strategies: Vec<StrategyStats> = stats.into_values().collect();
    for s in &mut strategies {
        s.score = score_strategy(s);
    }
    strategies.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then_with(|| b.locks.cmp(&a.locks))
            .then_with(|| b.locked_successes.cmp(&a.locked_successes))
            .then_with(|| b.plain_successes.cmp(&a.plain_successes))
            .then_with(|| a.strategy.cmp(&b.strategy))
    });

    let generated_blocks = write_preset(&cli, &strategies, &profiles)?;
    write_events_tsv(&cli.events_out, &events)?;

    let notes = vec![
        "Preset generation is best-effort: original blob file paths are not usually recoverable from debug log lines.".to_string(),
        "Use --base-preset to preserve lua-init, blob, wf and global options from a known working preset.".to_string(),
        "Generated --lua-desync lines are reconstructed from `profile N (noname) lua ...` definitions and LOCK/SUCCESS statistics.".to_string(),
    ];

    let report = Report {
        source_log: cli.log.display().to_string(),
        total_lines,
        profile_lua_steps: profiles.values().map(|v| v.len()).sum(),
        strategies,
        events,
        generated_blocks,
        notes,
    };

    let stats_file = File::create(&cli.stats_out)
        .with_context(|| format!("failed to create stats file: {}", cli.stats_out.display()))?;
    let mut stats_writer = BufWriter::new(stats_file);
    serde_json::to_writer_pretty(&mut stats_writer, &report)?;
    stats_writer.write_all(b"\n")?;

    eprintln!("preset written: {}", cli.preset_out.display());
    eprintln!("stats written:  {}", cli.stats_out.display());
    eprintln!("events written: {}", cli.events_out.display());
    eprintln!("generated preset blocks: {}", generated_blocks);

    Ok(())
}

fn parse_profile_lua_step(line: &str) -> Option<ProfileLuaStep> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| {
        Regex::new(r#"^profile\s+(?P<profile>\d+)\s+\([^)]*\)\s+lua\s+(?P<func>[A-Za-z0-9_]+)\((?P<body>.*)\)$"#).unwrap()
    });

    let caps = re.captures(line)?;
    let profile_id = caps.name("profile")?.as_str().parse::<u32>().ok()?;
    let func = caps.name("func")?.as_str().to_string();
    let body = caps.name("body")?.as_str().trim();

    let (param_part, range_in, range_out, payload_type) = split_lua_body(body);
    let params = parse_params(param_part);

    Some(ProfileLuaStep {
        profile_id,
        func,
        params,
        range_in,
        range_out,
        payload_type,
        raw: line.to_string(),
    })
}

fn split_lua_body(body: &str) -> (&str, Option<String>, Option<String>, Option<String>) {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| {
        Regex::new(r#"(?P<params>.*?)\s+range_in=(?P<rin>\S+)\s+range_out=(?P<rout>\S+)\s+payload_type=\s*(?P<payload>\S+)\s*$"#).unwrap()
    });

    if let Some(caps) = re.captures(body) {
        let params = caps.name("params").map(|m| m.as_str()).unwrap_or("").trim();
        let range_in = caps.name("rin").map(|m| m.as_str().to_string());
        let range_out = caps.name("rout").map(|m| m.as_str().to_string());
        let payload_type = caps.name("payload").map(|m| trim_log_value(m.as_str()));
        return (params, range_in, range_out, payload_type);
    }

    (body, None, None, None)
}

fn parse_params(s: &str) -> BTreeMap<String, String> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r#"([A-Za-z0-9_]+)=\"([^\"]*)\""#).unwrap());

    let mut out = BTreeMap::new();
    for caps in re.captures_iter(s) {
        let key = caps.get(1).unwrap().as_str().to_string();
        let val = caps.get(2).unwrap().as_str().to_string();
        out.insert(key, val);
    }
    out
}

fn update_context_from_line(ctx: &mut ContextState, line: &str) {
    if let Some(profile) = parse_desync_profile(line) {
        ctx.last_profile_id = Some(profile);
    }

    if let Some(strategy) = parse_current_strategy(line) {
        ctx.current_strategy = Some(strategy);
    }

    if let Some(host) = parse_hostname(line) {
        ctx.last_target = Some(host);
    }

    if let Some((proto, target)) = parse_host_record_key(line) {
        ctx.last_protocol = Some(proto);
        ctx.last_target = Some(target);
    }
}

fn parse_desync_profile(line: &str) -> Option<u32> {
    static RE1: OnceLock<Regex> = OnceLock::new();
    static RE2: OnceLock<Regex> = OnceLock::new();

    let re1 = RE1.get_or_init(|| Regex::new(r#"desync profile\s+(\d+)\s+\([^)]*\)\s+matches"#).unwrap());
    if let Some(caps) = re1.captures(line) {
        return caps.get(1)?.as_str().parse().ok();
    }

    let re2 = RE2.get_or_init(|| Regex::new(r#"using cached desync profile\s+(\d+)\s+\([^)]*\)"#).unwrap());
    if let Some(caps) = re2.captures(line) {
        return caps.get(1)?.as_str().parse().ok();
    }

    None
}

fn parse_current_strategy(line: &str) -> Option<u32> {
    static RE1: OnceLock<Regex> = OnceLock::new();
    static RE2: OnceLock<Regex> = OnceLock::new();

    let re1 = RE1.get_or_init(|| Regex::new(r#"circular_quality:\s+current strategy\s+(\d+)"#).unwrap());
    if let Some(caps) = re1.captures(line) {
        return caps.get(1)?.as_str().parse().ok();
    }

    let re2 = RE2.get_or_init(|| Regex::new(r#"circular_quality:\s+start from strategy\s+(\d+)"#).unwrap());
    if let Some(caps) = re2.captures(line) {
        return caps.get(1)?.as_str().parse().ok();
    }

    None
}

fn parse_hostname(line: &str) -> Option<String> {
    line.strip_prefix("hostname: ")
        .map(|s| trim_log_value(s.trim()))
        .filter(|s| !s.is_empty())
}

fn parse_host_record_key(line: &str) -> Option<(String, String)> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r#"host record key 'autostate\.([^\s']+)\s+([^']+)'"#).unwrap());
    let caps = re.captures(line)?;
    let proto = trim_log_value(caps.get(1)?.as_str());
    let target = trim_log_value(caps.get(2)?.as_str());
    Some((proto, target))
}

fn parse_strategy_event(line_no: u64, line: &str, ctx: &ContextState) -> Option<StrategyEvent> {
    if let Some(ev) = parse_slm_lock(line_no, line, ctx) {
        return Some(ev);
    }
    if let Some(ev) = parse_slm_success_or_fail(line_no, line, ctx) {
        return Some(ev);
    }
    if let Some(ev) = parse_circular_locked_on(line_no, line, ctx) {
        return Some(ev);
    }
    if let Some(ev) = parse_circular_locked_success(line_no, line, ctx) {
        return Some(ev);
    }
    if let Some(ev) = parse_circular_locked_fail(line_no, line, ctx) {
        return Some(ev);
    }
    if let Some(ev) = parse_failure_override(line_no, line, ctx) {
        return Some(ev);
    }
    if let Some(ev) = parse_auto_unlock(line_no, line, ctx) {
        return Some(ev);
    }
    None
}

fn parse_slm_lock(line_no: u64, line: &str, ctx: &ContextState) -> Option<StrategyEvent> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| {
        Regex::new(r#"LUA:\s+slm_quality:\s+LOCK\s+\[(?P<proto>[^\]]+)\]\s+(?P<target>.*?)\s+->\s+strat=(?P<strat>\d+)\s+\((?P<details>[^)]*)\)"#).unwrap()
    });

    let caps = re.captures(line)?;
    let strategy = caps.name("strat")?.as_str().parse().ok()?;
    Some(StrategyEvent {
        line: line_no,
        event: "lock".to_string(),
        strategy,
        protocol: caps.name("proto").map(|m| trim_log_value(m.as_str())),
        target: caps.name("target").map(|m| trim_log_value(m.as_str())),
        profile_id: ctx.last_profile_id,
        details: caps.name("details").map(|m| m.as_str().to_string()).unwrap_or_default(),
    })
}

fn parse_slm_success_or_fail(line_no: u64, line: &str, ctx: &ContextState) -> Option<StrategyEvent> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| {
        Regex::new(r#"LUA:\s+slm_quality:\s+\[(?P<proto>[^\]]+)\]\s+(?P<target>.*?)\s+strat=(?P<strat>\d+)\s+(?P<kind>SUCCESS|FAIL)\s+(?P<details>\d+/\d+)"#).unwrap()
    });

    let caps = re.captures(line)?;
    let strategy = caps.name("strat")?.as_str().parse().ok()?;
    let kind = caps.name("kind")?.as_str();
    Some(StrategyEvent {
        line: line_no,
        event: if kind == "SUCCESS" { "success" } else { "fail" }.to_string(),
        strategy,
        protocol: caps.name("proto").map(|m| trim_log_value(m.as_str())),
        target: caps.name("target").map(|m| trim_log_value(m.as_str())),
        profile_id: ctx.last_profile_id,
        details: caps.name("details").map(|m| m.as_str().to_string()).unwrap_or_default(),
    })
}

fn parse_circular_locked_on(line_no: u64, line: &str, ctx: &ContextState) -> Option<StrategyEvent> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r#"LUA:\s+circular_quality:\s+LOCKED on strategy\s+(?P<strat>\d+)(?P<details>.*)"#).unwrap());

    let caps = re.captures(line)?;
    let strategy = caps.name("strat")?.as_str().parse().ok()?;
    Some(StrategyEvent {
        line: line_no,
        event: "lock".to_string(),
        strategy,
        protocol: ctx.last_protocol.clone(),
        target: ctx.last_target.clone(),
        profile_id: ctx.last_profile_id,
        details: caps.name("details").map(|m| m.as_str().trim().to_string()).unwrap_or_default(),
    })
}

fn parse_circular_locked_success(line_no: u64, line: &str, ctx: &ContextState) -> Option<StrategyEvent> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r#"LUA:\s+circular_quality:\s+LOCKED strat\s+(?P<strat>\d+)\s+SUCCESS(?P<details>.*)"#).unwrap());

    let caps = re.captures(line)?;
    let strategy = caps.name("strat")?.as_str().parse().ok()?;
    Some(StrategyEvent {
        line: line_no,
        event: "locked_success".to_string(),
        strategy,
        protocol: ctx.last_protocol.clone(),
        target: ctx.last_target.clone(),
        profile_id: ctx.last_profile_id,
        details: caps.name("details").map(|m| m.as_str().trim().to_string()).unwrap_or_default(),
    })
}

fn parse_circular_locked_fail(line_no: u64, line: &str, ctx: &ContextState) -> Option<StrategyEvent> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r#"LUA:\s+circular_quality:\s+LOCKED strat\s+(?P<strat>\d+)\s+FAIL\s+(?P<details>#\d+/\d+)\s+for\s+(?P<target>.+)$"#).unwrap());

    let caps = re.captures(line)?;
    let strategy = caps.name("strat")?.as_str().parse().ok()?;
    Some(StrategyEvent {
        line: line_no,
        event: "fail".to_string(),
        strategy,
        protocol: ctx.last_protocol.clone(),
        target: caps.name("target").map(|m| trim_log_value(m.as_str())),
        profile_id: ctx.last_profile_id,
        details: caps.name("details").map(|m| m.as_str().to_string()).unwrap_or_default(),
    })
}

fn parse_failure_override(line_no: u64, line: &str, ctx: &ContextState) -> Option<StrategyEvent> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r#"LUA:\s+circular_quality:\s+FAILURE overrides previous SUCCESS for strat\s+(?P<strat>\d+)"#).unwrap());

    let caps = re.captures(line)?;
    let strategy = caps.name("strat")?.as_str().parse().ok()?;
    Some(StrategyEvent {
        line: line_no,
        event: "failure_override".to_string(),
        strategy,
        protocol: ctx.last_protocol.clone(),
        target: ctx.last_target.clone(),
        profile_id: ctx.last_profile_id,
        details: line.to_string(),
    })
}

fn parse_auto_unlock(line_no: u64, line: &str, ctx: &ContextState) -> Option<StrategyEvent> {
    if !line.contains("AUTO-UNLOCK") && !line.contains("auto-unlock") {
        return None;
    }

    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r#"strat(?:egy)?[=\s]+(?P<strat>\d+)"#).unwrap());

    let strategy = re
        .captures(line)
        .and_then(|c| c.name("strat"))
        .and_then(|m| m.as_str().parse().ok())
        .or(ctx.current_strategy)?;

    Some(StrategyEvent {
        line: line_no,
        event: "auto_unlock".to_string(),
        strategy,
        protocol: ctx.last_protocol.clone(),
        target: ctx.last_target.clone(),
        profile_id: ctx.last_profile_id,
        details: line.to_string(),
    })
}

fn apply_event(stats: &mut HashMap<u32, StrategyStats>, ev: &StrategyEvent) {
    let s = stats.entry(ev.strategy).or_insert_with(|| StrategyStats {
        strategy: ev.strategy,
        ..Default::default()
    });

    match ev.event.as_str() {
        "lock" => s.locks += 1,
        "locked_success" => s.locked_successes += 1,
        "success" => s.plain_successes += 1,
        "fail" => s.fails += 1,
        "failure_override" => s.failure_overrides += 1,
        "auto_unlock" => s.auto_unlocks += 1,
        _ => {}
    }

    if let Some(proto) = &ev.protocol {
        *s.protocols.entry(proto.clone()).or_insert(0) += 1;
    }
    if let Some(target) = &ev.target {
        *s.targets.entry(target.clone()).or_insert(0) += 1;
    }
    if let Some(profile) = ev.profile_id {
        *s.profiles.entry(profile).or_insert(0) += 1;
    }

    if s.first_line.is_none() {
        s.first_line = Some(ev.line);
    }
    s.last_line = Some(ev.line);
}

fn score_strategy(s: &StrategyStats) -> i64 {
    (s.locks as i64 * 100)
        + (s.locked_successes as i64 * 50)
        + (s.plain_successes as i64 * 5)
        - (s.fails as i64 * 25)
        - (s.failure_overrides as i64 * 80)
        - (s.auto_unlocks as i64 * 100)
}

fn write_preset(
    cli: &Cli,
    strategies: &[StrategyStats],
    profiles: &HashMap<u32, Vec<ProfileLuaStep>>,
) -> Result<usize> {
    let out = File::create(&cli.preset_out)
        .with_context(|| format!("failed to create preset: {}", cli.preset_out.display()))?;
    let mut w = BufWriter::new(out);

    if let Some(base) = &cli.base_preset {
        let text = std::fs::read_to_string(base)
            .with_context(|| format!("failed to read base preset: {}", base.display()))?;
        w.write_all(text.as_bytes())?;
        if !text.ends_with('\n') {
            w.write_all(b"\n")?;
        }
        w.write_all(b"\n")?;
    } else {
        write_default_header(&mut w)?;
    }

    writeln!(w, "# ============================================================")?;
    writeln!(w, "# Generated locked/successful strategy blocks")?;
    writeln!(w, "# Source log: {}", cli.log.display())?;
    writeln!(w, "# WARNING: generated blocks are best-effort. Audit before use.")?;
    writeln!(w, "# ============================================================")?;

    let mut emitted = 0usize;
    let mut seen_sections = HashSet::<String>::new();

    for strategy in strategies {
        if emitted >= cli.max_blocks {
            break;
        }
        if strategy.locks < cli.min_locks && !(cli.include_success_only && strategy.plain_successes > 0) {
            continue;
        }

        let profile_ids = ranked_profile_ids(strategy);
        let steps = candidate_steps_for_strategy(strategy.strategy, &profile_ids, profiles);
        if steps.is_empty() {
            writeln!(w)?;
            writeln!(w, "--new")?;
            writeln!(w, "# Strategy {} was successful/locked, but no matching profile lua step was reconstructed.", strategy.strategy)?;
            write_strategy_comment(&mut w, strategy)?;
            emitted += 1;
            continue;
        }

        let targets = top_keys(&strategy.targets, 5);
        let protocol = best_key(&strategy.protocols).unwrap_or_else(|| "unknown".to_string());
        let filter_line = choose_filter_line(&protocol, &cli.tcp_filter, &cli.udp_filter);

        for step in steps {
            let desync = lua_step_to_desync_line(&step);
            let section_key = format!("{}|{}|{}|{}", strategy.strategy, protocol, step.profile_id, desync);
            if !seen_sections.insert(section_key) {
                continue;
            }
            if emitted >= cli.max_blocks {
                break;
            }

            writeln!(w)?;
            writeln!(w, "--new")?;
            write_strategy_comment(&mut w, strategy)?;
            writeln!(w, "# Profile: {}", step.profile_id)?;
            writeln!(w, "# Source profile line: {}", step.raw)?;

            if !targets.is_empty() {
                writeln!(w, "# Targets seen: {}", targets.join(", "))?;
            }

            writeln!(w, "{}", filter_line)?;

            if !cli.no_hostlist_domains {
                for target in targets.iter().filter(|t| is_domain(t)).take(3) {
                    writeln!(w, "--hostlist-domains={}", target)?;
                }
            }

            if let Some(out_range) = step.range_out.as_deref().and_then(convert_out_range) {
                writeln!(w, "--out-range={}", out_range)?;
            }

            if let Some(payload) = &step.payload_type {
                if payload != "" && payload != "all)" {
                    writeln!(w, "--payload={}", payload.trim_end_matches(')'))?;
                }
            }

            writeln!(w, "{}", desync)?;
            emitted += 1;
        }
    }

    Ok(emitted)
}

fn write_default_header<W: Write>(w: &mut W) -> Result<()> {
    writeln!(w, "# Preset: Extracted locked strategies")?;
    writeln!(w, "# TemplateOrigin: zapret-strategy-extractor")?;
    writeln!(w, "# BuiltinVersion: unknown")?;
    writeln!(w, "# IconColor: #a8c5ff")?;
    writeln!(w)?;
    writeln!(w, "--lua-init=@lua/zapret-lib.lua")?;
    writeln!(w, "--lua-init=@lua/zapret-antidpi.lua")?;
    writeln!(w, "--lua-init=@lua/zapret-auto.lua")?;
    writeln!(w, "--lua-init=@lua/custom_funcs.lua")?;
    writeln!(w, "--lua-init=@lua/custom_diag.lua")?;
    writeln!(w, "--lua-init=@lua/zapret-multishake.lua")?;
    writeln!(w)?;
    writeln!(w, "--ctrack-disable=0")?;
    writeln!(w, "--ipcache-lifetime=8400")?;
    writeln!(w, "--ipcache-hostname=1")?;
    writeln!(w)?;
    writeln!(w, "--wf-tcp-out=80,443,500,853,1080,2053,2083,2087,2096,8443")?;
    writeln!(w, "--wf-udp-out=80,443,500,50000-65535")?;
    writeln!(w)?;
    writeln!(w, "# Add blob lines manually or pass --base-preset to preserve them from an existing preset.")?;
    Ok(())
}

fn write_strategy_comment<W: Write>(w: &mut W, s: &StrategyStats) -> Result<()> {
    writeln!(
        w,
        "# Strategy {}: score={} locks={} locked_successes={} successes={} fails={} overrides={} auto_unlocks={}",
        s.strategy, s.score, s.locks, s.locked_successes, s.plain_successes, s.fails, s.failure_overrides, s.auto_unlocks
    )?;
    if !s.protocols.is_empty() {
        writeln!(w, "# Protocols: {}", format_counts(&s.protocols, 5))?;
    }
    if !s.targets.is_empty() {
        writeln!(w, "# Targets: {}", format_counts(&s.targets, 5))?;
    }
    Ok(())
}

fn ranked_profile_ids(s: &StrategyStats) -> Vec<u32> {
    let mut pairs: Vec<(u32, u64)> = s.profiles.iter().map(|(k, v)| (*k, *v)).collect();
    pairs.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    pairs.into_iter().map(|(id, _)| id).collect()
}

fn candidate_steps_for_strategy(
    strategy: u32,
    profile_ids: &[u32],
    profiles: &HashMap<u32, Vec<ProfileLuaStep>>,
) -> Vec<ProfileLuaStep> {
    let mut out = Vec::new();
    let mut profile_order = profile_ids.to_vec();

    if profile_order.is_empty() {
        let mut all: Vec<u32> = profiles.keys().copied().collect();
        all.sort_unstable();
        profile_order = all;
    }

    for profile_id in profile_order {
        let Some(steps) = profiles.get(&profile_id) else { continue; };
        for step in steps {
            if step.func == "circular_quality" || step.func == "slm_quality" {
                continue;
            }
            if let Some(s) = step.params.get("strategy").and_then(|v| v.parse::<u32>().ok()) {
                if s == strategy {
                    out.push(step.clone());
                }
            }
        }
    }

    out
}

fn lua_step_to_desync_line(step: &ProfileLuaStep) -> String {
    let mut parts = vec![format!("--lua-desync={}", step.func)];
    for (key, val) in &step.params {
        if key == "strategy" {
            continue;
        }
        if val.is_empty() {
            continue;
        }
        parts.push(format!("{}={}", key, val));
    }
    parts.join(":")
}

fn choose_filter_line(protocol: &str, tcp_filter: &str, udp_filter: &str) -> String {
    let p = protocol.to_ascii_lowercase();
    if p.contains("quic") || p.contains("udp") || p.contains("unknown.udp") || p == "unknown" {
        format!("--filter-udp={}", udp_filter)
    } else {
        format!("--filter-tcp={}", tcp_filter)
    }
}

fn convert_out_range(range: &str) -> Option<String> {
    if range.is_empty() {
        return None;
    }

    if let Some(pos) = range.rfind('-') {
        let suffix = &range[pos..];
        if suffix.len() >= 3 && (suffix.starts_with("-d") || suffix.starts_with("-n")) {
            return Some(suffix.to_string());
        }
    }

    Some(range.to_string())
}

fn write_events_tsv(path: &PathBuf, events: &[StrategyEvent]) -> Result<()> {
    let out = File::create(path)
        .with_context(|| format!("failed to create events file: {}", path.display()))?;
    let mut w = BufWriter::new(out);
    writeln!(w, "line\tevent\tstrategy\tprotocol\ttarget\tprofile_id\tdetails")?;
    for ev in events {
        writeln!(
            w,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}",
            ev.line,
            ev.event,
            ev.strategy,
            ev.protocol.as_deref().unwrap_or(""),
            ev.target.as_deref().unwrap_or(""),
            ev.profile_id.map(|v| v.to_string()).unwrap_or_default(),
            ev.details.replace('\t', " ")
        )?;
    }
    Ok(())
}

fn best_key(map: &BTreeMap<String, u64>) -> Option<String> {
    map.iter()
        .max_by(|a, b| a.1.cmp(b.1).then_with(|| b.0.cmp(a.0)))
        .map(|(k, _)| k.clone())
}

fn top_keys(map: &BTreeMap<String, u64>, limit: usize) -> Vec<String> {
    let mut pairs: Vec<_> = map.iter().collect();
    pairs.sort_by(|a, b| b.1.cmp(a.1).then_with(|| a.0.cmp(b.0)));
    pairs.into_iter().take(limit).map(|(k, _)| k.clone()).collect()
}

fn format_counts(map: &BTreeMap<String, u64>, limit: usize) -> String {
    let mut pairs: Vec<_> = map.iter().collect();
    pairs.sort_by(|a, b| b.1.cmp(a.1).then_with(|| a.0.cmp(b.0)));
    pairs
        .into_iter()
        .take(limit)
        .map(|(k, v)| format!("{}={}", k, v))
        .collect::<Vec<_>>()
        .join(", ")
}

fn is_domain(s: &str) -> bool {
    let lower = s.to_ascii_lowercase();
    lower.contains('.')
        && !lower.chars().any(char::is_whitespace)
        && !lower.chars().all(|c| c.is_ascii_digit() || c == '.')
        && !lower.contains(':')
}

fn trim_log_value(s: &str) -> String {
    s.trim()
        .trim_matches('"')
        .trim_matches('\'')
        .trim_matches('(')
        .trim_matches(')')
        .trim_matches(',')
        .to_string()
}
