import os
import random
import re
from contextvars import ContextVar
from typing import Dict, Optional, Tuple

TRACEPARENT_REGEX = re.compile(r"^00-([a-f0-9]{32})-([a-f0-9]{16})-([a-f0-9]{2})$")

_current_trace_id: ContextVar[Optional[str]] = ContextVar("current_trace_id", default=None)
_current_span_id: ContextVar[Optional[str]] = ContextVar("current_span_id", default=None)


def generate_trace_id() -> str:
    return f"{random.getrandbits(128):032x}"


def generate_span_id() -> str:
    return f"{random.getrandbits(64):016x}"


def parse_traceparent(header_val: str) -> Optional[Tuple[str, str, str]]:
    if not header_val or not isinstance(header_val, str):
        return None
    match = TRACEPARENT_REGEX.match(header_val.strip())
    if match:
        return match.group(1), match.group(2), match.group(3)
    return None


def make_traceparent(trace_id: Optional[str] = None, span_id: Optional[str] = None, flags: str = "01") -> str:
    tid = trace_id or get_current_trace_id() or generate_trace_id()
    sid = span_id or generate_span_id()
    return f"00-{tid}-{sid}-{flags}"


def set_trace_context(trace_id: Optional[str] = None, span_id: Optional[str] = None):
    tid = trace_id or generate_trace_id()
    sid = span_id or generate_span_id()
    _current_trace_id.set(tid)
    _current_span_id.set(sid)
    return tid, sid


def get_current_trace_id() -> str:
    tid = _current_trace_id.get()
    if not tid:
        tid = generate_trace_id()
        _current_trace_id.set(tid)
    return tid


def get_current_span_id() -> str:
    sid = _current_span_id.get()
    if not sid:
        sid = generate_span_id()
        _current_span_id.set(sid)
    return sid


def get_trace_headers(trace_id: Optional[str] = None, span_id: Optional[str] = None) -> Dict[str, str]:
    return {
        "traceparent": make_traceparent(trace_id=trace_id, span_id=span_id),
        "X-Trace-ID": trace_id or get_current_trace_id()
    }
