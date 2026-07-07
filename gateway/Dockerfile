# Stage 1: build the TypeScript sources to dist/.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# Stage 2: slim production image with only runtime dependencies.
FROM node:20-alpine AS production
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist
RUN mkdir -p /app/audit && chown -R node:node /app/audit
USER node
EXPOSE 8080
CMD ["node", "dist/app.js"]
