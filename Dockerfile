FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
# sops decrypts each Contract's secrets.sops.yaml. Pinned, and verified per
# architecture; fetched here so the runtime stage needs no download tool.
ARG TARGETARCH
ARG SOPS_VERSION=3.13.3
RUN python - <<'EOF'
import hashlib, os, urllib.request
arch, version = os.environ["TARGETARCH"], os.environ["SOPS_VERSION"]
sha256 = {
    "amd64": "e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b",
    "arm64": "53b0abacd38ef1b12a66d6c100956691b9cefce018d91f81e73ddf7438b94d77",
}[arch]
url = f"https://github.com/getsops/sops/releases/download/v{version}/sops-v{version}.linux.{arch}"
data = urllib.request.urlopen(url, timeout=60).read()
if hashlib.sha256(data).hexdigest() != sha256:
    raise SystemExit(f"sops {version} {arch}: checksum mismatch")
with open("/usr/local/bin/sops", "wb") as f:
    f.write(data)
os.chmod("/usr/local/bin/sops", 0o755)
EOF
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin aiops
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /usr/local/bin/sops /usr/local/bin/sops
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8080
ENTRYPOINT ["aiops"]
CMD ["serve"]
