# Caddy plus the four module dashboards as static files (docker-compose.prod.yml).
# Build context: ./deploy (nothing is copied from it); each dashboard's source comes in
# as an additional context. Every dashboard gets its own host and calls its agent
# through /api on that host, which Caddy forwards to the agent (deploy/remote_setup.sh
# writes the routes). The relative /api base keeps the images independent of the IP.

# syntax=docker/dockerfile:1
FROM node:22-slim AS softpower
WORKDIR /app
COPY --from=softpower_src package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY --from=softpower_src index.html vite.config.js ./
COPY --from=softpower_src src ./src
COPY --from=softpower_src public ./public
RUN --mount=type=cache,target=/root/.npm VITE_API_BASE_URL=/api npm run build

FROM node:22-slim AS policystance
WORKDIR /app
COPY --from=policystance_src package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
# The module's .env files are left out on purpose: VITE_API_BASE is injected below.
COPY --from=policystance_src index.html vite.config.js postcss.config.js tailwind.config.js ./
COPY --from=policystance_src src ./src
# src/api.js reads VITE_API_BASE, src/api/client.js reads VITE_API_BASE_URL.
RUN --mount=type=cache,target=/root/.npm VITE_API_BASE=/api VITE_API_BASE_URL=/api NODE_OPTIONS=--max-old-space-size=3072 npm run build

FROM node:22-slim AS events
WORKDIR /app
COPY --from=events_src package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY --from=events_src index.html vite.config.js ./
COPY --from=events_src src ./src
COPY --from=events_src public ./public
RUN --mount=type=cache,target=/root/.npm VITE_API_URL=/api npm run build

FROM caddy:2
COPY --from=softpower /app/dist /srv/softpower
COPY --from=policystance /app/dist /srv/policystance
COPY --from=events /app/dist /srv/events
# Trade's dashboard is one static page; ?api=<origin> points it at its agent.
COPY --from=trade_src index.html /srv/trade/index.html
