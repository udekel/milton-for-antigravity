import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.utils.pii_redactor import PIIRedactor
from app.utils.tracing import get_current_span_id, get_current_trace_id


class JSONLogFormatter(logging.Formatter):
    """Structured JSON Log Formatter with PII Redaction and OpenTelemetry Trace Context."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", get_current_trace_id()),
            "span_id": getattr(record, "span_id", get_current_span_id()),
            "message": PIIRedactor.redact_text(record.getMessage())
        }

        # Include additional structured context attributes
        for attr in ("session_id", "event_type", "tool_name", "step_idx", "status_code"):
            if hasattr(record, attr):
                val = getattr(record, attr)
                log_obj[attr] = PIIRedactor.redact_data(val)

        if record.exc_info:
            log_obj["exception"] = PIIRedactor.redact_text(self.formatException(record.exc_info))

        return json.dumps(log_obj)


def get_json_logger(name: str = "milton") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONLogFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
