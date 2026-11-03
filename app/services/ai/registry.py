"""Provider registry and per-capability eligibility. A provider's general approval never enables
a capability: each capability lists its own permitted data classes."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_CLASSES = ("public_content", "synthetic", "deidentified", "phi")
CAPABILITIES = ("generation", "embeddings", "reranking", "transcription", "voice", "vendor_hosted_tools")
AGREEMENT = ("unknown", "pending", "signed", "not_applicable")
_PATH = Path(os.getenv("MYOS_PROVIDER_REGISTRY") or Path(__file__).with_name("providers.json"))
_cache: Optional[Dict[str, Any]] = None


def load(path: Optional[str] = None) -> Dict[str, Any]:
    global _cache
    if path:
        return json.loads(Path(path).read_text())
    if _cache is None:
        _cache = json.loads(_PATH.read_text())
    return _cache


def set_config(cfg: Optional[Dict[str, Any]]) -> None:
    """Swap the active registry (tests, and the config-only provider switch)."""
    global _cache
    _cache = cfg


@dataclass
class Choice:
    provider: str
    model: str


def eligible(cfg: Dict[str, Any], provider: str, capability: str, data_class: str, model: Optional[str] = None) -> Optional[str]:
    """Return None if eligible, else the reason (never contains clinical text)."""
    p = cfg["providers"].get(provider)
    if not p or not p.get("enabled"):
        return "provider_disabled"
    cap = (p.get("capabilities") or {}).get(capability)
    if not cap or not cap.get("enabled"):
        return "capability_not_enabled"
    if model and cap.get("models") and model not in cap["models"]:
        return "model_not_approved"
    if data_class not in (cap.get("data_classes") or []):
        return "data_class_not_permitted"
    if data_class == "phi":
        ag = p.get("agreements") or {}
        if p.get("region") == "us" and ag.get("baa") != "signed":
            return "baa_not_signed"
        if ag.get("dpa") not in ("signed", "not_applicable"):
            return "dpa_not_signed"
    return None


def chain(cfg: Dict[str, Any], clinic_slug: Optional[str], task: str) -> List[Choice]:
    r = cfg.get("routing") or {}
    entries = ((r.get("clinics") or {}).get(clinic_slug or "") or {}).get(task) or (r.get("default") or {}).get(task) or []
    out = []
    for e in entries:
        prov, _, model = e.partition(":")
        out.append(Choice(prov, model))
    return out


def clinic_data_class(cfg: Dict[str, Any], clinic) -> str:
    if clinic is not None and getattr(clinic, "is_demo", False):
        return "synthetic"
    m = cfg.get("clinic_data_class") or {}
    return m.get(getattr(clinic, "slug", None) or "", m.get("_default", "phi"))


def validate(cfg: Dict[str, Any]) -> List[str]:
    errs = []
    for name, p in cfg["providers"].items():
        for k in ("account_label", "endpoint", "region", "agreements", "retention", "review", "capabilities"):
            if k not in p:
                errs.append(f"{name}: missing {k}")
        for a in (p.get("agreements") or {}).values():
            if a not in AGREEMENT:
                errs.append(f"{name}: bad agreement status {a}")
        for c, v in (p.get("capabilities") or {}).items():
            if c not in CAPABILITIES:
                errs.append(f"{name}: unknown capability {c}")
            for d in v.get("data_classes") or []:
                if d not in DATA_CLASSES:
                    errs.append(f"{name}.{c}: unknown data class {d}")
        blob = json.dumps(p).lower()
        if "sk-" in blob or "api_key\":" in blob:
            errs.append(f"{name}: looks like a secret in the registry")
    return errs
