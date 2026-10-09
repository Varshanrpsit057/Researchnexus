# ResearchNexus frontend: the Next.js production server (standalone output).
#
#   docker build -t researchnexus-frontend ./frontend
#   docker build --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 ...   (API on another address)
#
# NEXT_PUBLIC_API_BASE_URL is compiled into the browser bundle, so it is a
# build argument -- and it is never a secret. Left empty (the default here),
# the browser calls the API on the app's own address under /api, which is
# how the AWS deployment routes it (AWS_ARCHITECTURE.md): one image then
# serves any environment.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"
# node is PID 1 and handles SIGTERM itself
CMD ["node", "server.js"]
