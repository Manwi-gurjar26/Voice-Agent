# syntax=docker/dockerfile:1

FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# NEXT_PUBLIC_* values are inlined into the client bundle at BUILD time, not
# read at container startup — a runtime environment variable on the
# `dashboard` service in docker-compose.yml would have no effect. This must
# be a browser-reachable URL (e.g. through nginx), never a Docker-internal
# service name like http://backend:8000 — the browser, not this container,
# is what actually calls it.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build

# --- Runtime stage: only the standalone output, no node_modules/toolchain ---
FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
