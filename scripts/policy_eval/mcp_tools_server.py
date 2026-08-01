#!/usr/bin/env python3
"""Minimal MCP stdio server exposing EXACTLY two tools to the retrieval model.

  web_search(query, count)  -> Brave Search API results
  http_fetch(url)           -> status, final URL, content type, and page text

This is the whole capability surface of the retrieval model. It is paired with
`--tools ""` on the Claude CLI, which removes every built-in tool (no file
reading, no shell, no built-in web tools), and with a working directory outside
this repository. The model therefore has no route to the answer key.

Every call is appended to the JSONL trace at $POLICY_EVAL_TOOL_LOG using the
existing trace record shape {i, action, args, obs}, so a reader can see exactly
what the model searched for and fetched.

The Brave token is read from the environment inside webtools.search and is never
written to the log.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policy_eval.webtools import SearchUnavailable, fetch, search  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "policyeval"

_log_lock = threading.Lock()
_counter = {"i": 0}

TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the public web. Returns up to `count` results, each with a "
            "title, a URL and a snippet. Use this to find candidate insurer or "
            "Medicare coverage policy documents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "count": {
                    "type": "integer",
                    "description": "Number of results, 1 to 20. Default 5.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "http_fetch",
        "description": (
            "Fetch a public URL over HTTP GET and return the HTTP status, the "
            "final URL after redirects, the content type and the extracted "
            "text (HTML and PDF supported). Use this to read a candidate "
            "policy document and check what it actually says."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL."}
            },
            "required": ["url"],
        },
    },
]


def _log(action: str, args: dict[str, Any], obs: Any) -> None:
    path = os.environ.get("POLICY_EVAL_TOOL_LOG")
    if not path:
        return
    with _log_lock:
        _counter["i"] += 1
        rec = {
            "i": _counter["i"],
            "action": action,
            "args": args,
            "obs": obs,
            "row_id": os.environ.get("POLICY_EVAL_ROW_ID"),
        }
        with open(path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "web_search":
        query = str(args.get("query", ""))
        count = int(args.get("count", 5) or 5)
        try:
            res = search(query, count)
        except SearchUnavailable as exc:
            res = {"error": str(exc), "result_count": 0, "results": []}
        _log(
            "web_search",
            {"query": query, "count": count},
            {
                "backend": res.get("backend"),
                "result_count": res.get("result_count"),
                "urls": [r.get("url") for r in res.get("results", [])],
                "error": res.get("error"),
            },
        )
        return {"query": query, "results": res.get("results", []),
                "result_count": res.get("result_count", 0),
                "error": res.get("error")}
    if name == "http_fetch":
        url = str(args.get("url", ""))
        res = fetch(url, max_text_chars=12000)
        _log(
            "http_fetch",
            {"url": url},
            {
                "status": res["status"],
                "final_url": res["final_url"],
                "bytes": res["bytes"],
                "sha256": res["sha256"],
                "login_wall": res["login_wall"],
                "error": res["error"],
            },
        )
        error = res["error"]
        if res.get("blocked") and not error:
            error = f"fetch blocked or unreadable: {res.get('blocked_reason')}"
        return {
            "url": url,
            "final_url": res["final_url"],
            "http_status": res["status"],
            "content_type": res["content_type"],
            "login_wall": res["login_wall"],
            "blocked": res.get("blocked", False),
            "blocked_reason": res.get("blocked_reason"),
            "error": error,
            "text": res["text"],
            "text_truncated": res["text_truncated"],
        }
    raise ValueError(f"unknown tool {name!r}")


def _send(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        mid = msg.get("id")

        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
                    },
                }
            )
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                out = _call_tool(name, args)
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(out, ensure_ascii=False),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "content": [{"type": "text", "text": f"error: {exc}"}],
                            "isError": True,
                        },
                    }
                )
        elif method in ("resources/list", "prompts/list"):
            key = "resources" if method.startswith("resources") else "prompts"
            _send({"jsonrpc": "2.0", "id": mid, "result": {key: []}})
        elif mid is not None:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": f"method {method}"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
