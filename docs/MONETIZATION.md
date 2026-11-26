# Монетизация проектов OpenMVP через OpenPay (DV-merchant)

## Общая модель

- **Один Store на проект** (уже создан, см. `openpay-billing-inventory.md`).
- **Единый контракт чекаута:** `POST https://<домен>/api/checkout.php {"sku":"<SKU>","user_id":"<id>"}` →
  `{"order_id":"<project>-<sku>-<user>-<nonce>","pay_url":"https://openpay.click/pay/wallet/..."}`.
  Код SKU кодируется в `store_external_id` — webhook знает, что открыть.
- **Единый вебхук:** `POST https://<домен>/api/dv_webhook.php`, подпись `X-Signature`,
  идемпотентно по `order_id`. После `PaymentReceived`: выдать entitlement, записать событие
  в ops-лог (`pending → paid`).
- **Минимальный платёж DV:** $0.10. Всё, что дешевле — продаём **пачками/кредитами**
  (пополнение баланса), а не списанием за вызов.
- **Пricing-политика:** USD, разовая покупка или подписка (месяц оплачивается отдельным
  счётом; авто-продления нет — напоминание за 3 дня, продление кнопкой).

### Типы entitlement

| Тип | Что выдаёт | Срок |
|---|---|---|
| `license` | доступ к файлу/исходнику/пресету | навсегда |
| `plan` | доступ к функционалу | 30 дней с оплаты |
| `credits` | баланс вызовов/токенов/GPU-часов | до исчерпания |
| `tip` | разовая поддержка, без привилегий | — |

---

## По проектам

| Проект | Модель и цены | SKU → entitlement | Где показывать |
|---|---|---|---|
| **OpenMVP.online** | Free трекер; Pro `$9/mo`: приватные проекты, алерты по spend, экспорт | `omvp_pro` → plan 30d | баннер в Projects, страница тарифа |
| **ApiMedia** | Пресет `$2.99`; вся библиотека `$19/mo`; кредиты генерации `$5/500` | `ap_media_preset`, `ap_media_pro`, `ap_media_c500` → license/plan/credits | каталог preset, кнопка «Buy preset» |
| **VibeMetrics** | Starter `$9/mo` (1 сайт), Pro `$29/mo` (10 сайтов + API) | `vm_starter`, `vm_pro` → plan 30d | Settings → Billing |
| **FapaCRM** | `$9/mo` за домен сети, `$49/mo` за всю сеть (23 домена), `$99/mo` с BI | `fcrm_site`, `fcrm_network`, `fcrm_bi` → plan 30d | CRM → Billing |
| **OpenPay** | Внутренний расчётный слой: 0% «платёж за платёж»; доход = сервисы ниже. Для внешних клиентов — `$5/mo` мониторинг + `$0.10/счёт` | `op_monitor`, `op_invoice` → plan/credits | отдельная страница для партнёров |
| **GitGame** | Игра `$0.10–$1.65` (уже работает); исходник `$9`; bundle всех игр `$29`; `$12/mo`-play-pass | `gg_game_<slug>`, `gg_src_<slug>`, `gg_bundle`, `gg_pass` → license/plan | кнопки Buy на 288 играх, корзина |
| **Dagi** | `$19/mo` workbench; `$0.50/запуск` (кредиты `$10/20`) | `dagi_pro`, `dagi_c10` → plan/credits | Workbench → Upgrade |
| **CPARK** | `$29/mo` workspace; 1% от ад spend (минимум `$10/мес`) | `cpark_pro`, `cpark_spend10` → plan/credits | Billing |
| **Fabra** | Шаблон `$4.99`; все 200 `$29/mo`; команда `$79/mo` | `fb_tpl`, `fb_all`, `fb_team` → license/plan | каталог шаблонов |
| **TapApp CRM** | `$19/mo` (3 приложения), `$49/mo` (без лимита), ревшар 5% черезвстроенным paywall | `tap_pro`, `tap_unlim` → plan | Settings → Billing |
| **FaceBook Ads Studio** | `$3/видео`, `$19/mo` (30 рендеров), `$49/mo` (без лимита) | `fas_video`, `fas_pro`, `fas_unlim` → credits/plan | Studio → Export |
| **GSB API** | `$9/10k проверок`, `$29/50k`, `$99/250k`; демо 100 бесплатно | `gsb_c9`, `gsb_c29`, `gsb_c99` → credits | Docs → Pricing, 402 → checkout |
| **HumanBro** | `$0.05/ран` (кредиты `$5/100`), `$29/mo` безлимит выделенных профилей | `hb_c5`, `hb_pro` → credits/plan | Dashboard → Runs |
| **AiWebBack** | `$2/восстановление`, `$9/mo` (10 restored), `$29/mo` безлимит | `awb_one`, `awb_pro`, `awb_unlim` → license/plan | результат поиска → Restore |
| **Fapa** | `$1/тип` (ad-free 24ч), `$9/mo` Premium, `$29/mo` студия | `fapa_tip`, `fapa_prem`, `fapa_studio` → tip/plan | плеер, Premium-баннер |
| **AI Spy** | Free radar; Pro `$9/mo` (фильтры, alerts, дамп), `$49/mo` API | `ais_pro`, `ais_api` → plan | Alerts → Unlock |
| **IBody** | `$1/изображение`, `$5/5`, `$19/mo` (100) | `ib_one`, `ib_5`, `ib_pro` → license/credits/plan | результат генерации |
| **APIAdult** | Кредиты `$5 / $20 / $100` (токены по внутреннему курсу), `$49/mo` приоритет | `aapi_c5`, `aapi_c20`, `aapi_c100`, `aapi_prio` → credits/plan | Dashboard → Balance |
| **BI GPU** | `$0.50/час` (кредиты `$10/20ч`), `$99/mo` за выделенную карту | `gpu_c10`, `gpu_dedicated` → credits/plan | Compute → Rent |
| **Worker.skin** | `$19/mo` агент-воркер, `$0.10/задача` (кредиты `$5/50`) | `ws_pro`, `ws_c5` → plan/credits | Worker → Upgrade |
| **SpottyGun** | `$2/песня`, `$19/mo` (20 песен), `$49/mo` коммерческая лицензия | `sg_song`, `sg_pro`, `sg_commercial` → license/plan | Generate → Download |
| **BigQuery.live** | `$9/mo` (1000 запросов), `$29/mo` (10k + AI-отчёты) | `bq_pro`, `bq_team` → plan/credits | Query → Upgrade |
| **Dildo MLL** | Подписка поддержки `$5/mo`, набор данных `$49`, research-лицензия `$199` | `mll_patron`, `mll_data`, `mll_research` → plan/license | Site → Support/Datasets |

---

## Что нужно от каждого сайта (минимальный чек-лист)

1. `/etc/<name>/dv.env` — ключи из `https://openpay.click/onboard/<name>.env` (только с IP проекта).
2. `POST /api/checkout.php`: принять `sku` + `user_id`, создать заказ, дернуть
   `POST https://openpay.click/api/v1/external/wallet` с `X-Api-Key`, вернуть `pay_url`.
3. `POST /api/dv_webhook.php`: проверить `X-Signature` HMAC-SHA256 compact-JSON от CLIENT_KEY;
   по `PaymentReceived` → распарсить SKU из `store_external_id`, выдать entitlement,
   идемпотентно записать `paid`; фейк без подписи → 403.
4. `GET /api/status.php?order=…` — статус для UI (pending/paid).
5. events в ops-лог: `checkout` → `webhook` → `paid` (POST `/ops/log/events` с IP проекта).
6. Песочница до включения кнопки: `/api/v1/onboard/sandbox/payment` + `/sandbox/webhook`,
   затем реальный платёж $0.10 на одном SKU.

## Риски и решения

- **Микроцены ниже $0.10** — продавать только пачками кредитов; счёт за 1 вызов не создавать.
- **Подписки ручные** — нет авто-списаний DV; продление отдельным счётом, напоминалка
  за 3 дня, grace 24ч. При желании автоматизацию можно построить на сохранённом wallet_id,
  но без сохранения платёжных данных безопасно только ручное продление.
- **18+ проекты** (Fapa, IBody, APIAdult, Dildo MLL, FapaCRM) — платёжная форма нейтральна,
  но страницы должны соответствовать правилам платёжного шлюза и возрастному гейту.
- **Общий IP у части проектов** — ключи разные, но `/onboard/<name>.env` виден всем сайтам
  на этом IP; при необходимости перевести каждый проект на отдельный IP.
- **Entitlement в БД сайта** — openpay хранит только факт платежа; владелец SKU/пользователя — сайт.
