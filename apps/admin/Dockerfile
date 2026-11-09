# Build context is the repo root so npm workspaces resolve.
FROM node:20-alpine AS base
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1

FROM base AS deps
COPY package.json package-lock.json* ./
COPY apps/kiosk/package.json ./apps/kiosk/
COPY apps/admin/package.json ./apps/admin/
RUN npm install

FROM deps AS dev
COPY apps/admin ./apps/admin
WORKDIR /repo/apps/admin
EXPOSE 3000
# Compose maps host ADMIN_PORT -> container 3000
CMD ["npx", "next", "dev", "-p", "3000"]

FROM deps AS builder
COPY apps/admin ./apps/admin
WORKDIR /repo/apps/admin
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
RUN addgroup -S nodejs && adduser -S nextjs -G nodejs
COPY --from=builder /repo/apps/admin/.next/standalone ./
COPY --from=builder /repo/apps/admin/.next/static ./apps/admin/.next/static
COPY --from=builder /repo/apps/admin/public ./apps/admin/public
USER nextjs
EXPOSE 3000
CMD ["node", "apps/admin/server.js"]
