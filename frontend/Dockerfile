# =========================
# 1. BUILD STAGE (Node)
# =========================
FROM node:20 AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# =========================
# 2. SERVE STAGE (nginx)
# =========================
FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# a self-signed certificate for the HTTPS listener (nginx.conf: WebXR needs a secure origin)
RUN apk add --no-cache openssl \
 && mkdir -p /etc/nginx/certs \
 && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=simsland" \
      -keyout /etc/nginx/certs/simsland.key -out /etc/nginx/certs/simsland.crt

# copy built files from builder
COPY --from=builder /app/dist /usr/share/nginx/html