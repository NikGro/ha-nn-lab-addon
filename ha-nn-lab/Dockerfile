ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip
RUN pip3 install --no-cache-dir fastapi==0.115.0 uvicorn[standard]==0.30.6 requests==2.32.3

COPY rootfs /
RUN chmod +x /run.sh

CMD ["/run.sh"]
