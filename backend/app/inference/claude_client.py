"""One way to reach Claude, behind one function.

- agent_sdk : Claude Agent SDK. Runs the Claude Code binary as a subprocess, so it can use the
              owner's own Claude Code login / long-lived token (CLAUDE_CODE_OAUTH_TOKEN from
              `claude setup-token`). Intended for personal, single-user use. No API key, no
              per-call billing.

The former "api" backend (Anthropic API key) was removed on purpose: this project runs on
free tiers only and never holds a paid, keyed API credential.

Returns a dict already validated against the requested JSON schema.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..core.config import settings

log = logging.getLogger(__name__)


class InferenceError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise InferenceError("no JSON object in model output")
    return json.loads(text[start : end + 1])


# ---------------------------------------------------------------- agent sdk
async def _agent_sdk_async(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    options = ClaudeAgentOptions(
        system_prompt=system,
        allowed_tools=[],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Agent", "Task"],
        permission_mode="dontAsk",
        max_turns=4,  # structured output uses an internal tool call, which counts as a turn
        model=settings.claude_model,
        output_format={"type": "json_schema", "schema": schema},
    )
    result: dict[str, Any] | None = None
    text_parts: list[str] = []
    async for message in query(prompt=user, options=options):
        if isinstance(message, ResultMessage):
            if getattr(message, "structured_output", None):
                result = message.structured_output  # type: ignore[assignment]
            elif getattr(message, "result", None):
                text_parts.append(str(message.result))
    if result is None:
        if not text_parts:
            raise InferenceError("agent sdk returned no result")
        result = _extract_json("".join(text_parts))
    return result


def _agent_sdk(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_agent_sdk_async(system, user, schema))


def complete_json(system: str, user: str, schema: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Return (data, backend_used). Raises InferenceError when no LLM backend is usable."""
    backend = settings.inference_backend
    if backend == "rules":
        raise InferenceError("rules backend selected")
    if backend != "agent_sdk":
        raise InferenceError(f"unknown backend {backend}")
    try:
        return _agent_sdk(system, user, schema), "agent_sdk"
    except InferenceError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("inference backend %s failed", backend)
        raise InferenceError(str(exc)) from exc
