# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable
WORKDIR /app

FROM base AS dependencies
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM dependencies AS build
COPY tsconfig.json drizzle.config.ts ./
COPY src ./src
COPY agent ./agent
COPY scripts ./scripts
RUN pnpm build

FROM base AS runtime
ENV NODE_ENV=production
ENV PORT=3000
WORKDIR /app

COPY --from=dependencies /app/node_modules ./node_modules
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY tsconfig.json drizzle.config.ts ./
COPY src ./src
COPY agent ./agent
COPY scripts ./scripts
COPY drizzle ./drizzle
COPY --from=build /app/.output ./.output
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 3000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["node", "node_modules/eve/bin/eve.js", "start", "--host", "0.0.0.0"]
