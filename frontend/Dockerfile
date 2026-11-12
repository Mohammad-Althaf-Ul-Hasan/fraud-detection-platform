# ---- Stage 1: build ----
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps first (leverages Docker layer cache)
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Build with configurable API base
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE

COPY . .
RUN npm run build

# ---- Stage 2: serve ----
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]