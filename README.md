# VPN Telegram Bot

Telegram бот для продажи VPN через Telegram Stars.

## Установка на VPS (Ubuntu/Debian) — одна команда

```bash
git clone https://github.com/gdidhdydyhejdhd-art/vpn-bot.git && cd vpn-bot && chmod +x setup.sh && sudo ./setup.sh "BOT_TOKEN" "XUI_LOGIN" "XUI_PASSWORD"
```

## Управление

```bash
systemctl status vpn_bot    # статус
systemctl restart vpn_bot   # перезапуск
journalctl -u vpn_bot -f    # логи
systemctl stop vpn_bot      # остановить
```
