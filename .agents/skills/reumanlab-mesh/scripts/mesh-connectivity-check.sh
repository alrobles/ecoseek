#!/bin/bash
# Full mesh connectivity check — pings every node from every other node
# Usage: bash mesh-connectivity-check.sh
# Run from any reumanlab node with tailscale and SSH access

NODES=(
  "reumanlab:100.100.245.62:reumanlab"
  "reumanlab-alpha:100.123.27.68:reumanlab"
  "reumanlab-beta:100.115.246.9:reumanlab"
  "reumanlab-gamma:100.105.254.1:a474r867"
  "reumanlab-terminal:100.106.100.62:alrobles"
)

echo "============================================================================"
echo "              Tailscale Mesh Connectivity Check"
echo "============================================================================"
echo ""

# First: local tailscale status
echo "--- Tailscale Status ---"
tailscale status 2>/dev/null | grep -E "reumanlab|iphone"
echo ""

# Ping all from local
LOCAL_HOST=$(hostname -s)
echo "--- Ping from $LOCAL_HOST ---"
for entry in "${NODES[@]}"; do
  IFS=':' read -r name ip user <<< "$entry"
  if [ "$name" = "$LOCAL_HOST" ]; then
    echo "  $name ($ip): SELF"
    continue
  fi
  if ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then
    rtt=$(ping -c 1 -W 2 "$ip" 2>/dev/null | tail -1 | awk -F'/' '{print $5}')
    echo "  $name ($ip): OK ${rtt}ms"
  else
    echo "  $name ($ip): FALLO"
  fi
done
echo ""

# Cross-node: SSH into each node and ping all others
for src_entry in "${NODES[@]}"; do
  IFS=':' read -r src_name src_ip src_user <<< "$src_entry"
  if [ "$src_name" = "$LOCAL_HOST" ]; then
    continue  # skip self, already done
  fi
  
  echo "--- Ping from $src_name (via SSH) ---"
  SSH_CMD="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 ${src_user}@${src_ip}"
  
  for dst_entry in "${NODES[@]}"; do
    IFS=':' read -r dst_name dst_ip dst_user <<< "$dst_entry"
    if [ "$dst_name" = "$src_name" ]; then
      echo "  $dst_name ($dst_ip): SELF"
      continue
    fi
    
    result=$($SSH_CMD "ping -c 1 -W 2 $dst_ip 2>/dev/null | tail -1 | awk -F'/' '{print \\\$5}'" 2>/dev/null)
    if [ -n "$result" ]; then
      echo "  $dst_name ($dst_ip): OK ${result}ms"
    else
      echo "  $dst_name ($dst_ip): FALLO"
    fi
  done
  echo ""
done

echo "============================================================================"
echo "Connection types (from local):"
tailscale status | awk 'NR>1 && /reumanlab/ {printf "  %-22s %-16s %s\n", $2, $1, $6}'
echo "============================================================================"
