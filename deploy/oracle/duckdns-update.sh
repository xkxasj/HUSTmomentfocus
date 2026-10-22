#!/usr/bin/env bash
# 把 DuckDNS 子域名指向本机当前公网 IP。
#
# 配置（二选一）：
#   1. /etc/mouke/duckdns.env 里写 DUCKDNS_DOMAIN / DUCKDNS_TOKEN；
#   2. 调用时通过环境变量传入。
#
# 用法：
#   sudo bash deploy/oracle/duckdns-update.sh          # 用出口 IP
#   sudo bash deploy/oracle/duckdns-update.sh 1.2.3.4  # 指定 IP
set -euo pipefail

CONF="${DUCKDNS_CONF:-/etc/mouke/duckdns.env}"
if [[ -f "$CONF" ]]; then
  # shellcheck disable=SC1090
  source "$CONF"
fi

: "${DUCKDNS_DOMAIN:?请在 $CONF 里设置 DUCKDNS_DOMAIN}"
: "${DUCKDNS_TOKEN:?请在 $CONF 里设置 DUCKDNS_TOKEN}"

IP="${1:-}"
QUERY="domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}"
if [[ -n "$IP" ]]; then
  QUERY="${QUERY}&ip=${IP}"
fi

RESPONSE="$(curl -fsS --max-time 15 "https://www.duckdns.org/update?${QUERY}")"
if [[ "$RESPONSE" != "OK" ]]; then
  echo "DuckDNS 更新失败：${RESPONSE}" >&2
  exit 1
fi

if [[ -n "$IP" ]]; then
  echo "DuckDNS ${DUCKDNS_DOMAIN}.duckdns.org -> ${IP}"
else
  echo "DuckDNS ${DUCKDNS_DOMAIN}.duckdns.org -> 当前出口 IP"
fi
