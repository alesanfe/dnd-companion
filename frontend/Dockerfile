# misma versión que CI (node 20) — divergir hace que el build de
# producción no reproduzca lo que CI valida
FROM node:20-alpine AS build
WORKDIR /app
# lockfile + npm ci: builds reproducibles — 'npm install' sin lock
# resolvía dependencias distintas a las del desarrollo
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# proxy /api + /ws al backend + fallback SPA — sin esto el compose
# servía index.html donde el cliente esperaba JSON
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
