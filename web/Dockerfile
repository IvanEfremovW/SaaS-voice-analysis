# Stage 1: build the frontend. Needs every package (React, Vite...), but none of them is in the final image.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: what runs: the backend, plus the built frontend (plain HTML, JS and CSS) it serves.
FROM node:24-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY backend ./backend
COPY --from=build /app/frontend/dist ./frontend/dist
CMD ["node", "backend/server.ts"]
