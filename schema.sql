-- AI Recommendation Panel — SQLite schema
-- Daily panel that asks SOTA frontier models (via CLI coding-agent harnesses)
-- for investment recommendations across persona × tool-state combinations.
-- Stores raw text, full stream-JSON trace (gzipped), and extracted ticker mentions.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- One row per scheduled daily run (or manual run).
CREATE TABLE IF NOT EXISTS runs (
  id              INTEGER PRIMARY KEY,
  started_at      TEXT    NOT NULL,           -- ISO8601 UTC
  finished_at     TEXT,
  panel_version   TEXT    NOT NULL,           -- git short SHA of prompts/personas
  status          TEXT    NOT NULL DEFAULT 'running',  -- running | completed | partial | failed
  notes           TEXT
);

-- Versioned prompt templates. New hash = new row; old data still references old hash.
CREATE TABLE IF NOT EXISTS prompts (
  id              TEXT    NOT NULL,           -- e.g. portfolio_01
  version_hash    TEXT    NOT NULL,           -- sha256(text) prefix
  category        TEXT    NOT NULL,           -- portfolio | single_name | sector_macro
  text            TEXT    NOT NULL,
  PRIMARY KEY (id, version_hash)
);

-- Versioned personas.
CREATE TABLE IF NOT EXISTS personas (
  id              TEXT    NOT NULL,           -- speculator | allocator
  version_hash    TEXT    NOT NULL,
  label           TEXT    NOT NULL,
  description     TEXT    NOT NULL,
  PRIMARY KEY (id, version_hash)
);

-- The CLI surfaces we panel.
CREATE TABLE IF NOT EXISTS model_configs (
  id              INTEGER PRIMARY KEY,
  provider        TEXT    NOT NULL,           -- claude | codex
  cli_command     TEXT    NOT NULL,           -- claude | codex
  model_name      TEXT    NOT NULL,           -- claude-opus-4-7 | gpt-5.5
  invocation_args TEXT    NOT NULL,           -- JSON: extra CLI flags for reproducibility
  notes           TEXT
);

-- One row per (run, prompt, persona, model_config, tool_state) tuple.
CREATE TABLE IF NOT EXISTS responses (
  id                  INTEGER PRIMARY KEY,
  run_id              INTEGER NOT NULL REFERENCES runs(id),
  prompt_id           TEXT    NOT NULL,
  prompt_version_hash TEXT    NOT NULL,
  persona_id          TEXT    NOT NULL,
  persona_version_hash TEXT   NOT NULL,
  model_config_id     INTEGER NOT NULL REFERENCES model_configs(id),
  tools_state         TEXT    NOT NULL,       -- on | off
  raw_text            TEXT,                   -- final response text only
  raw_trace_gz        BLOB,                   -- gzipped full stream-JSON / JSONL trace
  trace_format        TEXT,                   -- 'claude-stream-json' | 'codex-jsonl'
  trace_bytes_unz     INTEGER,                -- uncompressed size, for analytics
  latency_ms          INTEGER,
  tokens_in           INTEGER,
  tokens_out          INTEGER,
  cost_usd_reported   REAL,                   -- as reported by CLI (subscription-billed, not actual cash)
  session_id          TEXT,                   -- CLI session UUID for later resume/replay
  refused             INTEGER NOT NULL DEFAULT 0,  -- 0/1
  error               TEXT,                   -- non-null if the call failed
  started_at          TEXT    NOT NULL,
  finished_at         TEXT,
  FOREIGN KEY (prompt_id, prompt_version_hash) REFERENCES prompts(id, version_hash),
  FOREIGN KEY (persona_id, persona_version_hash) REFERENCES personas(id, version_hash)
);

CREATE INDEX IF NOT EXISTS idx_responses_run        ON responses(run_id);
CREATE INDEX IF NOT EXISTS idx_responses_prompt     ON responses(prompt_id);
CREATE INDEX IF NOT EXISTS idx_responses_persona    ON responses(persona_id);
CREATE INDEX IF NOT EXISTS idx_responses_model      ON responses(model_config_id);
CREATE INDEX IF NOT EXISTS idx_responses_started    ON responses(started_at);

-- Extracted ticker mentions (regex-derived, spot-checked weekly).
CREATE TABLE IF NOT EXISTS mentions (
  id              INTEGER PRIMARY KEY,
  response_id     INTEGER NOT NULL REFERENCES responses(id),
  ticker          TEXT    NOT NULL,           -- normalized uppercase, e.g. NVDA
  position        INTEGER,                    -- 1-indexed order in response (NULL if unordered)
  sentiment_hint  TEXT,                       -- 'buy' | 'hold' | 'sell' | 'avoid' | 'neutral' | NULL
  context_snippet TEXT,                       -- ±200 chars around the mention
  extraction_method TEXT NOT NULL,            -- 'regex_dollar' | 'regex_caps' | 'company_name' | 'manual'
  needs_review    INTEGER NOT NULL DEFAULT 0  -- 1 if regex flagged as ambiguous
);

CREATE INDEX IF NOT EXISTS idx_mentions_ticker     ON mentions(ticker);
CREATE INDEX IF NOT EXISTS idx_mentions_response   ON mentions(response_id);
