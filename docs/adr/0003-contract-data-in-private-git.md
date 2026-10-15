# Contract data lives in one private git repo, never in this one

This repository is public, so it never holds Contract data. Config, credentials, Runbooks and eval Scenarios live in one private contracts repo, with one directory per Contract. Investigations, recorded tool results and Teachings live in the Hub's Postgres. The Hub reads the contracts repo through a read-only deploy key and never pushes to it. Secrets are encrypted with SOPS, using a separate age key per Contract, so one Contract's key can't decrypt another's. Git history is the audit trail for config. The web console shows the effective config read-only and never edits it, so nothing exists in the console that git doesn't hold. CI and the public tests run on two synthetic demo Contracts built from the kind demo.

## Considered Options

- **Config in the database, edited in the web console** (the IncidentFox model). It's friendlier, but it's a second source of truth with no review history.
- **One private repo per Contract.** It's stronger isolation, and a client could own its repo, but it's more to manage alone. A Contract can move to its own repo if a client asks for that.
