FROM tailscale/tailscale:v1.102.5@sha256:c507f3a2a6ab1cabd8d809b98edeb41edbd5c3fb6ad9632ffd098b4c7d0b4065

RUN apk add --no-cache python3 nginx \
    && addgroup -g 10001 arkcontroller \
    && adduser -D -u 10001 -G arkcontroller arkcontroller
WORKDIR /app
COPY controller.py runtime.py healthcheck.py ./
COPY nginx.conf /etc/nginx/nginx.conf
USER 10001:10001
ENTRYPOINT ["python3", "/app/runtime.py"]
