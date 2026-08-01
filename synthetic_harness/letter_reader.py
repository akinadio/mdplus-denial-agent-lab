"""Turn photographs or PDFs of a denial letter into text.

The retrieval agent runs with no file tools and no vision, so an uploaded photo
can never reach it. Loosening that isolation to let it open files would be the
wrong trade. Instead this module reads the upload in a separate, tightly scoped
Claude call and hands the retrieval agent plain text.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/home/clawd/.local/bin/claude")
MODEL = os.environ.get("MDPLUS_LETTER_MODEL", "claude-opus-5")
TIMEOUT_S = int(os.environ.get("MDPLUS_LETTER_TIMEOUT_S", "300"))

MAX_FILES = 8
MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024

EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}

DENY_TOOLS = [
    "Bash",
    "BashOutput",
    "Write",
    "Edit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
    "KillShell",
]

PROMPT = """These files are photographs or scans of one insurance denial letter, in page order.

Read every file, then transcribe all of the text you can see. Preserve the order of the lines. Do not summarise, do not interpret, and do not add commentary. Copy dates, member numbers, reference numbers, CPT codes, dollar amounts, policy numbers, and deadlines exactly as printed.

If a page shows a decision for more than one procedure code, keep each code on its own line with the word that follows it, such as DENIED or APPROVED. That distinction matters and must not be merged.

If you cannot read a word, write [illegible] in its place.

If the files are not a denial letter, or no text is legible at all, reply with exactly one line: UNREADABLE: followed by a short reason.

Output the transcription as plain text and nothing else."""


class AttachmentError(ValueError):
    """The client sent an attachment we will not accept."""


def decode_attachments(raw: Any) -> list[dict[str, Any]]:
    """Validate client-supplied attachments and decode them to bytes.

    Filenames from the client are never used as paths. Each file is renamed to a
    page number plus an extension derived from its declared type.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        raise AttachmentError("attachments must be a list")
    if len(raw) > MAX_FILES:
        raise AttachmentError(f"at most {MAX_FILES} files can be uploaded at once")

    files: list[dict[str, Any]] = []
    total = 0
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise AttachmentError("each attachment must be an object")
        mime = str(item.get("mime", "")).split(";")[0].strip().lower()
        if mime not in EXTENSIONS:
            raise AttachmentError(f"unsupported file type: {mime or 'unknown'}")
        payload = item.get("data", "")
        if not isinstance(payload, str) or not payload:
            raise AttachmentError("attachment is missing its data")
        if "," in payload[:64] and payload.lstrip().startswith("data:"):
            payload = payload.split(",", 1)[1]
        try:
            blob = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AttachmentError("attachment data is not valid base64") from exc
        if not blob:
            raise AttachmentError("attachment is empty")
        if len(blob) > MAX_FILE_BYTES:
            raise AttachmentError("one of the files is larger than 12 MB")
        total += len(blob)
        if total > MAX_TOTAL_BYTES:
            raise AttachmentError("the uploaded files add up to more than 40 MB")
        files.append(
            {
                "safe_name": f"page_{index}{EXTENSIONS[mime]}",
                "original_name": str(item.get("name", ""))[:200],
                "mime": mime,
                "bytes": blob,
                "size_bytes": len(blob),
            }
        )
    return files


def transcribe(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Read the uploaded pages and return their text.

    Returns a record with `text` (empty when nothing could be read), `outcome`,
    and diagnostics. Never raises for a failed read; the caller decides what to
    tell the patient.
    """
    if not files:
        return {"outcome": "no files", "text": "", "pages": 0}

    record: dict[str, Any] = {
        "pages": len(files),
        "files": [
            {
                "safe_name": f["safe_name"],
                "original_name": f["original_name"],
                "size_bytes": f["size_bytes"],
            }
            for f in files
        ],
        "model": MODEL,
    }
    workdir = Path(tempfile.mkdtemp(prefix="mdplus-letter-"))
    started = time.time()
    try:
        names = []
        for item in files:
            (workdir / item["safe_name"]).write_bytes(item["bytes"])
            names.append(item["safe_name"])
        prompt = "Files in this directory, in page order: " + ", ".join(names) + "\n\n" + PROMPT
        argv = [
            CLAUDE_BIN,
            "-p",
            prompt,
            "--model",
            MODEL,
            "--output-format",
            "json",
            "--allowedTools",
            "Read",
            "--disallowedTools",
            ",".join(DENY_TOOLS),
            "--permission-mode",
            "default",
            "--disable-slash-commands",
        ]
        env = dict(os.environ)
        env.pop("ANTHROPIC_MODEL", None)
        try:
            proc = subprocess.run(
                argv,
                cwd=str(workdir),
                env=env,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            record["outcome"] = "timed out"
            record["text"] = ""
            return record
        record["elapsed_s"] = round(time.time() - started, 1)
        if proc.returncode != 0:
            record["outcome"] = "reader exited with an error"
            record["stderr"] = (proc.stderr or "")[-800:]
            record["text"] = ""
            return record
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            record["outcome"] = "reader returned unreadable output"
            record["text"] = ""
            return record
        record["cost_usd"] = envelope.get("total_cost_usd")
        if envelope.get("is_error"):
            record["outcome"] = "reader reported an error"
            record["text"] = ""
            return record
        text = (envelope.get("result") or "").strip()
        if not text or text.upper().startswith("UNREADABLE"):
            record["outcome"] = "unreadable"
            record["reason"] = text[:300]
            record["text"] = ""
            return record
        record["outcome"] = "transcribed"
        record["text"] = text
        record["characters"] = len(text)
        return record
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def save_uploads(files: list[dict[str, Any]], dest: Path) -> list[str]:
    """Keep the uploaded pages beside the episode so a reviewer can check them.

    Uploaded denial-letter images/PDFs are raw PHI. When an encryption key is
    configured they are sealed at rest (envelope AES-256-GCM) and stored with a
    ``.enc`` suffix; otherwise they are written as-is.
    """
    from . import encryption

    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for item in files:
        data, encrypted = encryption.maybe_encrypt(item["bytes"])
        name = item["safe_name"] + (".enc" if encrypted else "")
        (dest / name).write_bytes(data)
        saved.append(name)
    return saved
