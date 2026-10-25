"""Shared Claude calls for the SEO autopilot (draft, refresh, review, keyword triage).

One place for model choice, refusal fallback, prompt caching and stop-reason
handling, so every agent fails the same, visible way.
"""
import json
import os
import sys

MODEL = os.environ.get("SEO_MODEL", "claude-opus-5")


class LLMError(RuntimeError):
    pass


def _client():
    import anthropic  # imported lazily so dry runs work without the SDK
    return anthropic.Anthropic()


def call(system, blocks, *, effort="high", schema=None, max_tokens=64000):
    """Stream one request; return text, or parsed JSON when a schema is given.

    blocks: list of user text blocks; the first ones should be the stable,
    cacheable context (data, examples) and the last the per-call instruction.
    """
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    import anthropic
    content = [{"type": "text", "text": b} for b in blocks]
    if len(content) > 1:
        content[-2]["cache_control"] = {"type": "ephemeral"}
    try:
        msg = _stream(system, content, output_config, max_tokens)
    except anthropic.APIError as e:  # rate limits, overload, auth: the caller skips this item
        raise LLMError(f"{type(e).__name__}: {e}") from e
    return _finish(msg, schema)


def _stream(system, content, output_config, max_tokens):
    with _client().beta.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config=output_config,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
    ) as stream:
        return stream.get_final_message()


def _finish(msg, schema):
    if msg.stop_reason == "refusal":
        raise LLMError(f"refused ({getattr(msg.stop_details, 'category', None)})")
    if msg.stop_reason == "max_tokens":
        raise LLMError("output cut off at max_tokens")
    u = msg.usage
    print(f"  llm model={msg.model} in={u.input_tokens} out={u.output_tokens} "
          f"cache_read={u.cache_read_input_tokens}", file=sys.stderr)
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return json.loads(text) if schema else text
