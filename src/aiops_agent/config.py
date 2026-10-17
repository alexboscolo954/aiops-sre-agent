"""Runtime settings, read from AIOPS_* environment variables (or a .env file)."""

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIOPS_", env_file=".env", extra="ignore")

    # LLM. Any init_chat_model string; set model_base_url for an
    # OpenAI-compatible gateway (LiteLLM, vLLM) and use "openai:<model>".
    model: str = "anthropic:claude-sonnet-5-5"
    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    model_headers: dict[str, str] = {}  # JSON, e.g. {"anthropic-workspace-id": "..."}
    max_model_calls: int = 30
    max_tool_calls: int = 25
    tool_output_limit: int = 8000  # max characters per tool result

    # Every Contract: one directory each (see contracts.py). Required for serve,
    # triage and mcp.
    contracts_dir: Path | None = None

    # Webhook server. Each Contract's Alertmanager has its own token (a hash in its
    # contract.yaml) and can only submit alerts; only the Operator's approver token
    # reads reports and approves actions.
    approver_token: SecretStr | None = None
    database_url: SecretStr | None = None  # Postgres; required for serve
    max_concurrent_triages: int = 3  # alert storms queue instead of fanning out
    decision_timeout_seconds: int = 1800  # proposed actions go stale after this
    slack_bot_token: SecretStr | None = None  # xoxb-...; channels are per Contract
    # Approve / reject buttons: Socket Mode with an app-level token (xapp-...,
    # connections:write). Only clicks from the Operator's Slack user id decide.
    slack_app_token: SecretStr | None = None
    slack_operator_id: str | None = None  # U...


# Settings that are gone: most moved into a Contract's contract.yaml (slice 0.3).
MOVED = {
    "AIOPS_IN_CLUSTER": "clusters[].in_cluster",
    "AIOPS_KUBECONFIG": "clusters[].kubeconfig_file",
    "AIOPS_KUBE_CONTEXT": "clusters[].context",
    "AIOPS_NAMESPACES": "clusters[].namespaces",
    "AIOPS_ENABLE_ACTIONS": "the kubernetes integration's enable_actions",
    "AIOPS_MAX_REPLICAS": "the kubernetes integration's max_replicas",
    "AIOPS_PROMETHEUS_URL": "the prometheus integration's url",
    "AIOPS_PROMETHEUS_TOKEN": "the prometheus integration's token_secret",
    "AIOPS_RUNBOOKS_DIR": "<contract>/runbooks and shared/runbooks",
    "AIOPS_WEBHOOK_TOKEN": "webhook_token_sha256 (aiops contracts new-token)",
    "AIOPS_SLACK_WEBHOOK_URL": "AIOPS_SLACK_BOT_TOKEN, plus each Contract's slack.operator_channel",
}


def refuse_moved(env_file: Path | None = Path(".env")) -> None:
    """Settings ignores unknown variables, so a deploy still setting these would
    lose them silently. Fail and say where each one went."""
    names = set(os.environ)
    if env_file and env_file.is_file():
        names |= set(dotenv_values(env_file))
    found = sorted(set(MOVED) & names)
    if found:
        where = "; ".join(f"{n} -> {MOVED[n]}" for n in found)
        raise RuntimeError(f"these settings are gone; set instead: {where}")
