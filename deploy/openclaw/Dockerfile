ARG OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:2026.9.4

FROM node:24-bookworm-slim AS plugin-builder
WORKDIR /plugin
COPY package.json package-lock.json tsconfig.json openclaw.plugin.json ./
COPY src ./src
COPY skills ./skills
RUN npm ci --no-audit --no-fund && npm run build

FROM ${OPENCLAW_IMAGE}
USER root
COPY --from=plugin-builder --chown=node:node /plugin /opt/climbing-journal
USER node
