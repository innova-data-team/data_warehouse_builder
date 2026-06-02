"""JSON helpers: deep flattening for nested objects/arrays."""

from __future__ import annotations

from typing import Any


def flatten_json(
    obj: Any,
    *,
    parent_key: str = "",
    sep: str = ".",
    list_strategy: str = "index",
) -> dict[str, Any]:
    """Flatten a (possibly nested) JSON-like object into a single-level dict.

    Parameters
    ----------
    obj
        A ``dict``, ``list``, or scalar.
    parent_key
        Used internally during recursion; leave empty.
    sep
        Separator between path components in the output keys.
    list_strategy
        - ``"index"``  → ``items.0.name``, ``items.1.name``…
        - ``"join"``   → join scalars with ``", "``; recurse into dicts.

    The resulting dict preserves "source path" via its keys, which the
    Bronze loader can store in column metadata.
    """
    out: dict[str, Any] = {}

    def _recurse(value: Any, key: str) -> None:
        if isinstance(value, dict):
            if not value:
                out[key or "_root"] = None
                return
            for k, v in value.items():
                new_key = f"{key}{sep}{k}" if key else str(k)
                _recurse(v, new_key)
        elif isinstance(value, list):
            if not value:
                out[key or "_root"] = None
                return
            if list_strategy == "index":
                for i, v in enumerate(value):
                    new_key = f"{key}{sep}{i}" if key else str(i)
                    _recurse(v, new_key)
            else:  # "join"
                scalars, nested = [], []
                for v in value:
                    (nested if isinstance(v, (dict, list)) else scalars).append(v)
                if scalars:
                    out[key or "_root"] = ", ".join(str(s) for s in scalars)
                for i, v in enumerate(nested):
                    _recurse(v, f"{key}{sep}{i}" if key else str(i))
        else:
            out[key or "_root"] = value

    _recurse(obj, parent_key)
    return out


def is_jsonl(text: str) -> bool:
    """Cheap heuristic: at least 2 lines that each start with ``{`` or ``[``."""
    head = [ln.strip() for ln in text.splitlines() if ln.strip()][:5]
    if len(head) < 2:
        return False
    return all(ln.startswith(("{", "[")) for ln in head)
