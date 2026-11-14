FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==9.1.1 ruff==0.16.5 \
    && groupadd --gid 65532 sandbox \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin sandbox

WORKDIR /workspace
USER 65532:65532
