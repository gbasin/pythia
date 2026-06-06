#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Post-run health check + escalation for the pythia daily panel.

Runs at the end of daily_run.sh. Inspects the latest clean run in SQLite,
compares it against a rolling baseline, and routes any problems:

    critical -> ntfy push (your phone) + GitHub issue
    warn     -> GitHub issue only

Config + thresholds live in health_checks.yaml. The ntfy topic is a secret
read from the environment (PYTHIA_NTFY_TOPIC), never committed.

    uv run scripts/health_check.py            # check + alert
    uv run scripts/health_check.py --dry-run  # print findings, send nothing
    uv run scripts/health_check.py --force-test  # send a test alert and exit
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "panel.sqlite"
CONFIG = ROOT / "health_checks.yaml"


@dataclass
class Finding:
    key: str          # stable identifier, used for GitHub-issue dedup
    severity: str     # "critical" | "warn"
    title: str        # one-line summary
    detail: str       # multi-line body


# ───────────────────────── metric collection ─────────────────────────


def latest_run(con) -> sqlite3.Row | None:
    return con.execute(
        "SELECT id, started_at, status FROM runs "
        "WHERE is_clean=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()


def run_response_stats(con, run_id: int) -> dict:
    row = con.execute(
        """
        SELECT COUNT(*) AS n_total,
               SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS n_ok,
               SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS n_fail
        FROM responses WHERE run_id=?
        """,
        (run_id,),
    ).fetchone()
    return dict(row)


def provider_ok_counts(con, run_id: int) -> dict[str, int]:
    rows = con.execute(
        """
        SELECT mc.provider AS provider,
               SUM(CASE WHEN r.error IS NULL THEN 1 ELSE 0 END) AS n_ok
        FROM responses r JOIN model_configs mc ON r.model_config_id=mc.id
        WHERE r.run_id=? GROUP BY mc.provider
        """,
        (run_id,),
    ).fetchall()
    return {r["provider"]: r["n_ok"] for r in rows}


def mentions_per_response(con, run_id: int) -> tuple[float, int, int]:
    """(mentions_per_ok_response, n_mentions, n_needs_review) for a run."""
    row = con.execute(
        """
        SELECT COUNT(m.id) AS n_mentions,
               SUM(CASE WHEN m.needs_review=1 THEN 1 ELSE 0 END) AS n_review,
               (SELECT COUNT(*) FROM responses
                 WHERE run_id=? AND error IS NULL) AS n_ok
        FROM mentions m
        JOIN responses r ON m.response_id=r.id
        WHERE r.run_id=?
        """,
        (run_id, run_id),
    ).fetchone()
    n_ok = row["n_ok"] or 0
    n_mentions = row["n_mentions"] or 0
    n_review = row["n_review"] or 0
    rate = (n_mentions / n_ok) if n_ok else 0.0
    return rate, n_mentions, n_review


def _table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def alpha_lag_sessions(con) -> tuple[int, str | None, str | None]:
    """How many priced SPY sessions sit beyond the latest benchmarked entry_date.

    Returns (lag, latest_forward_entry, latest_priced_session). lag counts
    distinct SPY trading sessions newer than the most recent forward_returns
    entry — i.e. sessions we have prices for but haven't scored.
    """
    if not (_table_exists(con, "forward_returns") and _table_exists(con, "prices")):
        return 0, None, None
    fwd = con.execute(
        "SELECT MAX(entry_date) AS d FROM forward_returns WHERE horizon_days=1"
    ).fetchone()["d"]
    sessions = [
        r["date"]
        for r in con.execute(
            "SELECT DISTINCT date FROM prices "
            "WHERE ticker='SPY' AND source='yfinance' AND date > COALESCE(?, '0000-00-00') "
            "ORDER BY date",
            (fwd,),
        ).fetchall()
    ]
    return len(sessions), fwd, (sessions[-1] if sessions else None)


def baseline_mentions_rate(con, exclude_run_id: int, days: int) -> float:
    """Median mentions-per-ok-response across the prior `days` clean runs."""
    runs = [
        r["id"]
        for r in con.execute(
            "SELECT id FROM runs WHERE is_clean=1 AND id<? "
            "ORDER BY id DESC LIMIT ?",
            (exclude_run_id, days),
        ).fetchall()
    ]
    rates = [mentions_per_response(con, rid)[0] for rid in runs]
    rates = [x for x in rates if x > 0]
    if not rates:
        return 0.0
    rates.sort()
    mid = len(rates) // 2
    return rates[mid] if len(rates) % 2 else (rates[mid - 1] + rates[mid]) / 2


# ───────────────────────── checks ─────────────────────────


def run_checks(con, cfg: dict) -> list[Finding]:
    findings: list[Finding] = []
    checks = cfg.get("checks", {})

    run = latest_run(con)
    if run is None:
        return [Finding("no_run", "critical", "no clean runs in database",
                        "The runs table has no is_clean=1 rows.")]

    # Freshness: did a run actually happen recently?
    started = datetime.fromisoformat(run["started_at"])
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - started).total_seconds() / 3600
    max_age = cfg.get("fresh_run_max_age_h", 26)
    if age_h > max_age:
        findings.append(Finding(
            "stale_run", "critical",
            f"no fresh panel run in {age_h:.0f}h",
            f"Latest clean run is #{run['id']} started {run['started_at']} "
            f"({age_h:.1f}h ago, threshold {max_age}h). The nightly job may "
            f"not be firing (launchd unloaded? machine asleep?)."))
        # A stale run makes the per-run metrics below meaningless; stop here.
        return findings

    rid = run["id"]
    stats = run_response_stats(con, rid)

    # Provider blackout.
    if "provider_blackout" in checks:
        sev = checks["provider_blackout"].get("severity", "critical")
        for provider, n_ok in provider_ok_counts(con, rid).items():
            if n_ok == 0:
                findings.append(Finding(
                    f"blackout_{provider}", sev,
                    f"provider blackout: {provider} returned 0 responses",
                    f"In run #{rid}, every {provider} call failed. Common cause "
                    f"is an expired/rotated CLI auth token (codex 401, claude "
                    f"login). Re-authenticate the {provider} CLI."))

    # Run failure rate.
    if "run_failure_rate" in checks and stats["n_total"]:
        c = checks["run_failure_rate"]
        rate = (stats["n_fail"] or 0) / stats["n_total"]
        if rate > c.get("max", 0.15):
            findings.append(Finding(
                "failure_rate", c.get("severity", "critical"),
                f"run failure rate {rate:.0%} ({stats['n_fail']}/{stats['n_total']})",
                f"Run #{rid} had {stats['n_fail']} errored tuples out of "
                f"{stats['n_total']} (threshold {c.get('max', 0.15):.0%})."))

    # Mentions-per-response drift.
    if "mentions_per_response" in checks:
        c = checks["mentions_per_response"]
        rate, n_mentions, n_review = mentions_per_response(con, rid)
        base = baseline_mentions_rate(con, rid, cfg.get("baseline_days", 7))
        if base > 0 and rate < base * c.get("min_ratio", 0.5):
            findings.append(Finding(
                "mentions_drift", c.get("severity", "warn"),
                f"mentions/response dropped to {rate:.1f} (baseline {base:.1f})",
                f"Run #{rid} extracted {rate:.1f} tickers per successful "
                f"response vs a {cfg.get('baseline_days',7)}-day baseline of "
                f"{base:.1f}. The $TICKER format directive may have stopped "
                f"being honored, or extraction regressed."))
    else:
        _, n_mentions, n_review = mentions_per_response(con, rid)

    # Alpha benchmark lag — two signals, fire on either.
    if "alpha_lag" in checks:
        c = checks["alpha_lag"]
        sev = c.get("severity", "warn")
        lag, fwd, latest = alpha_lag_sessions(con)
        # (1) priced sessions beyond the latest scored entry (SPY fresh, scoring stuck).
        if lag > c.get("max_sessions", 1):
            findings.append(Finding(
                "alpha_lag", sev,
                f"alpha benchmark lagging {lag} sessions (through {fwd})",
                f"{lag} priced SPY sessions exist beyond the latest benchmarked "
                f"entry_date {fwd} (newest priced: {latest}). Forward returns "
                f"aren't being computed for sessions we already have prices for "
                f"— the price cache or benchmark_alpha is stuck."))
        # (2) calendar staleness — catches a total stall where SPY is frozen too.
        elif fwd:
            entry = datetime.fromisoformat(fwd).replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - entry).total_seconds() / 86400
            if age_days > c.get("max_age_days", 5):
                findings.append(Finding(
                    "alpha_stale", sev,
                    f"alpha benchmark stale: newest scored session {fwd} "
                    f"is {age_days:.0f}d old",
                    f"The latest forward-return entry_date is {fwd} "
                    f"({age_days:.1f} calendar days ago, threshold "
                    f"{c.get('max_age_days', 5)}d). The price fetch may be down "
                    f"(yfinance) or benchmark_alpha is not running."))

    # Classifier needs_review rate.
    if "classifier_needs_review" in checks and n_mentions:
        c = checks["classifier_needs_review"]
        ratio = n_review / n_mentions
        if ratio > c.get("max_ratio", 0.05):
            findings.append(Finding(
                "needs_review", c.get("severity", "warn"),
                f"classifier needs_review at {ratio:.0%} ({n_review}/{n_mentions})",
                f"Run #{rid} left {n_review} of {n_mentions} mentions in "
                f"needs_review (threshold {c.get('max_ratio',0.05):.0%}). The "
                f"sentiment judge may be emitting malformed JSON."))

    return findings


# ───────────────────────── transports ─────────────────────────


def send_ntfy(cfg: dict, finding: Finding) -> bool:
    t = cfg["transports"]["ntfy"]
    topic = os.environ.get(t.get("topic_env", "PYTHIA_NTFY_TOPIC"))
    if not topic:
        print("  ntfy: skipped (topic env unset)")
        return False
    url = f"{t.get('server', 'https://ntfy.sh').rstrip('/')}/{topic}"
    req = urllib.request.Request(
        url, data=finding.detail.encode("utf-8"), method="POST",
        headers={
            "Title": f"pythia: {finding.title}",
            "Priority": "high" if finding.severity == "critical" else "default",
            "Tags": "rotating_light" if finding.severity == "critical" else "warning",
        })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        print(f"  ntfy: sent ({finding.key})")
        return True
    except Exception as e:  # noqa: BLE001 — never let alerting crash the run
        print(f"  ntfy: FAILED ({finding.key}): {e}")
        return False


def _gh(args: list[str], repo: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args, "--repo", repo],
        capture_output=True, text=True, timeout=30)


def open_issue_keys(cfg: dict) -> set[str]:
    """Return the set of finding-keys that already have an open issue, parsed
    from a marker line in the body so we never double-file the same problem."""
    t = cfg["transports"]["gh_issue"]
    try:
        r = _gh(["issue", "list", "--state", "open", "--label", t["label"],
                 "--json", "body", "--limit", "100"], t["repo"])
        if r.returncode != 0:
            print(f"  gh: list failed: {r.stderr.strip()}")
            return set()
        keys = set()
        for issue in json.loads(r.stdout or "[]"):
            for line in (issue.get("body") or "").splitlines():
                if line.startswith("pythia-health-key:"):
                    keys.add(line.split(":", 1)[1].strip())
        return keys
    except Exception as e:  # noqa: BLE001
        print(f"  gh: list error: {e}")
        return set()


def file_issue(cfg: dict, finding: Finding, existing: set[str]) -> bool:
    t = cfg["transports"]["gh_issue"]
    if finding.key in existing:
        print(f"  gh: open issue already exists ({finding.key}), skipping")
        return False
    body = (f"{finding.detail}\n\n"
            f"severity: {finding.severity}\n"
            f"pythia-health-key: {finding.key}\n"
            f"_filed automatically by scripts/health_check.py_")
    try:
        r = _gh(["issue", "create",
                 "--title", f"[health] {finding.title}",
                 "--body", body, "--label", t["label"]], t["repo"])
        if r.returncode != 0:
            print(f"  gh: create failed ({finding.key}): {r.stderr.strip()}")
            return False
        print(f"  gh: filed ({finding.key}): {r.stdout.strip()}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  gh: create error ({finding.key}): {e}")
        return False


def route(cfg: dict, findings: list[Finding], dry_run: bool) -> None:
    existing = set()
    gh_enabled = cfg["transports"].get("gh_issue", {}).get("enabled")
    if gh_enabled and not dry_run:
        existing = open_issue_keys(cfg)

    for f in findings:
        print(f"[{f.severity.upper()}] {f.title}")
        if dry_run:
            continue
        # critical -> ntfy + gh; warn -> gh only.
        if f.severity == "critical" and cfg["transports"].get("ntfy", {}).get("enabled"):
            send_ntfy(cfg, f)
        if gh_enabled:
            if file_issue(cfg, f, existing):
                existing.add(f.key)


# ───────────────────────── main ─────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print findings, send no alerts")
    ap.add_argument("--force-test", action="store_true",
                    help="emit a synthetic critical finding through the "
                         "configured transports, then exit")
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text())

    if args.force_test:
        test = Finding("selftest", "critical", "health-check self-test",
                       "If you can see this, ntfy + GitHub routing works.")
        route(cfg, [test], dry_run=False)
        return

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    findings = run_checks(con, cfg)

    if not findings:
        print("health check: all green")
        return

    route(cfg, findings, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
