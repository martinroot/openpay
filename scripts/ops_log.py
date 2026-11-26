#!/usr/bin/env python3
"""Simple ops log: projects + payment/request statuses. SQLite, stdlib only.

API (also proxied as /ops/log/... for IP-locked agent writes):
  POST /api/projects {name, site, ip, store_id}
  GET  /api/projects
  POST /api/events {project, kind, order_id, status, amount, pay_url, detail}
  GET  /api/events?project=&status=&limit=200
  GET  / — HTML dashboard
"""
import json, sqlite3, html, os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB = "/opt/dv-bundle/data/ops.db"
os.makedirs(os.path.dirname(DB), exist_ok=True)
c = sqlite3.connect(DB, check_same_thread=False)
c.executescript("""
create table if not exists projects(id integer primary key autoincrement,
  name text unique not null, site text, ip text, store_id text, created_at text);
create table if not exists events(id integer primary key autoincrement,
  project text not null, ts text not null, kind text, order_id text, status text,
  amount real, pay_url text, source_ip text, detail text);
create index if not exists idx_events_project on events(project, id desc);
create index if not exists idx_events_status on events(status, id desc);
""")
c.commit()

def now(): return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def out(h, obj, code=200):
    b = json.dumps(obj, ensure_ascii=False).encode()
    h.send_response(code); h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(b))); h.end_headers(); h.wfile.write(b)

def html_page(q):
    proj = q.get("project", [""])[0]; status = q.get("status", [""])[0]
    rows = c.execute("select id,name,site,ip,store_id from projects order by name").fetchall()
    where, args = [], []
    if proj: where.append("project=?"); args.append(proj)
    if status: where.append("status=?"); args.append(status)
    sql = "select id,ts,project,kind,order_id,status,amount,pay_url,source_ip,detail from events"
    if where: sql += " where " + " and ".join(where)
    sql += " order by id desc limit 300"
    ev = c.execute(sql, args).fetchall()
    opts = "".join('<option value="%s"%s>%s</option>' % (html.escape(p[1]), " selected" if p[1]==proj else "", html.escape(p[1])) for p in rows)
    tr = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
        (html.escape(str(e[0])), html.escape(e[1]), html.escape(e[2]), html.escape(e[3] or ""),
         html.escape(e[4] or ""), '<span class="s">%s</span>' % html.escape(e[5] or ""),
         html.escape(str(e[6] or "")),
         ('<a href="%s">pay</a>' % html.escape(e[7])) if e[7] else ""
        ) for e in ev)
    return """<!doctype html><meta charset="utf-8"><title>OpenPay — ops log</title>
<style>body{font:14px system-ui;background:#0f1216;color:#dde3ea;margin:24px}
h1{font-size:20px}table{border-collapse:collapse;width:100%%}
th,td{padding:6px 9px;border-bottom:1px solid #28303a;text-align:left}
th{color:#8fa0b2}.s{color:#7ee787}form{display:inline-block;margin-right:12px}
select,input,button{background:#1b2129;color:#dde3ea;border:1px solid #394452;padding:5px;border-radius:4px}
a{color:#79c0ff}</style><h1>OpenPay · проекты и платежи</h1>
<form method="get"><select name="project"><option value="">все проекты</option>%s</select>
<select name="status"><option value="">все статусы</option>%s</select>
<button type="submit">Фильтр</button></form> <a href="/ops/">сбросить</a>
<p>Проектов: %d · событий в выборке: %d</p>
<table><tr><th>#</th><th>Время UTC</th><th>Проект</th><th>Тип</th><th>Заказ</th><th>Статус</th><th>$</th><th>Ссылка</th></tr>%s</table>""" % (
        opts, "".join('<option value="%s"%s>%s</option>' % (s, " selected" if s==status else "", s) for s in
                      ("pending", "paid", "sandbox", "error", "info")), len(rows), len(ev), tr)

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path in ("/health",): return out(self, {"ok": True, "db": DB})
        if u.path == "/api/projects":
            return out(self, {"ok": True, "projects": [dict(zip(("id","name","site","ip","store_id"),r)) for r in
                             c.execute("select id,name,site,ip,store_id from projects order by name")]})
        if u.path == "/api/events":
            return out(self, {"ok": True, "events": [dict(zip(("id","ts","project","kind","order_id","status","amount","pay_url","source_ip","detail"),r)) for r in
                             c.execute("select * from events order by id desc limit 300")]})
        if u.path == "/":
            b = html_page(q).encode()
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        return out(self, {"ok": False, "error": "not found"}, 404)
    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try: b = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return out(self, {"ok": False, "error": "bad json"}, 400)
        if u.path == "/api/projects":
            if not b.get("name"): return out(self, {"ok": False, "error": "name required"}, 400)
            c.execute("insert into projects(name,site,ip,store_id,created_at) values(?,?,?,?,?) on conflict(name) do update set site=excluded.site,ip=excluded.ip,store_id=excluded.store_id",
                      (b["name"], b.get("site",""), b.get("ip",""), b.get("store_id",""), now()))
            c.commit(); return out(self, {"ok": True, "project": b["name"]})
        if u.path == "/api/events":
            if not b.get("project") or not b.get("kind"):
                return out(self, {"ok": False, "error": "project and kind required"}, 400)
            c.execute("insert into events(project,ts,kind,order_id,status,amount,pay_url,source_ip,detail) values(?,?,?,?,?,?,?,?,?)",
                      (b["project"], now(), b["kind"], b.get("order_id",""), b.get("status","info"),
                       b.get("amount"), b.get("pay_url",""), self.headers.get("X-Forwarded-For") or self.client_address[0],
                       json.dumps(b.get("detail", {}), ensure_ascii=False)))
            c.commit(); return out(self, {"ok": True, "event_id": c.execute("select last_insert_rowid()").fetchone()[0]})
        return out(self, {"ok": False, "error": "not found"}, 404)

ThreadingHTTPServer(("127.0.0.1", 18083), H).serve_forever()
