#!/bin/sh
set -eu
case "${SIP_PASSWORD:?SIP_PASSWORD is required}" in
    *[!a-zA-Z0-9]*|'') echo 'SIP_PASSWORD must be alphanumeric.' >&2; exit 1 ;;
esac
[ "${#SIP_PASSWORD}" -ge 24 ] || { echo 'SIP_PASSWORD must have at least 24 characters.' >&2; exit 1; }
envsubst '${SIP_PASSWORD}' < /opt/config.json.template > /usr/share/nginx/html/config.json
