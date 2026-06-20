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

# copy built files from builder
COPY --from=builder /app/dist /usr/share/nginx/html