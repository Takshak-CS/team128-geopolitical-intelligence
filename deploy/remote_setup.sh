#!/usr/bin/env bash
# Runs on the server; scripts/deploy.ps1 uploads it with the bundle and calls it.
#
#   bash ~/team128-upload/remote_setup.sh <site-address> [login|public]
#
# <site-address> is what Caddy serves: a domain or <ip>.sslip.io for automatic
# HTTPS, or http://<ip> for plain HTTP. "login" (the default) asks for the shared
# login in team128-upload/.auth; "public" serves the site to anyone.
set -euo pipefail
SITE="$1"
ACCESS="${2:-login}"
UP="$HOME/team128-upload"
APP="$HOME/team128"
COMPOSE=(sudo docker compose -f docker-compose.prod.yml)

echo "== 1/6 Docker"
if ! command -v docker >/dev/null 2>&1 || ! sudo docker compose version >/dev/null 2>&1 || ! sudo docker buildx version >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose-v2 docker-buildx
  sudo systemctl enable --now docker
fi
sudo docker compose version

echo "== 2/6 Memory"
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
echo "RAM: ${mem_mb} MB"
# Policy Stance peaks near 2 GB while building its cache; all five services need ~4 GB.
if [ "$mem_mb" -lt 7500 ] && [ -z "$(swapon --show --noheadings)" ]; then
  echo "Adding a 4 GB swap file"
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== 3/6 Code"
mkdir -p "$APP"
tar -xzf "$UP/code.tar.gz" -C "$APP"

echo "== 4/6 Data"
if [ -f "$UP/data.tar.gz" ]; then
  tar -xzf "$UP/data.tar.gz" -C "$APP"
  rm -f "$UP/data.tar.gz"
fi
missing=0
for need in services/trade_intelligence/cache/meta.json services/policy_stance/data services/event_summarization/data/dyad_geopolitical_scores.csv; do
  if [ ! -e "$APP/$need" ]; then echo "MISSING: $need (see docs/DATA.md)"; missing=1; fi
done
[ "$missing" -eq 0 ] && echo "data present"

echo "== 5/6 Access and HTTPS"
if [ "$ACCESS" = "public" ]; then
  AUTH_BLOCK=""
  echo "serving $SITE to anyone, no login"
else
  # Older .auth files have no trailing newline, so read returns 1 at end of file
  # even though it filled both variables; check the values instead of the status.
  read -r AUTH_USER AUTH_HASH < "$UP/.auth" || true
  if [ -z "${AUTH_USER:-}" ] || [ -z "${AUTH_HASH:-}" ]; then
    echo "deploy/.auth is empty or malformed; run scripts/set_password.ps1 again"; exit 1
  fi
  AUTH_BLOCK=$(printf '\tbasic_auth {\n\t\t%s %s\n\t}' "$AUTH_USER" "$AUTH_HASH")
  echo "serving $SITE for user $AUTH_USER"
fi

# Each module dashboard gets its own host under the site's: softpower.<site> and so
# on. sslip.io resolves those by itself; a custom domain needs DNS records for them,
# and a bare IP (plain-HTTP deploys) has no subdomains, so it gets no dashboards.
SCHEME="https://"; PREFIX=""; HOST="$SITE"
case "$SITE" in http://*) SCHEME="http://"; PREFIX="http://"; HOST="${SITE#http://}" ;; esac
if echo "$HOST" | grep -qE '^[0-9.]+$'; then DASHBOARDS=0; else DASHBOARDS=1; fi
{
  cat <<EOF
$SITE {
	encode gzip
$AUTH_BLOCK
	reverse_proxy orchestrator:8000
}
EOF
  if [ "$DASHBOARDS" -eq 1 ]; then
    # The React dashboards call their agent through /api on their own host.
    for pair in softpower:soft_power policystance:policy_stance events:event_summarization; do
      name="${pair%%:*}"; agent="${pair#*:}"
      cat <<EOF

${PREFIX}${name}.${HOST} {
	encode gzip
$AUTH_BLOCK
	header X-Frame-Options ""
	header Content-Security-Policy ""
	handle_path /api/* {
		reverse_proxy ${agent}:8000
	}
	handle {
		root * /srv/${name}
		try_files {path} /index.html
		file_server
	}
}
EOF
    done
    # Trade's page takes its agent's origin as ?api= and calls it at the root, so the
    # page and the agent share this host: the page at /, everything else to the agent.
    cat <<EOF

${PREFIX}trade.${HOST} {
	encode gzip
$AUTH_BLOCK
	@bare {
		path /
		not query api=*
	}
	redir @bare /?api=${SCHEME}trade.${HOST} 302
	@page path / /index.html
	handle @page {
		root * /srv/trade
		rewrite * /index.html
		file_server
	}
	handle {
		reverse_proxy trade_intelligence:8000
	}
}
EOF
  fi
} > "$APP/deploy/Caddyfile.new"

# The briefing UI links to each dashboard; compose reads these from .env. Other
# settings someone put in the server's .env (GEMINI_API_KEY) are kept.
touch "$APP/.env"
sed -i '/_DASHBOARD_URL=/d' "$APP/.env"
if [ "$DASHBOARDS" -eq 1 ]; then
  cat >> "$APP/.env" <<EOF
SOFT_POWER_DASHBOARD_URL=${SCHEME}softpower.${HOST}
POLICY_STANCE_DASHBOARD_URL=${SCHEME}policystance.${HOST}
EVENTS_DASHBOARD_URL=${SCHEME}events.${HOST}
TRADE_DASHBOARD_URL=${SCHEME}trade.${HOST}/?api=${SCHEME}trade.${HOST}
EOF
else
  echo "no module dashboards: $HOST is an IP address, which has no subdomains"
fi

echo "== 6/6 Build and start (the first build takes 10-20 minutes)"
cd "$APP"
DOCKER_BUILDKIT=1 "${COMPOSE[@]}" build
# Check the new Caddyfile before it replaces the current one, then copy it over in
# place: Caddy's container mounts that very file, so its inode must not change.
"${COMPOSE[@]}" run --rm --no-deps -T -v "$APP/deploy/Caddyfile.new:/tmp/Caddyfile.new:ro" caddy   caddy validate --config /tmp/Caddyfile.new --adapter caddyfile
cat "$APP/deploy/Caddyfile.new" > "$APP/deploy/Caddyfile"
rm -f "$APP/deploy/Caddyfile.new"
"${COMPOSE[@]}" up -d --remove-orphans
# Caddy reads its config only when it starts, and compose does not recreate it when
# just the mounted Caddyfile changed; restart it so a new login or access mode applies.
"${COMPOSE[@]}" restart caddy
"${COMPOSE[@]}" ps

echo "Waiting for the agents (Policy Stance builds its cache on first start, ~10 minutes)..."
for i in $(seq 1 120); do
  health=$("${COMPOSE[@]}" exec -T orchestrator python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5))['agents'])" 2>/dev/null || true)
  echo "  $health"
  if [ -n "$health" ] && ! echo "$health" | grep -q -E "unavailable|not_ready|error"; then
    echo "All four agents are up."
    break
  fi
  sleep 15
done
echo "DONE: ${SCHEME}${HOST}"
if [ "$DASHBOARDS" -eq 1 ]; then
  for name in softpower policystance events trade; do echo "  dashboard: ${SCHEME}${name}.${HOST}"; done
fi
