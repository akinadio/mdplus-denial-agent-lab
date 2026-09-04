"""Multi-provider agent loop — run the SAME two-tool retrieval agent on
Anthropic (Claude), OpenAI (GPT), or Google (Gemini).

Why this exists
---------------
The moat is accuracy: OrthoAppeals grounds every appeal in the payer's *actual*
current policy instead of a model's memory. To prove which model does that best
— and to avoid betting the product on one vendor — we need to run the identical
task, with the identical tools and prompts, across providers and compare.

Everything that matters for a fair comparison is held constant here: the system
prompt, the user prompt, the two tools (`web_search`, `http_fetch`) and their
in-process implementations, and the strict-JSON output contract. Providers differ
only in four mechanical ways, which is all this module abstracts:

  1. the SDK client,
  2. how tools are declared,
  3. how the model requests a tool call and how a tool result is returned,
  4. where token usage lives on the response.

Each provider exposes the same surface: `available()`, `default_model()`,
`make_client()`, `run()` (drive the tool loop to a final text answer, returning
the running transcript so a repair round can continue it), and `continue_once()`
(one more turn on the same transcript). Tool execution is passed in as a plain
`tool_call(name, args) -> dict` callable, so the caller owns logging/tracing and
the providers stay stateless.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

# --- canonical tool definitions (provider-independent) ---------------------
# One source of truth; each provider formats these into its own schema shape.
CANONICAL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "description": (
            "Search the public web. Returns up to `count` results, each with a "
            "title, a URL and a snippet. Use this to find candidate insurer or "
            "Medicare coverage policy documents."
        ),
        "parameters": {
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
            "final URL after redirects, the content type and the extracted text "
            "(HTML and PDF supported). Use this to read a candidate policy "
            "document and check what it actually says."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL."}
            },
            "required": ["url"],
        },
    },
]

ToolCall = Callable[[str, dict[str, Any]], dict[str, Any]]

# Models that must use /v1/responses rather than /v1/chat/completions when
# function tools are in play. Seeded from env, grown at runtime from the 400.
RESPONSES_API_MODELS: set[str] = {
    m.strip() for m in os.environ.get(
        "MDPLUS_OPENAI_RESPONSES_MODELS", "gpt-5.6-luna,gpt-5.6-sol"
    ).split(",") if m.strip()
}


# Fields the Responses API emits on an output item but refuses to accept back
# on the next turn's input. Echoing the transcript verbatim 400s on them, so we
# strip these and learn any others from the "Unknown parameter" the API returns.
_ECHO_DROP: set[str] = {"status"}


def _strip_echo(obj: Any, keys: set[str]) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_echo(v, keys) for k, v in obj.items()
                if k not in keys and v is not None}
    if isinstance(obj, list):
        return [_strip_echo(v, keys) for v in obj]
    return obj


_UNKNOWN_PARAM = re.compile(r"Unknown parameter: '([^']+)'")


def _unknown_param_key(exc: Exception) -> str | None:
    """'input[2].content[0].annotations' -> 'annotations'."""
    m = _UNKNOWN_PARAM.search(str(exc))
    if not m:
        return None
    leaf = m.group(1).split(".")[-1].split("[")[0].strip()
    return leaf or None


def _needs_responses_api(exc: Exception) -> bool:
    m = str(exc)
    return "/v1/responses" in m or "reasoning_effort" in m




def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


# --------------------------------------------------------------------------
# Anthropic (Claude)
# --------------------------------------------------------------------------
class AnthropicProvider:
    name = "anthropic"
    key_env = "ANTHROPIC_API_KEY"

    def default_model(self) -> str:
        return os.environ.get("MDPLUS_API_MODEL", "claude-opus-5")

    def available(self) -> bool:
        if not os.environ.get(self.key_env):
            return False
        try:  # pragma: no cover - import availability is environment-dependent
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def make_client(self, timeout: int) -> Any:
        import anthropic

        return anthropic.Anthropic(
            api_key=os.environ[self.key_env],
            max_retries=int(os.environ.get("MDPLUS_API_MAX_RETRIES", "4")),
            timeout=float(timeout),
        )

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in CANONICAL_TOOLS
        ]

    @staticmethod
    def _text(content: list[Any]) -> str:
        return "".join(
            b.text for b in content if getattr(b, "type", None) == "text"
        )

    @staticmethod
    def _acc(usage: dict[str, int], resp: Any) -> None:
        u = getattr(resp, "usage", None)
        if u is not None:
            usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0

    def run(self, *, client, model, system, prompt, tool_call, deadline, usage,
            max_iters, max_tokens):
        tools = self._tools()
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        final_text, stop = "", "max_iterations"
        for _ in range(max_iters):
            if time.time() > deadline:
                stop = "timeout"
                break
            resp = client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                tools=tools, messages=messages,
            )
            self._acc(usage, resp)
            stop = resp.stop_reason
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                final_text = self._text(resp.content)
                break
            results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                out = tool_call(block.name, dict(block.input or {}))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _dumps(out),
                })
            messages.append({"role": "user", "content": results})
        return final_text, messages, stop

    def continue_once(self, *, client, model, system, transcript, ask, usage, max_tokens):
        messages = transcript + [{"role": "user", "content": ask}]
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            tools=self._tools(), messages=messages,
        )
        self._acc(usage, resp)
        return self._text(resp.content)


# --------------------------------------------------------------------------
# OpenAI (GPT)
# --------------------------------------------------------------------------
class OpenAIProvider:
    name = "openai"
    key_env = "OPENAI_API_KEY"

    def default_model(self) -> str:
        return os.environ.get("MDPLUS_OPENAI_MODEL", "gpt-4o")

    def available(self) -> bool:
        if not os.environ.get(self.key_env):
            return False
        try:  # pragma: no cover
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def make_client(self, timeout: int) -> Any:
        import openai

        return openai.OpenAI(
            api_key=os.environ[self.key_env],
            max_retries=int(os.environ.get("MDPLUS_API_MAX_RETRIES", "4")),
            timeout=float(timeout),
        )

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["parameters"]}}
            for t in CANONICAL_TOOLS
        ]

    def _create(self, client, **kw):
        """Create a completion, tolerating the max_tokens vs max_completion_tokens
        split between older chat models and the newer o-series / gpt-5 family."""
        limit = kw.pop("_max_tokens", None)
        if limit is not None:
            try:
                return client.chat.completions.create(max_tokens=limit, **kw)
            except Exception as exc:  # noqa: BLE001
                if "max_tokens" in str(exc) or "max_completion_tokens" in str(exc):
                    return client.chat.completions.create(
                        max_completion_tokens=limit, **kw)
                raise
        return client.chat.completions.create(**kw)

    @staticmethod
    def _acc(usage: dict[str, int], resp: Any) -> None:
        u = getattr(resp, "usage", None)
        if u is not None:
            usage["input_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            usage["output_tokens"] += getattr(u, "completion_tokens", 0) or 0

    def _run_chat(self, *, client, model, system, prompt, tool_call, deadline, usage,
            max_iters, max_tokens):
        tools = self._tools()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        final_text, stop = "", "max_iterations"
        for _ in range(max_iters):
            if time.time() > deadline:
                stop = "timeout"
                break
            resp = self._create(
                client, model=model, messages=messages, tools=tools,
                tool_choice="auto", _max_tokens=max_tokens,
            )
            self._acc(usage, resp)
            choice = resp.choices[0]
            msg = choice.message
            stop = choice.finish_reason
            calls = getattr(msg, "tool_calls", None) or []
            asst: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if calls:
                asst["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name,
                                  "arguments": c.function.arguments}}
                    for c in calls
                ]
            messages.append(asst)
            if not calls:
                final_text = msg.content or ""
                break
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = tool_call(c.function.name, args)
                messages.append({
                    "role": "tool", "tool_call_id": c.id, "content": _dumps(out),
                })
        return final_text, messages, stop

    def _continue_chat(self, *, client, model, system, transcript, ask, usage, max_tokens):
        messages = transcript + [{"role": "user", "content": ask}]
        resp = self._create(
            client, model=model, messages=messages, tools=self._tools(),
            tool_choice="auto", _max_tokens=max_tokens,
        )
        self._acc(usage, resp)
        return resp.choices[0].message.content or ""

    # --- Responses API path -------------------------------------------------
    # gpt-5.x reasoning models reject function tools on /v1/chat/completions
    # unless reasoning_effort is 'none'. Forcing 'none' would handicap the
    # comparison arm -- the ChatGPT free tier reasons by default -- so we move
    # those models to /v1/responses instead and leave reasoning at the model's
    # own default. The switch is discovered from the 400, then remembered.

    def _responses_tools(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "name": t["name"],
             "description": t["description"], "parameters": t["parameters"]}
            for t in CANONICAL_TOOLS
        ]

    @staticmethod
    def _acc_responses(usage: dict[str, int], resp: Any) -> None:
        u = getattr(resp, "usage", None)
        if u is not None:
            usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0

    @staticmethod
    def _as_item(o: Any) -> Any:
        return o.model_dump() if hasattr(o, "model_dump") else o

    def _responses_create(self, client, **kw):
        """store=False keeps the study's letters off OpenAI's servers; the
        encrypted-reasoning include is what lets a reasoning model carry its
        chain across tool turns without server-side state. Both degrade.

        The API is asymmetric about its own transcript -- it emits fields on an
        output item that it rejects when that item comes back as input -- so
        offending keys are stripped, and any the API names in a 400 are added
        to the drop set and the call retried."""
        if not hasattr(client, "responses"):
            raise RuntimeError(
                "This openai SDK has no Responses API. Run: pip install -U openai")
        drop = getattr(self, "_echo_drop", None)
        if drop is None:
            drop = self._echo_drop = set(_ECHO_DROP)
        raw_input = kw.pop("input")
        include: list[str] | None = ["reasoning.encrypted_content"]
        for _ in range(8):
            payload = dict(kw, input=_strip_echo(raw_input, drop), store=False)
            if include:
                payload["include"] = include
            try:
                return client.responses.create(**payload)
            except Exception as exc:  # noqa: BLE001
                m = str(exc)
                if include and ("include" in m or "encrypted" in m):
                    include = None
                    continue
                key = _unknown_param_key(exc)
                if key and key not in drop and key not in ("input", "tools"):
                    drop.add(key)
                    continue
                raise
        raise RuntimeError(
            f"Responses API kept rejecting echoed transcript fields; dropped {sorted(drop)}")

    def _run_responses(self, *, client, model, system, prompt, tool_call, deadline,
                       usage, max_iters, max_tokens):
        tools = self._responses_tools()
        items: list[Any] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        final_text, stop = "", "max_iterations"
        for _ in range(max_iters):
            if time.time() > deadline:
                stop = "timeout"
                break
            resp = self._responses_create(
                client, model=model, input=items, tools=tools,
                tool_choice="auto", max_output_tokens=max_tokens)
            self._acc_responses(usage, resp)
            out = list(getattr(resp, "output", []) or [])
            items.extend(self._as_item(o) for o in out)
            calls = [o for o in out if getattr(o, "type", None) == "function_call"]
            if not calls:
                final_text = getattr(resp, "output_text", "") or ""
                stop = getattr(resp, "status", None) or "stop"
                if stop == "incomplete":
                    d = getattr(resp, "incomplete_details", None)
                    stop = getattr(d, "reason", None) or "incomplete"
                break
            for c in calls:
                try:
                    args = json.loads(getattr(c, "arguments", "") or "{}")
                except json.JSONDecodeError:
                    args = {}
                items.append({
                    "type": "function_call_output",
                    "call_id": c.call_id,
                    "output": _dumps(tool_call(c.name, args)),
                })
        return final_text, items, stop

    def _continue_responses(self, *, client, model, transcript, ask, usage, max_tokens):
        items = list(transcript) + [{"role": "user", "content": ask}]
        resp = self._responses_create(
            client, model=model, input=items, tools=self._responses_tools(),
            tool_choice="auto", max_output_tokens=max_tokens)
        self._acc_responses(usage, resp)
        return getattr(resp, "output_text", "") or ""

    # --- dispatch -----------------------------------------------------------
    def run(self, *, client, model, system, prompt, tool_call, deadline, usage,
            max_iters, max_tokens):
        kw = dict(client=client, model=model, system=system, prompt=prompt,
                  tool_call=tool_call, deadline=deadline, usage=usage,
                  max_iters=max_iters, max_tokens=max_tokens)
        if model in RESPONSES_API_MODELS:
            return self._run_responses(**kw)
        try:
            return self._run_chat(**kw)
        except Exception as exc:  # noqa: BLE001
            if not _needs_responses_api(exc):
                raise
            RESPONSES_API_MODELS.add(model)
            return self._run_responses(**kw)

    def continue_once(self, *, client, model, system, transcript, ask, usage, max_tokens):
        if model in RESPONSES_API_MODELS:
            return self._continue_responses(
                client=client, model=model, transcript=transcript, ask=ask,
                usage=usage, max_tokens=max_tokens)
        return self._continue_chat(
            client=client, model=model, system=system, transcript=transcript,
            ask=ask, usage=usage, max_tokens=max_tokens)


# --------------------------------------------------------------------------
# Google (Gemini) — new `google-genai` SDK
# --------------------------------------------------------------------------
class GoogleProvider:
    name = "google"
    key_env = "GOOGLE_API_KEY"

    def default_model(self) -> str:
        return os.environ.get("MDPLUS_GOOGLE_MODEL", "gemini-2.5-pro")

    def available(self) -> bool:
        if not (os.environ.get(self.key_env) or os.environ.get("GEMINI_API_KEY")):
            return False
        try:  # pragma: no cover
            from google import genai  # noqa: F401
        except ImportError:
            return False
        return True

    def make_client(self, timeout: int) -> Any:  # noqa: ARG002 - timeout via config
        from google import genai

        return genai.Client(
            api_key=os.environ.get(self.key_env) or os.environ["GEMINI_API_KEY"]
        )

    def _tools_and_config(self, system: str, max_tokens: int):
        from google.genai import types

        decls = [
            types.FunctionDeclaration(
                name=t["name"], description=t["description"],
                parameters=t["parameters"],
            )
            for t in CANONICAL_TOOLS
        ]
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)],
            max_output_tokens=max_tokens,
        )
        return cfg, types

    @staticmethod
    def _acc(usage: dict[str, int], resp: Any) -> None:
        u = getattr(resp, "usage_metadata", None)
        if u is not None:
            usage["input_tokens"] += getattr(u, "prompt_token_count", 0) or 0
            usage["output_tokens"] += getattr(u, "candidates_token_count", 0) or 0

    @staticmethod
    def _parts(resp: Any):
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            return None, []
        content = cands[0].content
        return content, list(getattr(content, "parts", None) or [])

    def run(self, *, client, model, system, prompt, tool_call, deadline, usage,
            max_iters, max_tokens):
        cfg, types = self._tools_and_config(system, max_tokens)
        contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
        final_text, stop = "", "max_iterations"
        for _ in range(max_iters):
            if time.time() > deadline:
                stop = "timeout"
                break
            resp = client.models.generate_content(
                model=model, contents=contents, config=cfg)
            self._acc(usage, resp)
            content, parts = self._parts(resp)
            fcalls = [p.function_call for p in parts
                      if getattr(p, "function_call", None)]
            if content is not None:
                contents.append(content)
            if not fcalls:
                stop = "stop"
                final_text = "".join(
                    getattr(p, "text", "") or "" for p in parts)
                break
            stop = "tool_use"
            fr_parts = []
            for fc in fcalls:
                out = tool_call(fc.name, dict(fc.args or {}))
                fr_parts.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name, response={"result": out})))
            contents.append(types.Content(role="user", parts=fr_parts))
        return final_text, contents, stop

    def continue_once(self, *, client, model, system, transcript, ask, usage, max_tokens):
        cfg, types = self._tools_and_config(system, max_tokens)
        contents = list(transcript) + [
            types.Content(role="user", parts=[types.Part(text=ask)])]
        resp = client.models.generate_content(
            model=model, contents=contents, config=cfg)
        self._acc(usage, resp)
        _, parts = self._parts(resp)
        return "".join(getattr(p, "text", "") or "" for p in parts)


_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
    "gemini": GoogleProvider,  # friendly alias
}


def get_provider(name: str | None = None):
    """Return the provider adapter. Defaults to MDPLUS_ENGINE_PROVIDER, then
    'anthropic'. Raises ValueError on an unknown name."""
    key = (name or os.environ.get("MDPLUS_ENGINE_PROVIDER") or "anthropic").lower()
    if key not in _PROVIDERS:
        raise ValueError(
            f"unknown provider {key!r}; choose one of "
            f"{sorted(set(_PROVIDERS))}"
        )
    return _PROVIDERS[key]()


def provider_names() -> list[str]:
    return ["anthropic", "openai", "google"]
