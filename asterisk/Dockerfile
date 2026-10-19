FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends asterisk curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY config/ /etc/asterisk/
COPY entrypoint.sh /entrypoint.sh
RUN cp /etc/asterisk/rtp.conf /etc/asterisk/rtp.base.conf && chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
