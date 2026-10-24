"""Masking (slice 6.4): a Contract's identifiers become stable placeholders on the way
to the LLM, and come back as they were in what it answers.

Only the wire is masked. One model-call middleware (`on_the_wire`, innermost) masks
each request just before the provider gets it: messages, system prompt and tool
definitions. It unmasks the response (text, tool-call arguments, the structured
Report) before anything else sees it, so the agent's state, checkpoints, tool calls
and Reports stay plaintext. A placeholder is an HMAC of the value with the Contract's
own key: the same host reads the same in every Run of that Contract, and differently
in any other.

The same middleware redacts secrets (safety.redact) for every Contract, masking or
not: alert labels and Questions reach the model without passing through a tool.
"""

import hmac
import ipaddress
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from langchain.agents.middleware import ModelResponse, wrap_model_call
from langchain.agents.middleware.types import ExtendedModelResponse
from langchain.messages import AIMessage, ToolMessage
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from aiops_agent.contracts import MASK_KEY, Contract
from aiops_agent.safety import redact

log = logging.getLogger("aiops.masking")

KINDS = ("email", "host", "name", "ip")
EMAIL = r"\b[\w.%+-]+@(?:[a-z0-9-]+\.)+[a-z]{2,}\b"
IPV4 = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
IPV6 = r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])"
# A placeholder as written, or as a model copies it without its brackets.
PLACEHOLDER = re.compile(r"<?\b(email|host|name|ip)-([0-9a-f]{8})\b>?")

Seen = dict[str, str]  # placeholder -> the text it replaced, in one request


def _ip(text: str) -> bool:
    """A real address worth hiding: not a time (12:30:45), a version, ::1 or 0.0.0.0."""
    try:
        a = ipaddress.ip_address(text)
    except ValueError:
        return False
    return not (a.is_loopback or a.is_unspecified)


class Masker:
    """One Contract's Data policy mask: its terms and shapes, keyed with its own secret."""

    def __init__(self, key: bytes, terms: list[str], emails: bool = True, ips: bool = True) -> None:
        self._key = key
        by_length = sorted(terms, key=len, reverse=True)  # acme.internal before acme
        domains = [re.escape(t) for t in by_length if "." in t]
        names = [re.escape(t) for t in by_length if "." not in t]
        parts = []  # at one position, the first that matches wins
        if emails:
            parts.append(rf"(?P<email>{EMAIL})")
        if domains:  # a domain covers its subdomains
            parts.append(rf"(?P<host>\b(?:[a-z0-9-]+\.)*(?:{'|'.join(domains)})\b)")
        if names:
            parts.append(rf"(?P<name>\b(?:{'|'.join(names)})\b)")
        if ips:
            parts.append(rf"(?P<ip>{IPV4}|{IPV6})")
        self._pattern = re.compile("|".join(parts), re.IGNORECASE)

    def placeholder(self, kind: str, value: str) -> str:
        digest = hmac.new(self._key, value.lower().encode(), "sha256").hexdigest()
        return f"<{kind}-{digest[:8]}>"

    def mask(self, text: str, seen: Seen) -> str:
        def sub(m: re.Match[str]) -> str:
            kind, value = m.lastgroup or "", m.group(0)
            if kind == "ip" and not _ip(value):
                return value
            p = self.placeholder(kind, value)
            seen.setdefault(p, value)  # restored as first written in this request
            return p

        return self._pattern.sub(sub, text)


def unmask(text: str, seen: Seen) -> str:
    """Each placeholder masked in this request back to its text; any other (a model's
    invention) stays as written."""
    return PLACEHOLDER.sub(lambda m: seen.get(f"<{m[1]}-{m[2]}>", m[0]), text)


def for_contract(contract: Contract) -> Masker | None:
    """The Contract's Masker, or None when its Data policy masks nothing."""
    m = contract.data_policy.mask
    if m is None:
        return None
    key = contract.secret(MASK_KEY).get_secret_value().encode()  # load() checked it exists
    return Masker(key, m.terms, m.emails, m.ips)


def outgoing(masker: Masker | None, text: str, seen: Seen | None = None) -> str:
    """Text as the provider may see it: secrets redacted, then identifiers masked."""
    text = redact(text)
    return masker.mask(text, {} if seen is None else seen) if masker else text


def _walk(value: Any, f: Callable[[str], str]) -> Any:
    """Every string in a JSON-like value through f. Keys stay: they are argument and
    field names, while the client's text is in the values."""
    if isinstance(value, str):
        return f(value)
    if isinstance(value, dict):
        return {k: _walk(v, f) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_walk(v, f) for v in value]
    return value


def _message(m: BaseMessage, f: Callable[[str], str]) -> BaseMessage:
    update: dict[str, Any] = {
        "content": _walk(m.content, f),
        "additional_kwargs": _walk(m.additional_kwargs, f),
    }
    if isinstance(m, AIMessage):
        update["tool_calls"] = [{**c, "args": _walk(c["args"], f)} for c in m.tool_calls]
        update["invalid_tool_calls"] = [
            {**c, "args": _walk(c.get("args"), f)} for c in m.invalid_tool_calls
        ]
    if isinstance(m, ToolMessage):  # not sent by the providers we use; masked anyway
        update["artifact"] = _walk(m.artifact, f)
    return m.model_copy(update=update)


def _tool(t: Any, f: Callable[[str], str]) -> Any:
    """A tool's definition with its descriptions masked (a cluster's namespaces can
    name the client); the BaseTool itself when nothing in it needed masking."""
    if not isinstance(t, BaseTool):
        return _walk(t, f)
    spec = convert_to_openai_tool(t)
    masked = _walk(spec, f)
    return t if masked == spec else masked


def _value(v: Any, f: Callable[[str], str]) -> Any:
    if isinstance(v, BaseModel):
        return type(v).model_validate(_walk(v.model_dump(), f))
    return _walk(v, f)


def _restore(response: Any, f: Callable[[str], str]) -> Any:
    if isinstance(response, ExtendedModelResponse):
        return replace(response, model_response=_restore(response.model_response, f))
    if isinstance(response, ModelResponse):
        return ModelResponse(
            result=[_message(m, f) for m in response.result],
            structured_response=_value(response.structured_response, f),
        )
    return _message(response, f)


MaskSink = Callable[[list[str]], Awaitable[None]]  # placeholders sent in one request
# Added to a masking Contract's system prompt: a shortened placeholder (`<host>`, seen
# on Haiku) can't be restored and reaches the Report as written.
NOTE = """
Masked values: the client's names, hosts, emails and IPs appear as placeholders like
<host-3f9a1c2e>. Use them as if they were the values, in tool calls too, and copy each
one whole every time you write it: never shorten one to <host> or drop its brackets."""


def _noted(system: BaseMessage | None) -> BaseMessage:
    if system is None:
        return SystemMessage(content=NOTE.lstrip())
    content = system.content
    noted = (
        content + NOTE if isinstance(content, str) else [*content, {"type": "text", "text": NOTE}]
    )
    return system.model_copy(update={"content": noted})


def on_the_wire(masker: Masker | None, sink: MaskSink | None = None) -> Any:
    """The model-call middleware: redact (every Contract) and mask (a Contract whose
    Data policy says so) each request; unmask its response. Innermost, so the other
    middleware and the agent's state only ever see plaintext."""

    @wrap_model_call
    async def wire(request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        seen: Seen = {}

        def out(s: str) -> str:
            return outgoing(masker, s, seen)

        system = request.system_message
        if system is not None:
            system = _message(system, out)
        if masker:
            system = _noted(system)
        response = await handler(
            request.override(
                messages=[_message(m, out) for m in request.messages],
                system_message=system,
                tools=[_tool(t, out) for t in request.tools] if masker else request.tools,
            )
        )
        if not seen:
            return response
        if sink:
            try:
                await sink(sorted(seen))
            except Exception:
                log.exception("could not record what was masked")
        return _restore(response, lambda s: unmask(s, seen))

    return wire
