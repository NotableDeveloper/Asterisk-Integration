#!/bin/sh
set -eu

# Restrict values inserted into Asterisk config files to a single safe token.
for credential in "${ARI_PASSWORD:?ARI_PASSWORD is required}" "${SIP_PASSWORD:?SIP_PASSWORD is required}"; do
    case "$credential" in
        *[!a-zA-Z0-9]*|'') echo 'Passwords must be alphanumeric.' >&2; exit 1 ;;
    esac
    [ "${#credential}" -ge 24 ] || { echo 'Passwords must have at least 24 characters.' >&2; exit 1; }
done

ASTERISK_CONTAINER_IP=$(hostname -i | awk '{print $1}')
export ASTERISK_CONTAINER_IP
for name in ari pjsip rtp; do
    envsubst '${ARI_PASSWORD} ${SIP_PASSWORD} ${ASTERISK_CONTAINER_IP}' < "/opt/asterisk-templates/$name.conf" > "/etc/asterisk/$name.conf"
    chown root:asterisk "/etc/asterisk/$name.conf"
    chmod 640 "/etc/asterisk/$name.conf"
done
# Setgid lets the Whisper service read completed recordings and dequeue them.
install -d -o asterisk -g 10001 -m 2770 /inquiries
find /inquiries -maxdepth 1 -type f -name 'open-*.wav' -delete
mkdir -p /var/run/asterisk
chown -R asterisk:asterisk /var/run/asterisk /var/log/asterisk /var/spool/asterisk /var/lib/asterisk
exec asterisk -f -U asterisk -G asterisk
