# syntax=docker/dockerfile:1
#
# Build context is the REPO ROOT (see docker-compose.yml's
# `build: {context: ., dockerfile: nginx/Dockerfile}`), not this directory —
# needed so this stage can reach widget/ to build it.

FROM node:20-slim AS widget-build
WORKDIR /widget
COPY widget/package.json widget/package-lock.json ./
RUN npm ci
COPY widget/. .
RUN npm run build

FROM nginx:alpine
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=widget-build /widget/dist/widget.js /usr/share/nginx/widget/widget.js
