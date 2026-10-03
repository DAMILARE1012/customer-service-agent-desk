# syntax=docker/dockerfile:1
# Baton web (staff app, chat widget, demo store). Build from the project root:
#   docker build -f frontend/Dockerfile -t baton-web .
#
# Built once with no settings; the VITE_* variables are read when the container starts (see
# docker/40-baton-config.sh), and WIDGET_FRAME_ANCESTORS limits which sites may embed the chat widget.

FROM node:22-alpine AS build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM nginxinc/nginx-unprivileged:1.29-alpine
ENV WIDGET_FRAME_ANCESTORS="*"
COPY --chown=101:101 --from=build /app/frontend/dist /usr/share/nginx/html
COPY frontend/docker/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 frontend/docker/40-baton-config.sh /docker-entrypoint.d/40-baton-config.sh
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
