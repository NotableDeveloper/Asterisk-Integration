FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY src/ src/
RUN npm run build

FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
COPY config.json.template /opt/config.json.template
COPY entrypoint.sh /docker-entrypoint.d/40-webphone-config.sh
RUN chmod +x /docker-entrypoint.d/40-webphone-config.sh
EXPOSE 8080
