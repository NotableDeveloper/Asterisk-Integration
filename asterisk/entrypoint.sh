#!/bin/sh
set -eu
# Docker's container IP is not reachable by the host browser. Advertise the
# host-mapped RTP address in ICE; retain the same UDP port numbers.
cp /etc/asterisk/rtp.base.conf /etc/asterisk/rtp.conf
container_ip=$(hostname -I | awk '{print $1}')
printf '\n[ice_host_candidates]\n%s => %s\n' "$container_ip" "${WEBRTC_MEDIA_ADDRESS:-127.0.0.1}" >> /etc/asterisk/rtp.conf
exec asterisk -f -vvv
