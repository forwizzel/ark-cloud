FROM node:22.23.2-alpine3.24

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci && sha256sum package-lock.json | cut -d " " -f 1 > node_modules/.ark-lock-hash

COPY . .
RUN chown -R node:node /app

USER node

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
