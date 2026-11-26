#!/usr/bin/env python3
"""DV-merchant onboarding API: self-service store setup + sandbox transaction tests.

Runs on 127.0.0.1:18082 behind nginx, which enforces per-IP access.
No secrets in responses: keys are fetched only from IP-locked /onboard/<name>.env.
"""
import hmac, hashlib, json, subprocess, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PSQL = ["docker", "exec", "dv-postgres-database", "psql", "-U", "postgres", "-d", "dv_merchant", "-qAtc", ""]
MERCHANT = "http://127.0.0.1:18081/api/v1/external/wallet"
CREATE = "/opt/dv-bundle/scripts/create-store.sh"

def sql(q):
    cmd = PSQL[:-1] + [q]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()

def store_id(name):
    return sql("select id from stores where name='%s' limit 1" % name.replace("'", "''"))

def api_key(name):
    return sql("select k.key from store_api_keys k join stores s on s.id=k.store_id where s.name='%s' limit 1" % name.replace("'", "''"))

def client_key(name):
    return sql("select sec.secret from store_secrets sec join stores s on s.id=sec.store_id where s.name='%s' limit 1" % name.replace("'", "''"))

def err(h, code, msg):
    body = json.dumps({"ok": False, "error": msg}).encode()
    h.send_response(code); h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(body))); h.end_headers(); h.wfile.write(body)

def out(h, obj, code=200):
    body = json.dumps(obj).encode()
    h.send_response(code); h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(body))); h.end_headers(); h.wfile.write(body)

def log_event(project, kind, status="info", order_id="", amount=None, detail=None):
    """Best-effort write to local ops log; never fail the payment flow."""
    try:
        d = json.dumps({"project": project, "kind": kind, "status": status,
                        "order_id": order_id, "amount": amount, "detail": detail or {}}).encode()
        req = urllib.request.Request("http://127.0.0.1:18083/api/events", data=d,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).close()
    except Exception:
        pass

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *a): pass

    def do_GET(self):
        if self.path in ("/health", "/api/v1/onboard/health"):
            return out(self, {"ok": True})
        if self.path.startswith("/api/v1/onboard/store/"):
            name = self.path.rsplit("/", 1)[-1].replace("'", "''")
            sid = store_id(name)
            if not sid: return err(self, 404, "store not found")
            info = sql("select distinct s.name||' | '||s.site||' | '||coalesce(w.url,'-')||' | '||coalesce(wl.ip,'-') from stores s left join store_webhooks w on w.store_id=s.id left join store_whitelist wl on wl.store_id=s.id where s.id='%s'" % sid)
            return out(self, {"ok": True, "store_id": sid, "info": info,
                              "delivery_url": "https://openpay.click/onboard/%s.env" % name,
                              "has_api_key": bool(api_key(name)), "has_client_key": bool(client_key(name))})
        return err(self, 404, "not found")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: b = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return err(self, 400, "bad json")
        p = self.path

        if p == "/api/v1/onboard/store":
            for k in ("name", "site_url", "webhook_url", "ip"):
                if not b.get(k): return err(self, 400, "missing " + k)
            r = subprocess.run(["sudo", CREATE, b["name"], b["site_url"], b["webhook_url"], b["ip"]],
                               capture_output=True, text=True)
            if r.returncode: return err(self, 500, (r.stdout + r.stderr)[-400:])
            log_event(b["name"], "store_created", "info", detail={"ip": b["ip"], "webhook": b["webhook_url"]})
            return out(self, {"ok": True, "store_id": store_id(b["name"]),
                              "delivery_url": "https://openpay.click/onboard/%s.env" % b["name"],
                              "detail": r.stdout.strip().splitlines()[-1]})

        if p == "/api/v1/onboard/sandbox/payment":
            name, order, amount = b.get("name"), b.get("order_id"), b.get("amount", 0.10)
            if not name or not order: return err(self, 400, "name and order_id required")
            key = api_key(name)
            if not key: return err(self, 404, "store/keys not found")
            payload = json.dumps({"amount": amount, "currency_code": "USD",
                                  "store_external_id": "sandbox-" + order}).encode()
            req = urllib.request.Request(MERCHANT, data=payload, headers={
                "X-Api-Key": key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    d = json.load(r)["data"]
            except Exception as e:
                return err(self, 502, str(e))
            log_event(name, "sandbox_payment", "sandbox", order, amount, {"wallet": d.get("id")})
            return out(self, {"ok": True, "sandbox": True, "wallet_id": d.get("id"),
                              "pay_url": d.get("pay_url"), "note": "Ничего не оплачено; это тестовый счёт."})

        if p == "/api/v1/onboard/sandbox/webhook":
            name, order, amount = b.get("name"), b.get("order_id"), b.get("amount", 0.10)
            if not name or not order: return err(self, 400, "name and order_id required")
            sid, ckey = store_id(name), client_key(name)
            if not sid or not ckey: return err(self, 404, "store/keys not found")
            hook = sql("select url from store_webhooks where store_id='%s' and enabled limit 1" % sid)
            if not hook: return err(self, 404, "webhook not configured")
            payload = {"type": "PaymentReceived", "status": "paid", "sandbox": True,
                       "store_external_id": "sandbox-" + order, "amount": amount,
                       "currency_code": "USD"}
            raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
            sig = hmac.new(ckey.encode(), raw, hashlib.sha256).hexdigest()
            req = urllib.request.Request(hook, data=raw, headers={
                "Content-Type": "application/json", "X-Signature": sig}, method="POST")
            log_event(name, "sandbox_webhook", "sandbox",
                      payload["store_external_id"], amount)
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return out(self, {"ok": True, "sandbox": True, "webhook_status": r.status,
                                      "response": r.read(200).decode(errors="replace"),
                                      "order_id": payload["store_external_id"]})
            except urllib.error.HTTPError as e:
                return out(self, {"ok": False, "webhook_status": e.code,
                                  "response": e.read(200).decode(errors="replace")})
            except Exception as e:
                return err(self, 502, str(e))
        return err(self, 404, "not found")

ThreadingHTTPServer(("127.0.0.1", 18082), H).serve_forever()
