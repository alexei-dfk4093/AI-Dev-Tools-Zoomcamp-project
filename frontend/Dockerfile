# EcoMind frontend: static build served by nginx with /api proxied to the
# backend service.
#
# Build (from the repository root):
#   docker build -f frontend/Dockerfile -t ecomind-frontend .

# --- 1. Build the production bundle -----------------------------------------
FROM node:26-alpine AS build

WORKDIR /app

# Install from the lockfile first so source changes do not re-resolve
# dependencies.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY frontend/ ./
RUN npm run build

# --- 2. Serve the bundle -----------------------------------------------------
FROM nginx:1.29-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
