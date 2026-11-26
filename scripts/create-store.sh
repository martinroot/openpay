#!/usr/bin/env bash
# DV-merchant store onboarding (self-service):
#   sudo /opt/dv-bundle/scripts/create-store.sh <name> <site_url> <webhook_url> <allow_ip>
# Creates Store + webhook + IP whitelist + API/CLIENT keys, publishes the env file
# at https://openpay.click/onboard/<name>.env readable ONLY from <allow_ip>, and
# opens POST /api/v1/external/wallet for <allow_ip>. Idempotent.
set -euo pipefail
NAME=${1:?usage: create-store.sh <name> <site_url> <webhook_url> <allow_ip>}
SITE=${2:?site_url required}; HOOK=${3:?webhook_url required}; ALLOW_IP=${4:?allow_ip required}

PSQL="docker exec dv-postgres-database psql -U postgres -d dv_merchant -qAtc"
USER_ID=$($PSQL "select user_id from stores limit 1")
STORE=$($PSQL "select id from stores where name='$NAME' limit 1")
if [ -z "$STORE" ]; then
  STORE=$($PSQL "insert into stores (id,user_id,name,site,currency_id,rate_source,return_url,success_url,status,minimal_payment,public_payment_form_enabled) values (gen_random_uuid(),'$USER_ID','$NAME','$SITE','USD','binance','$SITE/','$SITE/?paid=1',true,0.10,true) returning id")
fi
$PSQL "insert into store_webhooks (store_id,url,enabled,events) select '$STORE','$HOOK',true,'[\"PaymentReceived\"]'::json where not exists (select 1 from store_webhooks where store_id='$STORE' and url='$HOOK')" >/dev/null
$PSQL "insert into store_whitelist (ip,store_id) select '$ALLOW_IP','$STORE' where not exists (select 1 from store_whitelist where store_id='$STORE' and ip='$ALLOW_IP')" >/dev/null
# Валюты Store: копируем с эталонного Store, исключая DAI (нет курса в binance —
# без этого walletprepare падает и форма оплаты остаётся без адресов).
$PSQL "insert into store_currencies (currency_id,store_id)
       select currency_id,'$STORE' from store_currencies
       where store_id=(select id from stores where name='First Store' limit 1)
         and currency_id not like 'DAI.%'
       on conflict do nothing" >/dev/null
APIKEY=$($PSQL "select key from store_api_keys where store_id='$STORE' limit 1")
[ -z "$APIKEY" ] && APIKEY=$($PSQL "insert into store_api_keys (store_id,key) values ('$STORE','dv_${NAME}_'||md5(random()::text)||md5(random()::text)) returning key")
CLIENTKEY=$($PSQL "select secret from store_secrets where store_id='$STORE' limit 1")
[ -z "$CLIENTKEY" ] && CLIENTKEY=$($PSQL "insert into store_secrets (store_id,secret) values ('$STORE','$(openssl rand -hex 32)') on conflict (store_id) do update set secret=excluded.secret, updated_at=now() returning secret")

ENVNAME="$NAME.env"
ENVF="/home/voiceagent/stores/$ENVNAME"
mkdir -p /home/voiceagent/stores
printf 'DV_STORE_ID=%s\nDV_API_KEY=%s\nDV_CLIENT_KEY=%s\nDV_MERCHANT_API=https://openpay.click/api/v1/external\n' "$STORE" "$APIKEY" "$CLIENTKEY" | tee "$ENVF" >/dev/null
chmod 600 "$ENVF"

# --- self-service delivery over HTTPS, IP-locked ---
PUB="/var/www/openpay.click/onboard"
mkdir -p "$PUB"
cp "$ENVF" "$PUB/$ENVNAME"; chmod 640 "$PUB/$ENVNAME"; chown root:www-data "$PUB/$ENVNAME"
CON=/etc/nginx/sites-available/openpay.conf
cp "$CON" "${CON}.bak-$(date +%Y%m%d-%H%M%S)"
if ! grep -q "location = /onboard/$ENVNAME" "$CON"; then
  sed -i "s|    location = /api/v1/external/wallet {|    # onboard $NAME: env читает только IP сайта\n    location = /onboard/$ENVNAME {\n        allow $ALLOW_IP;\n        deny all;\n    }\n    location = /api/v1/external/wallet {|" "$CON"
fi
# /api/v1/external/wallet: разрешить IP сайта
if ! grep -A3 "location = /api/v1/external/wallet" "$CON" | grep -q "allow $ALLOW_IP;"; then
  sed -i "s|    location = /api/v1/external/wallet {\n        allow 127.0.0.1;|&|" "$CON"
  sed -i "0,/    location = \/api\/v1\/external\/wallet {\n        allow 127.0.0.1;/s||&|" "$CON" || true
fi
# простая вставка allow перед deny в блоке external wallet (если ещё нет)
if ! awk '/location = \/api\/v1\/external\/wallet \{/,/\}/' "$CON" | grep -q "allow $ALLOW_IP;"; then
  python3 - "$CON" "$ALLOW_IP" <<'PY'
import sys,re
p,ip=sys.argv[1],sys.argv[2]
t=open(p).read()
m=re.search(r'(    location = /api/v1/external/wallet \{\n)',t)
if m: t=t[:m.end()]+f"        allow {ip};\n"+t[m.end():]
open(p,'w').write(t)
PY
fi
nginx -t 2>/dev/null && systemctl reload nginx
echo "OK store=$STORE webhook=$HOOK whitelist=$ALLOW_IP"
echo "env file: $ENVF (0600); self-service: https://openpay.click/onboard/$ENVNAME (только с $ALLOW_IP)"
