#!/usr/bin/env bash
# Update a running EC2 deployment to an exact commit; run by CI/CD over SSH.
#   bash -s -- <commit-sha> < deploy/ec2/update.sh
set -euo pipefail
SHA="${1:?commit sha required}"
cd "$HOME/Pehchaan"
git fetch --quiet origin
git checkout --quiet --force "$SHA"
.venv/bin/pip install --quiet -c requirements.lock -e ".[semantic,server]"
sudo systemctl restart pehchan
HOST="$(sudo grep '^PEHCHAN_PUBLIC_HOSTS=' /etc/pehchan.env | cut -d= -f2)"
for _ in $(seq 1 60); do
  if curl -sf -H "Host: $HOST" http://127.0.0.1:8000/health >/dev/null; then
    echo "Pehchan is healthy at commit ${SHA:0:7}"
    exit 0
  fi
  sleep 3
done
echo "Pehchan did not become healthy; see: journalctl -u pehchan -n 100" >&2
exit 1
