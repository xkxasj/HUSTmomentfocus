#!/usr/bin/env bash
# 放行 Oracle Ubuntu 实例的 80/443，并持久化 iptables 规则。
# 用法：sudo bash deploy/oracle/open-ports.sh
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请用 sudo 运行：sudo bash $0" >&2
  exit 1
fi

add_rule() {
  local proto="$1"
  local port="$2"
  if ! iptables -C INPUT -p "$proto" --dport "$port" -j ACCEPT 2>/dev/null; then
    iptables -I INPUT -p "$proto" --dport "$port" -j ACCEPT
    echo "已放行 ${proto}/${port}"
  else
    echo "${proto}/${port} 已存在，跳过"
  fi
}

add_rule tcp 80
add_rule tcp 443
add_rule udp 443

# Oracle 镜像通常不启用 ufw；如果启用了，也一并放行。
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow 443/udp
fi

if ! command -v netfilter-persistent >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
fi

netfilter-persistent save
echo
echo "iptables 规则已保存。"
echo "还必须在 OCI 控制台的 Security List 里放行 TCP 80/443，否则外网仍然打不开。"
