#!/bin/bash
set -e
BOT_TOKEN="$1"
XUI_LOGIN="$2"
XUI_PASSWORD="$3"
if [ -z "$BOT_TOKEN" ] || [ -z "$XUI_LOGIN" ] || [ -z "$XUI_PASSWORD" ]; then
  echo "Usage: sudo ./setup.sh BOT_TOKEN XUI_LOGIN XUI_PASSWORD"
  exit 1
fi
echo "=== Installing dependencies ==="
apt-get update -qq && apt-get install -y -qq python3 python3-pip
pip3 install -q -r bot/requirements.txt
echo "=== Creating .env ==="
cat > .env << EOF
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
XUI_LOGIN=$XUI_LOGIN
XUI_PASSWORD=$XUI_PASSWORD
EOF
echo "=== Setting up systemd ==="
WORKDIR="$(pwd)"
cat > /etc/systemd/system/vpn_bot.service << EOF
[Unit]
Description=Telegram VPN Bot
After=network.target
[Service]
WorkingDirectory=$WORKDIR
EnvironmentFile=$WORKDIR/.env
ExecStart=/usr/bin/python3 bot/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable vpn_bot
systemctl start vpn_bot
echo ""
echo "=== Готово! Бот запущен ==="
echo "Статус:  systemctl status vpn_bot"
echo "Логи:    journalctl -u vpn_bot -f"
echo "Стоп:    systemctl stop vpn_bot"
