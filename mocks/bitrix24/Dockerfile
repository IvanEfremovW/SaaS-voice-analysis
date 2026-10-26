FROM node:24-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY .env.defaults mock_config.json ./
COPY src ./src

CMD ["node", "--env-file=.env.defaults", "src/server.ts"]
