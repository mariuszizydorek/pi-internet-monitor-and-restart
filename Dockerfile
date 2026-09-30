FROM node:latest AS web
RUN npm install -g corepack && corepack enable && corepack prepare pnpm@11.22.0 --activate
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/index.html web/rsbuild.config.ts web/tsconfig.json ./
COPY web/src ./src
RUN pnpm build

FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATUS_DIST=/app/web/dist \
    STATUS_PORT=16081

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg iproute2 iputils-ping iw libgpiod2 \
    && curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash \
    && apt-get update \
    && apt-get install -y --no-install-recommends speedtest \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=web /web/dist /app/web/dist
RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir gpiod

CMD ["netwatch-monitor"]
