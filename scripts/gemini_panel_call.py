#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai>=0.8.0"]
# ///
"""Pythia panel caller for the Gemini API with Google Search grounding.

Invoked by scripts/run_panel.py as a subprocess (provider: gemini).
Reads the full prompt from stdin and emits JSONL events to stdout that
parse_gemini_jsonl() in the orchestrator consumes.

Event schema:
  {"type":"init",     "model":"gemini-flash-latest", "session_id":"<uuid>"}
  {"type":"grounding","sources":[{"uri":"...","title":"..."}]}
  {"type":"result",   "model":"gemini-3.5-flash", "tokens_in":N, "tokens_out":M, "duration_ms":N, "text":"<full>"}
  {"type":"error",    "message":"..."}

The init event carries the requested model (possibly a floating alias);
the result event carries the resolved model id from resp.model_version.

Quota errors are surfaced with the string "RESOURCE_EXHAUSTED" so the
orchestrator's QUOTA_EXHAUSTED_PAT trips and the provider is blocked for
the remainder of the run.
"""

import argparse
import json
import os
import sys
import time
import uuid


def emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-flash-latest")
    ap.add_argument("--no-grounding", action="store_true")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        emit({"type": "error", "message": "GEMINI_API_KEY not set"})
        return 2

    prompt = sys.stdin.read()
    if not prompt.strip():
        emit({"type": "error", "message": "empty prompt on stdin"})
        return 2

    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        emit({"type": "error", "message": f"google-genai not installed: {e}"})
        return 2

    session_id = str(uuid.uuid4())
    emit({"type": "init", "model": args.model, "session_id": session_id})

    client = genai.Client(api_key=api_key)
    tools = None if args.no_grounding else [
        types.Tool(google_search=types.GoogleSearch())
    ]
    config = types.GenerateContentConfig(tools=tools) if tools else None

    started = time.monotonic()
    try:
        resp = client.models.generate_content(
            model=args.model,
            contents=prompt,
            config=config,
        )
    except Exception as e:
        msg = str(e)
        # Surface 429s / quota errors with the magic string the orchestrator
        # scans for so the provider gets blocked for the rest of the run.
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            emit({"type": "error", "message": f"RESOURCE_EXHAUSTED: {msg}"})
            return 3
        emit({"type": "error", "message": msg})
        return 1

    elapsed_ms = int((time.monotonic() - started) * 1000)
    text = resp.text or ""

    sources: list[dict] = []
    try:
        gm = resp.candidates[0].grounding_metadata
        if gm and gm.grounding_chunks:
            for chunk in gm.grounding_chunks:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    sources.append({
                        "uri": web.uri,
                        "title": getattr(web, "title", "") or "",
                    })
    except (AttributeError, IndexError, TypeError):
        pass
    if sources:
        emit({"type": "grounding", "sources": sources})

    usage = resp.usage_metadata
    tokens_in = getattr(usage, "prompt_token_count", 0) or 0
    tokens_out = getattr(usage, "candidates_token_count", 0) or 0
    emit({
        "type": "result",
        "model": getattr(resp, "model_version", None) or args.model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "duration_ms": elapsed_ms,
        "text": text,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
