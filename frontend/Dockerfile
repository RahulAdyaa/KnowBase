# Build stage
FROM node:24-slim AS build
WORKDIR /srv/web
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY . .
RUN npm run build

# Serve stage: tiny static server. In production put a CDN / nginx in front.
FROM node:24-slim AS serve
WORKDIR /srv/web
RUN npm install -g serve@14
COPY --from=build /srv/web/dist ./dist
EXPOSE 3000
CMD ["serve", "-s", "dist", "-l", "3000"]
