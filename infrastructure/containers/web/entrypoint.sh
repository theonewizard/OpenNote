#!/bin/sh
# opennote-web entrypoint. Writes /tmp/nginx-runtime.conf, which nginx.conf includes in its
# server block, then execs its arguments, the image's CMD (nginx), as PID 1 (so nginx
# receives SIGQUIT directly).
#   resolver: every nameserver in /etc/resolv.conf, the container's own DNS on Docker,
#     Podman and Kubernetes alike; 127.0.0.11 (Docker's) if the file names none.
#   $api: http://$OPENNOTE_API_UPSTREAM, host[:port], default api:8000 when unset (an empty
#     value is refused). nginx's resolver ignores the resolv.conf search list, so Kubernetes
#     needs a fully qualified name.
set -eu

upstream=${OPENNOTE_API_UPSTREAM-api:8000}
refuse() {
  echo "opennote-web cannot start: OPENNOTE_API_UPSTREAM must be host[:port]" >&2
  exit 1
}
# Host: letters, digits, dots, hyphens; port: 1-65535. Nothing else reaches nginx's config.
host=${upstream%%:*}
port=${upstream#"$host"}
case $host in '' | *[!A-Za-z0-9.-]*) refuse ;; esac
if [ -n "$port" ]; then
  port=${port#:}
  case $port in '' | *[!0-9]* | ??????*) refuse ;; esac
  if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then refuse; fi
fi

servers=
while read -r key address _ || [ -n "$key" ]; do
  [ "$key" = nameserver ] || continue
  case $address in '' | *[!0-9A-Fa-f.:]*) continue ;; *:*) address="[$address]" ;; esac
  servers="$servers $address"
done </etc/resolv.conf
if [ -z "$servers" ]; then
  echo "opennote-web: no nameserver in /etc/resolv.conf, using 127.0.0.11" >&2
  servers=" 127.0.0.11"
fi

printf "resolver%s valid=30s ipv6=off;\nset \$api http://%s;\n" "$servers" "$upstream" \
  >/tmp/nginx-runtime.conf
exec "$@"
