"""Scrubbing for the recorders (evals/record_*.py). This repo is public: a recording
from a real account maps its ids and names to fixed fakes, drops the fields that say
who called from where, and isn't written if a real value survives."""

import re
import sys
from collections.abc import Callable
from typing import Any


def scrubber(fakes: dict[str, str], dropped: set[str]) -> Callable[[Any], Any]:
    """Every real value in `fakes` replaced, case-insensitively, in keys and values;
    keys in `dropped` removed at any depth."""
    # Longest first, so an email goes whole before its user name does.
    pattern = re.compile(
        "|".join(re.escape(k) for k in sorted(fakes, key=len, reverse=True)), re.IGNORECASE
    )
    lower = {k.lower(): v for k, v in fakes.items()}

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {scrub(k): scrub(v) for k, v in value.items() if k not in dropped}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            return pattern.sub(lambda m: lower[m[0].lower()], value)
        return value

    return scrub


def refuse_leaks(text: str, fakes: dict[str, str]) -> None:
    if leaked := [k for k in fakes if k.lower() in text.lower()]:
        sys.exit(f"not written: {len(leaked)} real value(s) survived the scrub")
