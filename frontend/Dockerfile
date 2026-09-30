FROM node:24-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# proxy /api + /ws al backend + fallback SPA — sin esto el compose
# servía index.html donde el cliente esperaba JSON
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
