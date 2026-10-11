FROM node:20-alpine AS base

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci
RUN npm install --no-save sharp

# Copy source and build
COPY . .
ENV NEXT_PUBLIC_API_URL=http://localhost:3000
ENV DOCKER_ENV=1
RUN npm run build

# Copy static files into standalone directory (required for standalone server to serve CSS/JS)
RUN cp -r .next/static .next/standalone/.next/static

# Expose the Next.js standalone server port
EXPOSE 3001

ENV PORT=3001
ENV HOSTNAME="0.0.0.0"
ENV NEXT_PUBLIC_API_URL=http://localhost:3000

CMD ["node", ".next/standalone/server.js"]
