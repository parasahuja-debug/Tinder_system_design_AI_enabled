# Production image for the Angular frontend — two stages so the final image
# carries only static files + nginx, no Node toolchain or node_modules.
#
# Why not `ng serve` (how it runs in dev): that's a development server with
# live reload, not meant to serve real traffic. In the cluster the built app
# is plain static files, which any web server can serve.

# --- Stage 1: build -----------------------------------------------------------
FROM node:24-alpine AS build
WORKDIR /app
# Dependency manifests first, so the npm ci layer is cached until they change.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Production build -> dist/frontend/browser (Angular's application builder).
RUN npx ng build --configuration production

# --- Stage 2: serve -----------------------------------------------------------
FROM nginx:1.27-alpine
# SPA-aware config (see nginx.conf): unknown paths fall back to index.html so
# Angular's client-side routes survive a page refresh.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
EXPOSE 80
