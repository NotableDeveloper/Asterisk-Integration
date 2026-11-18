FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod +x /usr/sbin/policy-rc.d \
    && apt-get update \
    && apt-get install -y --no-install-recommends asterisk gettext-base ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY config/ /etc/asterisk/
COPY sounds/*.wav /usr/share/asterisk/sounds/fcr/
COPY templates/ /opt/asterisk-templates/
COPY entrypoint.sh /usr/local/bin/asterisk-entrypoint
RUN chmod +x /usr/local/bin/asterisk-entrypoint

EXPOSE 5060/udp 8088/tcp 10000-10019/udp
ENTRYPOINT ["/usr/local/bin/asterisk-entrypoint"]
