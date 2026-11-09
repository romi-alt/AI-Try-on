# Build context is the repo root so npm workspaces resolve.
FROM node:20-alpine AS base
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1

# --- dependencies -----------------------------------------------------------
FROM base AS deps
COPY package.json package-lock.json* ./
COPY apps/kiosk/package.json ./apps/kiosk/
COPY apps/admin/package.json ./apps/admin/
RUN npm install

# --- dev (hot reload; source is bind-mounted by compose) -------------------
FROM deps AS dev
COPY apps/kiosk ./apps/kiosk
WORKDIR /repo/apps/kiosk
EXPOSE 3000
CMD ["npm", "run", "dev"]

# --- production build --------------------------------------------------------
FROM deps AS builder
COPY apps/kiosk ./apps/kiosk
WORKDIR /repo/apps/kiosk
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
RUN addgroup -S nodejs && adduser -S nextjs -G nodejs
COPY --from=builder /repo/apps/kiosk/.next/standalone ./
COPY --from=builder /repo/apps/kiosk/.next/static ./apps/kiosk/.next/static
COPY --from=builder /repo/apps/kiosk/public ./apps/kiosk/public
USER nextjs
EXPOSE 3000
CMD ["node", "apps/kiosk/server.js"]
