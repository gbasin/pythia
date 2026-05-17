#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
# ///
"""AI Recommendation Panel — daily orchestrator.

For each (prompt, persona, model_config) tuple, invokes the corresponding CLI
(claude -p or codex exec), captures the full JSONL trace, parses out the
final response text + metadata, and writes everything to SQLite.

Usage:
    uv run scripts/run_panel.py                # full daily panel
    uv run scripts/run_panel.py --dry-run      # print tuples without running
    uv run scripts/run_panel.py --limit 1      # run a single tuple
    uv run scripts/run_panel.py --prompt-id name_01 --persona-id speculator \\
        --model-config-id claude_opus_tools_off
"""

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "panel.sqlite"
PERSONAS_PATH = ROOT / "personas.yaml"
PROMPTS_PATH = ROOT / "prompts.yaml"
MODEL_CONFIGS_PATH = ROOT / "model_configs.yaml"
NEUTRAL_CWD = "/tmp"  # avoid loading CLAUDE.md / project memory from a real repo


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: Path):
    with path.open() as f:
        return yaml.safe_load(f)


def upsert_versioned(con, table: str, id_: str, version_hash: str, **fields):
    cols = ["id", "version_hash", *fields.keys()]
    placeholders = ",".join("?" * len(cols))
    values = [id_, version_hash, *fields.values()]
    con.execute(
        f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        values,
    )


def ensure_model_config(con, mc: dict) -> int:
    invocation_args = json.dumps(
        {"subcommand": mc.get("subcommand"), "args": mc.get("args", [])},
        sort_keys=True,
    )
    row = con.execute(
        "SELECT id FROM model_configs WHERE provider=? AND model_name=? AND invocation_args=?",
        (mc["provider"], mc["model_name"], invocation_args),
    ).fetchone()
    if row:
        return row[0]
    cur = con.execute(
        "INSERT INTO model_configs (provider, cli_command, model_name, invocation_args, notes) "
        "VALUES (?,?,?,?,?)",
        (mc["provider"], mc["cli_command"], mc["model_name"], invocation_args, mc.get("notes")),
    )
    return cur.lastrowid


TOOLS_OFF_SUFFIX = (
    "IMPORTANT: For this query, you may NOT use any web search, browser, "
    "or external lookup tools. Answer entirely from your training data. "
    "If your information is stale, say so and proceed anyway with the "
    "best answer you can give from what you know."
)


def assemble_prompt(persona: dict, preamble: str, prompt_text: str, tools_state: str) -> str:
    """Compose persona + preamble + question, plus tool-state-specific suffix.

    Tools-off behavior is enforced two ways: (a) where the CLI supports it,
    via hard flags (claude's `--tools ""`); (b) always, via a prompt
    instruction. Codex has no documented way to disable web_search, so the
    prompt instruction is the only lever — verify compliance by checking
    the trace for web_search events.
    """
    parts = [
        f"About me:\n{persona['description'].strip()}",
        preamble.strip(),
    ]
    if tools_state == "off":
        parts.append(TOOLS_OFF_SUFFIX)
    parts.append(f"Question:\n{prompt_text.strip()}")
    return "\n\n".join(parts) + "\n"


def parse_claude_stream(stdout_bytes: bytes) -> dict:
    """Parse claude -p --output-format stream-json output."""
    text_parts: list[str] = []
    out = {
        "text": "",
        "session_id": None,
        "model_name": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": None,
        "duration_ms": None,
    }
    for line in stdout_bytes.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        et = ev.get("type")
        if et == "system" and ev.get("subtype") == "init":
            out["session_id"] = ev.get("session_id")
            out["model_name"] = ev.get("model")
        elif et == "assistant":
            for content in ev.get("message", {}).get("content", []):
                if content.get("type") == "text":
                    text_parts.append(content.get("text", ""))
        elif et == "result":
            out["session_id"] = out["session_id"] or ev.get("session_id")
            out["duration_ms"] = ev.get("duration_ms")
            out["cost"] = ev.get("total_cost_usd")
            usage = ev.get("usage", {}) or {}
            out["tokens_in"] = (
                (usage.get("input_tokens") or 0)
                + (usage.get("cache_creation_input_tokens") or 0)
                + (usage.get("cache_read_input_tokens") or 0)
            )
            out["tokens_out"] = usage.get("output_tokens") or 0
            if ev.get("result"):
                # Prefer the final result text if provided
                text_parts = [ev["result"]]
    out["text"] = "".join(text_parts).strip()
    return out


def parse_codex_jsonl(stdout_bytes: bytes) -> dict:
    """Parse `codex exec --json` output.

    Event schema observed:
      {"type": "thread.started", "thread_id": "..."}
      {"type": "turn.started"}
      {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "..."}}
      {"type": "item.completed", "item": {"id": "item_1", "type": "web_search", "query": "..."}}
      ...
      {"type": "turn.completed", "usage": {"input_tokens": N, "cached_input_tokens": N,
                                            "output_tokens": N, "reasoning_output_tokens": N}}

    Multiple agent_message items can appear (intermediate reasoning + final
    answer). The last agent_message is the actual user-visible response;
    everything before it is the model's planning narrative.
    """
    agent_messages: list[str] = []
    out = {
        "text": "",
        "session_id": None,
        "model_name": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": None,
        "duration_ms": None,
    }
    for line in stdout_bytes.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        et = ev.get("type")
        if et == "thread.started":
            out["session_id"] = ev.get("thread_id")
        elif et == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message":
                txt = item.get("text") or ""
                if txt:
                    agent_messages.append(txt)
        elif et == "turn.completed":
            usage = ev.get("usage") or {}
            out["tokens_in"] = (usage.get("input_tokens") or 0) + (usage.get("cached_input_tokens") or 0)
            out["tokens_out"] = (usage.get("output_tokens") or 0) + (usage.get("reasoning_output_tokens") or 0)
    # The final agent_message is the user-facing answer.
    out["text"] = agent_messages[-1].strip() if agent_messages else ""
    return out


def run_one(model_config: dict, full_prompt: str, timeout: int) -> dict:
    # Both `claude -p` and `codex exec` read from stdin when no positional
    # prompt is supplied (codex requires "-" or no prompt arg for this).
    # Piping via stdin avoids quoting/parsing issues with flags like
    # `--tools ""` (claude) or multi-line prompts.
    cmd = [model_config["cli_command"]]
    if model_config.get("subcommand"):
        cmd.append(model_config["subcommand"])
    cmd.extend(model_config.get("args", []))
    if model_config.get("subcommand") == "exec":
        cmd.append("-")  # codex requires "-" to read from stdin when also receiving piped input

    started_mono = time.monotonic()
    started_iso = now_iso()
    try:
        proc = subprocess.run(
            cmd,
            input=full_prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            cwd=NEUTRAL_CWD,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "raw_stdout": b"",
            "raw_stderr": b"",
            "returncode": -1,
            "elapsed_ms": int((time.monotonic() - started_mono) * 1000),
            "started_at": started_iso,
            "finished_at": now_iso(),
            "error": "timeout",
            "text": "",
            "session_id": None,
            "model_name": None,
            "tokens_in": None,
            "tokens_out": None,
            "cost": None,
            "duration_ms": None,
        }

    elapsed_ms = int((time.monotonic() - started_mono) * 1000)
    if model_config["trace_format"] == "claude-stream-json":
        parsed = parse_claude_stream(proc.stdout)
    elif model_config["trace_format"] == "codex-jsonl":
        parsed = parse_codex_jsonl(proc.stdout)
    else:
        parsed = {
            "text": proc.stdout.decode("utf-8", errors="replace"),
            "session_id": None, "model_name": None,
            "tokens_in": 0, "tokens_out": 0, "cost": None, "duration_ms": None,
        }

    return {
        "raw_stdout": proc.stdout,
        "raw_stderr": proc.stderr,
        "returncode": proc.returncode,
        "elapsed_ms": parsed.get("duration_ms") or elapsed_ms,
        "started_at": started_iso,
        "finished_at": now_iso(),
        "error": None if proc.returncode == 0 else f"exit {proc.returncode}",
        **parsed,
    }


REFUSAL_PAT = re.compile(
    r"\b(I (?:can't|cannot|won't|will not|am not able to|am unable to)|"
    r"I'm (?:not able to|unable to|not going to))\b",
    re.IGNORECASE,
)
TICKER_PAT = re.compile(r"\$([A-Z]{1,5})\b")


def detect_refusal(text: str | None) -> int:
    if not text:
        return 0
    return 1 if REFUSAL_PAT.search(text) else 0


def extract_mentions(response_id: int, text: str | None) -> list[tuple]:
    """Return one row per unique ticker in order of first appearance.

    `position` is the 1-indexed rank of the first time the ticker appears
    (so a top-5 list yields positions 1..5). `context_snippet` is ±100 chars
    around the first occurrence. Frequency is recoverable from raw_text;
    we keep one row per ticker per response for tractable analysis.
    """
    if not text:
        return []
    seen: dict[str, int] = {}
    rows: list[tuple] = []
    for m in TICKER_PAT.finditer(text):
        ticker = m.group(1)
        if ticker in seen:
            continue
        position = len(seen) + 1
        seen[ticker] = position
        start = max(0, m.start() - 100)
        end = min(len(text), m.end() + 100)
        context = text[start:end]
        rows.append((response_id, ticker, position, None, context, "regex_dollar", 0))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--prompt-id")
    ap.add_argument("--persona-id")
    ap.add_argument("--model-config-id")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    personas_data = load_yaml(PERSONAS_PATH)
    prompts_data = load_yaml(PROMPTS_PATH)
    model_configs_data = load_yaml(MODEL_CONFIGS_PATH)

    preamble = prompts_data["preamble"]
    all_prompts = prompts_data["prompts"]
    all_personas = personas_data["personas"]
    all_mcs = model_configs_data["model_configs"]

    # Always upsert the complete configured panel into the DB. The DB is the
    # source of truth for "what does the active panel ask?"; filtering below
    # only narrows what runs *this invocation*, not what the panel is.
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")

    prompt_hashes = {}
    for p in all_prompts:
        h = short_hash(p["text"])
        prompt_hashes[p["id"]] = h
        upsert_versioned(con, "prompts", p["id"], h, category=p["category"], text=p["text"])
    persona_hashes = {}
    for pe in all_personas:
        h = short_hash(pe["description"])
        persona_hashes[pe["id"]] = h
        upsert_versioned(con, "personas", pe["id"], h, label=pe["label"], description=pe["description"])
    mc_db_ids = {mc["id"]: ensure_model_config(con, mc) for mc in all_mcs}
    con.commit()

    # Apply filters for this invocation only.
    prompts = all_prompts
    personas = all_personas
    model_configs = all_mcs
    if args.prompt_id:
        prompts = [p for p in prompts if p["id"] == args.prompt_id]
    if args.persona_id:
        personas = [p for p in personas if p["id"] == args.persona_id]
    if args.model_config_id:
        model_configs = [m for m in model_configs if m["id"] == args.model_config_id]

    tuples = [(p, pe, mc) for p in prompts for pe in personas for mc in model_configs]
    if args.limit:
        tuples = tuples[: args.limit]

    print(
        f"[panel] {len(tuples)} tuples "
        f"(prompts={len(prompts)} × personas={len(personas)} × model_configs={len(model_configs)})"
    )

    if args.dry_run:
        for p, pe, mc in tuples[:10]:
            print(f"  {p['id']:>14} × {pe['id']:>12} × {mc['id']}")
        if len(tuples) > 10:
            print(f"  ... and {len(tuples)-10} more")
        con.close()
        return 0

    panel_version = short_hash(
        json.dumps(
            {"preamble": preamble, "prompts": prompts, "personas": personas, "model_configs": model_configs},
            sort_keys=True,
            default=str,
        )
    )
    cur = con.execute(
        "INSERT INTO runs (started_at, panel_version, status) VALUES (?,?,?)",
        (now_iso(), panel_version, "running"),
    )
    run_id = cur.lastrowid
    con.commit()
    print(f"[panel] run_id={run_id} panel_version={panel_version}")

    failures = 0
    for i, (p, pe, mc) in enumerate(tuples, start=1):
        full_prompt = assemble_prompt(pe, preamble, p["text"], mc["tools_state"])
        label = f"{p['id']}/{pe['id']}/{mc['id']}"
        print(f"[{i:>3}/{len(tuples)}] {label} ...", flush=True)
        result = run_one(mc, full_prompt, timeout=args.timeout)
        if result["error"]:
            failures += 1
            print(f"        ERROR: {result['error']} (stderr={result['raw_stderr'][:200]!r})")
        else:
            print(
                f"        ok in {result['elapsed_ms']}ms, "
                f"out_tokens={result['tokens_out']}, text_len={len(result.get('text') or '')}"
            )

        trace_gz = gzip.compress(result["raw_stdout"]) if result["raw_stdout"] else None
        cur_insert = con.execute(
            """INSERT INTO responses (
                run_id, prompt_id, prompt_version_hash, persona_id, persona_version_hash,
                model_config_id, tools_state, raw_text, raw_trace_gz, trace_format,
                trace_bytes_unz, latency_ms, tokens_in, tokens_out, cost_usd_reported,
                session_id, refused, error, started_at, finished_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                p["id"], prompt_hashes[p["id"]],
                pe["id"], persona_hashes[pe["id"]],
                mc_db_ids[mc["id"]], mc["tools_state"],
                result.get("text"), trace_gz, mc["trace_format"],
                len(result["raw_stdout"]) if result["raw_stdout"] else 0,
                result.get("elapsed_ms"),
                result.get("tokens_in"), result.get("tokens_out"),
                result.get("cost"),
                result.get("session_id"),
                detect_refusal(result.get("text")), result.get("error"),
                result["started_at"], result["finished_at"],
            ),
        )
        response_id = cur_insert.lastrowid
        mention_rows = extract_mentions(response_id, result.get("text"))
        if mention_rows:
            con.executemany(
                """INSERT INTO mentions (
                    response_id, ticker, position, sentiment_hint,
                    context_snippet, extraction_method, needs_review
                ) VALUES (?,?,?,?,?,?,?)""",
                mention_rows,
            )
        con.commit()

    status = "completed" if failures == 0 else "partial"
    con.execute("UPDATE runs SET finished_at=?, status=? WHERE id=?", (now_iso(), status, run_id))
    con.commit()
    con.close()
    print(f"[panel] run {run_id} {status} ({failures} failure(s) / {len(tuples)} total)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
