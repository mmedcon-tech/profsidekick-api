"""Operational model log: which provider/model handled a request and why fallback happened.
Never contains message text, prompts, source passages or patient identifiers."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger("myos.model_ops")
ALLOWED = {"request_id", "clinic", "task", "data_class", "provider", "model", "outcome", "error_kind",
           "fallback_from", "fallback_reason", "skipped", "latency_ms", "attempt", "tokens_in", "tokens_out",
           "provider_request_id"}


def record(**fields: Any) -> Dict[str, Any]:
    ev = {k: v for k, v in fields.items() if k in ALLOWED and v is not None}
    logger.info("model_op %s", json.dumps(ev, sort_keys=True, default=str))
    return ev
