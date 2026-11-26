# Оплата через DV-merchant на 5.144.179.170 — инструкция для агентов

Назначение: внедрение, тестирование и проверка оплат на сайтах через self-hosted dv-bundle.
Все команды выполняются на сервере `voiceagent@5.144.179.170` (SSH-ключ `~/.ssh/voice-agent-sandbox_ed25519`).
Копия этого файла на сервере: `/home/voiceagent/PAYMENTS_INTEGRATION.md`.

## 0. Quick start для агента (3 команды)

```bash
K=$(ssh -i ~/.ssh/voice-agent-sandbox_ed25519 voiceagent@5.144.179.170 \
  'sudo docker exec dv-postgres-database psql -U postgres -d dv_merchant -tAc "select key from store_api_keys where enabled limit 1"')
ssh -i ~/.ssh/voice-agent-sandbox_ed25519 voiceagent@5.144.179.170 \
  curl -s -H "X-Api-Key: $K" -H "Content-Type: application/json" \
  -d '{"amount":1,"currency_code":"USD","store_external_id":"test-1"}' \
  http://127.0.0.1:18081/api/v1/external/wallet
# → data.pay_url открывает форму оплаты (200), data.address[] — адреса валют
```

Проверка живости: `curl -s -o /dev/null -w '%{http_code}' https://openpay.click/pay/` → 200.
Форма подтверждения Store уже привязана к домену openpay.click (см. §5.1).

## 0.1. Онбординг нового сайта — самосервис, участие агента платежей НЕ нужно

Авторизация: IP + ключ. Store привязан к IP сайта (whitelist), env-файл с ключами читается
только с IP сайта, вызовы `/api/v1/external/wallet` — только с IP сайта.

**Путь A — у агента сайта есть SSH на payments-сервер** (заведение нового сайта):

```bash
ssh -i ~/.ssh/voice-agent-sandbox_ed25519 voiceagent@5.144.179.170 \
  'sudo /opt/dv-bundle/scripts/create-store.sh <name> <site_url> <webhook_url> <site_ip>'
# скрипт сам: Store, webhook, whitelist, ключи, nginx allow (env + external API), reload.
# Печатает env-блок; идемпотентен (повторный запуск не плодит ключи/Store).
```

**Путь B — у агента сайта SSH на payments нет** (обычный случай): env уже опубликован
для его IP, забрать со СВОЕГО сервера и записать в конфиг сайта:

```bash
# на сервере сайта:
curl -s https://openpay.click/onboard/<name>.env -o /etc/<site>/dv.env   # 403 с чужого IP
chmod 600 /etc/<site>/dv.env
```

Затем на сервере сайта — smoke (должен быть 200; с чужих IP external API отдаёт 403):

```bash
source /etc/<site>/dv.env
curl -s -H "X-Api-Key: $DV_API_KEY" -H "Content-Type: application/json" \
  -d '{"amount":0.10,"currency_code":"USD","store_external_id":"<name>-smoke-1"}' \
  "$DV_MERCHANT_API/wallet" | tee /tmp/dv-smoke.json
# ожидание: {"code":200,...,"data":{"pay_url":"https://openpay.click/pay/wallet/..."}}
curl -s -o /dev/null -w '%{http_code}\n' "$(python3 -c "import json;print(json.load(open('/tmp/dv-smoke.json'))['data']['pay_url'])")"  # → 200
```

Если у сайта ещё нет Store — попросить любого агента с доступом к payments-серверу
выполнить Путь A (это единственное действие "со стороны"; дальше сайт самодостаточен).

## 0.2. API самообслуживания и песочница (без SSH и без реальных денег)

База: `https://openpay.click/api/v1/onboard/…`. Доступ **только с IP, привязанного к Store**
(с другого IP → 403); секреты в ответах API не возвращаются — ключи забираются по IP из
`/onboard/<name>.env` (см. §0.1).

| Метод | Endpoint | Что делает |
|---|---|---|
| GET | `/health` | `{"ok":true}` — API живой |
| POST | `/store` | `{"name","site_url","webhook_url","ip"}` → создать Store + webhook + whitelist + ключи и nginx-доступ; ответ — `store_id` и `delivery_url` |
| GET | `/store/<name>` | состояние Store: hooks/IP, есть ли ключи (без самих ключей) |
| POST | `/sandbox/payment` | `{"name","order_id","amount"}` → создать тестовый wallet, вернуть `pay_url`; **деньги не списываются**, счёт не оплачивается |
| POST | `/sandbox/webhook` | `{"name","order_id","amount"}` → подписать HMAC-SHA256 webhook ключом Store (канонический compact-JSON, заголовок `X-Signature`) и доставить на webhook сайта; ответ — HTTP-статус сайта |

Полный цикл агента сайта (с его сервера, его IP):

```bash
# 1. ключи (если ещё нет): curl -s https://openpay.click/onboard/<name>.env -o /etc/<site>/dv.env && chmod 600 /etc/<site>/dv.env
# 2. состояние Store (секретов нет):
curl -s https://openpay.click/api/v1/onboard/store/<name>
# 3. песочница: тестовый счёт → pay_url (оплаты НЕТ):
curl -s -X POST https://openpay.click/api/v1/onboard/sandbox/payment \
  -H 'Content-Type: application/json' -d '{"name":"<name>","order_id":"smoke-1","amount":0.10}'
# 4. песочница: подписанный webhook → проверка той же подписи и обработчика сайта:
curl -s -X POST https://openpay.click/api/v1/onboard/sandbox/webhook \
  -H 'Content-Type: application/json' -d '{"name":"<name>","order_id":"smoke-1","amount":0.10}'
# ожидание: {"ok":true,"webhook_status":200,"response":"OK","order_id":"sandbox-smoke-1"}
# 5. только после 200 — реальный чекаут сайта и живая оплата (§7)
```

`order_id` в песочнице получает префикс `sandbox-` — такие заказы никогда не должны
попадать в продакшен-БД как оплаченные; проверяй, что сайт их фильтрует (или чистит).

Сервис: `/opt/dv-bundle/scripts/onboard_api.py`, systemd `dv-onboard-api` (127.0.0.1:18082),
логи: `sudo journalctl -u dv-onboard-api -n 50`. Изменения конфигурации — в репозитории
`github.com/martinroot/openpay`.

## 0.3. Логирование обращений и статусов (ops-лог)

Админка: `https://openpay.click/ops/` — таблица проектов, статусов платежей и лог событий
(чекауты, песочница, webhook'и, ошибки), фильтры по проекту/статусу. Доступ по basic auth
( creds выдаются отдельно, в публичную инструкцию не включаются ).

Агент сайта может писать события сам со своего IP (без basic auth):

```bash
curl -s -X POST https://openpay.click/ops/log/events -H 'Content-Type: application/json' \
  -d '{"project":"<name>","kind":"checkout","order_id":"<id>","status":"pending","amount":0.10,"pay_url":"..."}'
# → {"ok":true,"event_id":N}; с чужого IP → 403
```

Статусы: `pending`, `paid`, `sandbox`, `error`, `info`. Пиши события checkout → webhook → paid,
чтобы статус заказа был виден в одном месте и привязан к проекту.

## 1. Стек (факт, проверено)

| Компонент | Контейнер | Порт | Назначение |
|---|---|---|---|
| dv-merchant | `dv-merchant` | 127.0.0.1:18081 | API, админка, платёжная форма |
| dv-processing | `dv-processing` | 127.0.0.1:9000 (gRPC) | кошельки/балансы |
| Postgres 16 | `dv-postgres-database` | 127.0.0.1:5432 | БД |
| Redis 7 | `dv-redis-database` | 127.0.0.1:16379 | кэш |

- Compose: `/opt/dv-bundle/docker-compose.yml` (network_mode: host, всё на localhost).
- Пароли/учётки: `/opt/dv-bundle/.env` (0600), конфиг `/root/dv-merchant-config.yaml`.
- Документация API: https://docs.dv.net (клиенты: PHP `dv-net/php-client`, Python `dv-net-client`, JS `@dv-net/js-client`).

## 2. Маршруты dv-merchant (важно для nginx)

| Маршрут | Доступ | Публиковать наружу? |
|---|---|---|
| `/pay/` | платёжная форма (JS frontend) | да |
| `/api/v1/public/` | методы платёжной формы | да |
| `/api/v1/external/` | интеграция магазина (создание инвойсов) | НЕТ (localhost/VPN) |
| `/api/v1/dv-admin/` | API админки | НЕТ |
| `/dv-admin/` | веб-админка | НЕТ |

Пример nginx (на хосте сайта):
```nginx
location /pay/ { proxy_pass http://127.0.0.1:18081; }
location /api/v1/public/ { proxy_pass http://127.0.0.1:18081; }
```
Локальный тест без nginx: `ssh -L 18081:127.0.0.1:18081 voiceagent@5.144.179.170` → `http://127.0.0.1:18081/dv-admin/`.

## 3. Доступы агентов

SSH: `ssh -i ~/.ssh/voice-agent-sandbox_ed25519 voiceagent@5.144.179.170`
Системные вызовы на сервере — через `sudo` (approvals уже сохранены).

```bash
# статус стека
sudo docker ps --format '{{.Names}}\t{{.Status}}' | grep dv-
# health merchant (с саммари-сервера)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18081/   # 302 → https://dv.net/ = жив
# логи
sudo docker logs dv-merchant --tail 50
sudo docker logs dv-processing --tail 50
# БД merchant
sudo /opt/dv-bundle/scripts/psql.sh
```

## 4. Креды магазина (создать один раз в /dv-admin)

1. Store: название, внешний ID, URL сайта, success_url / return_url / fail_url, webhook URL (`https://<сайт>/api/dv_webhook.php`).
2. Включить валюты/методы оплаты.
3. Раздел API Keys: выпустить `API_KEY` (сервер) и `CLIENT_KEY` (secret для проверки подписи вебхуков).
4. Положить ключи в env сайта (не в git): например `/var/www/<site>/config.php` или `.env` сайта.

## 5. Создание счёта с сайта (депозит-кошелёк)

Проверено на живом стеке: метод интеграции — `POST /api/v1/external/wallet`.
Ассинхронных "invoice" в dv-merchant этой сборки НЕТ; вернее — API возвращает
платёжную форму с адресами по всем валютам.

```bash
# smoke-тест (с сервера):
K=$(sudo cat /tmp/dvkey.txt)   # или ключ из store_api_keys
curl -s -H "X-Api-Key: $K" -H "Content-Type: application/json" \
  -d '{"amount":1,"currency_code":"USD","store_external_id":"<id заказа>"}' \
  http://127.0.0.1:18081/api/v1/external/wallet
```
Ответ: `data.pay_url` (редиректить клиента) + `data.address[]` (по одному адресу
на каждую валюту: BTC, ETH, TRX, USDT-ETH/TRON/BSC/Polygon/Arbitrum, DOGE, LTC, BCH…),
`data.id` — wallet_id, связывать `store_external_id ↔ wallet_id` в БД сайта.

Сумма и store_external_id — только из бэкенда. Никогда не собирать из параметров запроса.

## 5.1 Store openpay.click — уже настроено (2026-11-12)

- Store `First Store` (bd8d9f4c-…-99184d2f58ee): site=`https://openpay.click`,
  return_url=`https://openpay.click/`, success_url=`https://openpay.click/?paid=1`,
  public_payment_form_enabled=true, 22 валюты включены.
- Платёжная форма живая: `https://openpay.click/pay/…` отвечает 200 через nginx.
- Админка: `https://openpay.click/dv-admin/` (register-роут закрыт basic-auth через nginx).
- ⚠ Webhook НЕ настроен (store_webhooks пуст) — добавить, когда известен сайт-приёмник.

## 6. Вебхук (подтверждение оплаты)

`api/dv_webhook.php`:
```php
$raw = file_get_contents('php://input');
$ok = (new \DvNet\PhpClient\Utils\MerchantUtilsManager())->checkSign(
    $_SERVER['HTTP_X_SIGNATURE'] ?? '', $DV_CLIENT_KEY, json_decode($raw, true));
if (!$ok) { http_response_code(403); exit; }
// map_webhook → типы: PaymentReceived (оплата подтверждена),
// Unconfirmed..., Withdrawal...
// идемпотентно по invoice_id: повторный вебхук не дублирует 'оплачен'
http_response_code(200); echo 'OK';
```

## 7. Чек-лист тестирования (агент обязан прогнать)

- [ ] `docker ps` — dv-merchant/dv-processing Up, health 302/200.
- [ ] API-ключ валиден: создание тест-инвойса на 1.00 USD вернуло `invoice_id` + `payment_url`.
- [ ] `payment_url` открывается, форма `/pay/` рисуется.
- [ ] После оплаты вебхук пришёл, подпись прошла, заказ = `paid` (проверить в БД сайта).
- [ ] Повторная доставка вебхука НЕ создаёт дубль платежа.
- [ ] Фейк-POST без подписи → 403, статус не меняется.
- [ ] Наружу торчат только `/pay/` и `/api/v1/public/` (curl с внешнего хоста на `/dv-admin/` и `/api/v1/external/` → deny/404).
- [ ] В логах dv-merchant нет ERROR по инвойсу.

## 8. Типовые аварии

| Симптом | Проверить |
|---|---|
| Инвойс создаётся, форма не платит | кошельки/валюты включены в Store, dv-processing жив |
| Вебхук не приходит | webhook URL в Store доступен извне, TLS валиден |
| 401 при createInvoice | API_KEY истёк/не тот Store |
| Ложные оплаты | подпись проверяется? CLIENT_KEY тот? |
| Форма оплаты пустая / "ошибка", нет списка кошельков | `curl -s 'https://openpay.click/api/v1/public/wallet/<id>?locale=en' \| python3 -c "import json,sys;d=json.load(sys.stdin)['data'];print(len(d['addresses']),len(d['rates']))"` → должно быть >0; если `0 0` — в Store нет валют (`store_currencies`) или `walletprepare` упал на DAI (нет курса в binance). Лечение: `sudo /opt/dv-bundle/scripts/create-store.sh <name> <site> <webhook> <ip>` (копирует 18 валют без DAI) — для уже созданного кошелька адреса подтянутся автоматически |

## 9. Правила

- Не публиковать `/api/v1/external`, `/api/v1/dv-admin`, gRPC 9000 наружу.
- Секреты — только в env/файлы с 0600 на сервере; в чат/логи — маскировать.
- Правки `docker-compose.yml`/`.env` → после них `cd /opt/dv-bundle && sudo docker compose up -d`.
