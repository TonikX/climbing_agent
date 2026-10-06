ARG OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:2026.9.4

FROM node:24-bookworm-slim AS plugin-builder
WORKDIR /plugin
COPY package.json package-lock.json tsconfig.json openclaw.plugin.json ./
COPY src ./src
COPY skills ./skills
COPY deploy/openclaw/cloudru-deepseek.json ./deploy/openclaw/cloudru-deepseek.json
COPY deploy/openclaw/multiuser-pilot.json ./deploy/openclaw/multiuser-pilot.json
COPY deploy/openclaw/pilot-workspace ./deploy/openclaw/pilot-workspace
RUN npm ci --no-audit --no-fund && npm run plugin:build && npm run plugin:validate

FROM ${OPENCLAW_IMAGE}
USER root
COPY --from=plugin-builder --chown=node:node /plugin /opt/climbing-journal
USER node
