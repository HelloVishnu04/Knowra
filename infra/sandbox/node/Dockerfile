FROM node:22-slim

RUN groupadd --gid 65532 sandbox \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin sandbox \
    && npm install --global typescript@5.9.3

WORKDIR /workspace
USER 65532:65532
