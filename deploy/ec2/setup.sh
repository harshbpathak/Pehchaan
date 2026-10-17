#!/usr/bin/env bash
# One-time setup of Pehchan on a fresh Ubuntu 24.04 EC2 instance.
#
#   bash setup.sh <public-hostname> <openrouter-api-key>
#
# Installs Docker, Caddy (automatic HTTPS), Python and the app; restores the graph from
# ~/falkordb-data.tgz if present; writes /etc/pehchan.env with fresh tokens; runs Pehchan
# as a systemd service behind Caddy. Safe to rerun: existing tokens and data are kept.
set -euo pipefail

HOST="${1:?usage: bash setup.sh <public-hostname> <openrouter-api-key>}"
OPENROUTER_KEY="${2:?usage: bash setup.sh <public-hostname> <openrouter-api-key>}"
REPO="https://github.com/harshbpathak/Pehchaan.git"
APP="$HOME/Pehchaan"

echo "==> System packages"
sudo apt-get update -y
sudo apt-get install -y python3.12-venv git docker.io docker-compose-v2 curl \
  debian-keyring debian-archive-keyring apt-transport-https gnupg
sudo usermod -aG docker "$USER"

if [ "$(free -m | awk '/Mem:/ {print $2}')" -lt 7000 ] && [ ! -f /swapfile ]; then
  echo "==> Adding 4 GB swap (instance has under 7 GB RAM)"
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "==> Application"
[ -d "$APP/.git" ] || git clone "$REPO" "$APP"
cd "$APP"
[ -d .venv ] || python3.12 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install --quiet -c requirements.lock -e ".[semantic,server]"
.venv/bin/python -m pehchan.cli download-models

echo "==> FalkorDB"
if ! sudo docker volume inspect pehchan_falkordb-data >/dev/null 2>&1 && [ -f "$HOME/falkordb-data.tgz" ]; then
  echo "    restoring graph from ~/falkordb-data.tgz"
  sudo docker volume create pehchan_falkordb-data >/dev/null
  sudo docker run --rm -v pehchan_falkordb-data:/data -v "$HOME":/backup alpine \
    tar xzf /backup/falkordb-data.tgz -C /data
fi
sudo docker compose up -d --wait
sudo docker update --restart unless-stopped "$(sudo docker compose ps -q falkordb)" >/dev/null

echo "==> Configuration (/etc/pehchan.env)"
if [ ! -f /etc/pehchan.env ]; then
  READ_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  WRITE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  sudo install -m 600 /dev/null /etc/pehchan.env
  sudo tee /etc/pehchan.env >/dev/null <<EOF
FALKORDB_HOST=127.0.0.1
FALKORDB_PORT=16379
FALKORDB_GRAPH=pehchan
PEHCHAN_MODEL_DIR=$APP/.models
PEHCHAN_PUBLIC_HOSTS=$HOST
PEHCHAN_PUBLIC_READ=1
PEHCHAN_PUBLIC_RATE_LIMIT=30
PEHCHAN_API_TOKEN=$READ_TOKEN
PEHCHAN_WRITE_TOKEN=$WRITE_TOKEN
OPENROUTER_API_KEY=$OPENROUTER_KEY
PEHCHAN_OPENROUTER_MODEL=openai/gpt-oss-120b
EOF
  echo "    write token (keep it private; needed to save cases): $WRITE_TOKEN"
else
  echo "    keeping existing /etc/pehchan.env"
fi

echo "==> Service"
sudo tee /etc/systemd/system/pehchan.service >/dev/null <<EOF
[Unit]
Description=Pehchan AI API, web app and MCP
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP
EnvironmentFile=/etc/pehchan.env
ExecStart=$APP/.venv/bin/uvicorn pehchan.api:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now pehchan
sudo systemctl restart pehchan

echo "==> HTTPS (Caddy)"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
fi
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$HOST {
    encode gzip
    reverse_proxy 127.0.0.1:8000 {
        transport http {
            read_timeout 180s
        }
    }
}
EOF
sudo systemctl reload caddy

echo "==> Waiting for Pehchan"
for _ in $(seq 1 60); do
  if curl -sf -H "Host: $HOST" http://127.0.0.1:8000/health >/dev/null; then break; fi
  sleep 3
done
curl -s -H "Host: $HOST" http://127.0.0.1:8000/health; echo
echo
echo "Done. Open https://$HOST/  (MCP: https://$HOST/public/mcp/)"
