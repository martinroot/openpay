# OpenPay — self-hosted DV-merchant платежи

Репозиторий инфраструктуры и интеграций платежей: https://openpay.click/

## Состав

- `docs/PAYMENTS_INTEGRATION.md` — источник истины для агентов. Онбординг сайта под ключ,
  API `POST /api/v1/external/wallet`, webhook, чек-лист проверок, аварии.
  Живая копия: https://openpay.click/integration.md
- `scripts/create-store.sh` — самосервис-онбординг: Store + webhook + IP-whitelist + ключи,
  публикация env-файла `https://openpay.click/onboard/<name>.env` только для IP сайта,
  разрешение `POST /api/v1/external/wallet` только для IP сайта. Идемпотентен.
- `nginx/openpay.conf` — рабочая конфигурация nginx домена openpay.click (без секретов).

## Быстрый старт для нового сайта

У агента есть SSH на payments-сервер:

```bash
sudo /opt/dv-bundle/scripts/create-store.sh <name> <site_url> <webhook_url> <site_ip>
```

У агента НЕТ SSH (обычный случай) — забрать ключи со своего сервера:

```bash
curl -s https://openpay.click/onboard/<name>.env -o /etc/<site>/dv.env
chmod 600 /etc/<site>/dv.env
```

Дальше — по `docs/PAYMENTS_INTEGRATION.md` §0.1 (smoke-чекаут $0.10, проверка pay_url)
и §7 (полный чек-лист).

## API и песочница

`https://openpay.click/api/v1/onboard/` (доступ только с IP сайта): `POST /store`, `GET /store/<name>`, `POST /sandbox/payment`, `POST /sandbox/webhook` — подписанный тестовый webhook без реальных денег. Полный цикл — `docs/PAYMENTS_INTEGRATION.md` §0.2.

## Правила

- Ключи и секреты — только в env сайта (0600), не в git и не в чаты.
- Наружу публикуются только `/pay/`, `/api/v1/public/`, `/onboard/<name>.env` (по IP)
  и `/api/v1/external/wallet` (по IP). `/dv-admin/` и `/api/v1/dv-admin/` — только localhost/VPN.
- Live-инструкция и копии (`/home/voiceagent/`, `/var/www/openpay.click/integration.md`)
  синхронизируются при каждом изменении.
