"""Vendor MCP servers the Hub may start, by name: a Contract says `vendor: <name>`.

The command lives here, in the Hub's code, never in the contracts repo: whoever can
push there must not be able to run a program next to every Contract's keys (the
reasoning of ADR 0002 for kubeconfig exec plugins). For the same reason a Contract
may set only the variables its vendor's entry lists: `LD_PRELOAD`, `PATH`,
`NODE_OPTIONS` and the like would run code all the same. Each binary ships in the
image, pinned and checksum-verified like sops. Grafana arrives in slice 4.3.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Spec:
    command: tuple[str, ...]  # command[0] an absolute path: PATH can't redirect it
    env: frozenset[str]  # the only variables a Contract may set for it

    def __post_init__(self) -> None:
        if not Path(self.command[0]).is_absolute():
            raise ValueError(f"vendor command must be an absolute path: {self.command[0]!r}")


VENDORS: dict[str, Spec] = {}
START_SECONDS = 30  # a vendor that never finishes MCP's handshake fails the Run
CALL_SECONDS = 60  # each vendor tool call
