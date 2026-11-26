FROM node:24-alpine

WORKDIR /app

# The Prisma schema is needed by `npm ci`: its postinstall generates the Prisma client.
COPY package.json package-lock.json prisma.config.ts ./
COPY prisma ./prisma
RUN npm ci --omit=dev

COPY . .

CMD ["sh", "-c", "npx prisma migrate deploy && node app/server.ts"]
