# Dashboard image: build the Vite bundle, serve it with nginx.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# API base can be overridden at build time; defaults to the published api port.
ARG VITE_API_BASE=http://localhost:8000/api/v1
ARG VITE_WS_BASE=ws://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_WS_BASE=$VITE_WS_BASE
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# SPA fallback so client-side routing works.
RUN printf 'server {\n  listen 80;\n  location / {\n    root /usr/share/nginx/html;\n    try_files $uri $uri/ /index.html;\n  }\n}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
