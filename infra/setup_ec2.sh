#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# EC2 bootstrap for Crypto Swing Trader
# Run once on a fresh Ubuntu 24.04 instance.
# Usage: sudo bash setup_ec2.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e
REPO="https://github.com/YOUR_GITHUB_USER/crypto-swing-trader.git"
APP_DIR="/home/ubuntu/crypto-swing-trader"
USER="ubuntu"

echo "=== System update ==="
apt-get update -y && apt-get upgrade -y
apt-get install -y git curl wget build-essential nginx python3.12 python3.12-venv python3-pip

echo "=== PostgreSQL check ==="
if ! command -v psql &>/dev/null; then
  apt-get install -y postgresql postgresql-contrib
  systemctl enable postgresql && systemctl start postgresql
fi

# Create DB user and database (reuse copilot_db from AI Data Copilot)
sudo -u postgres psql -c "CREATE USER copilot WITH PASSWORD 'copilot';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE copilot_db OWNER copilot;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE copilot_db TO copilot;" 2>/dev/null || true

echo "=== Clone repository ==="
if [ -d "$APP_DIR" ]; then
  cd "$APP_DIR" && git pull
else
  git clone "$REPO" "$APP_DIR"
fi
chown -R "$USER:$USER" "$APP_DIR"

echo "=== Python virtual environment ==="
cd "$APP_DIR"
sudo -u "$USER" python3.12 -m venv .venv
sudo -u "$USER" .venv/bin/pip install --upgrade pip
sudo -u "$USER" .venv/bin/pip install -r requirements.txt

echo "=== Create .env ==="
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.production" "$APP_DIR/.env"
  echo "GROQ_API_KEY=${GROQ_API_KEY:-}" >> "$APP_DIR/.env"
fi
chown "$USER:$USER" "$APP_DIR/.env"

echo "=== Systemd service ==="
sed "s/__USER__/$USER/g" "$APP_DIR/infra/trader.service" > /etc/systemd/system/crypto-trader.service
systemctl daemon-reload
systemctl enable crypto-trader
systemctl restart crypto-trader

echo "=== Nginx ==="
cp "$APP_DIR/infra/nginx.conf" /etc/nginx/sites-available/default
nginx -t && systemctl reload nginx

echo "=== Done! ==="
echo "Trader UI: http://$(curl -s ifconfig.me)/trader/"
