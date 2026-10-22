"""Reference solution: rebuilds Chromium's CORS preflight-cache decisions from the logs.

Reads only /app/data. Each browser profile keeps its own preflight cache, shared by its tabs and
emptied whenever its browser is restarted, partitioned by the top-level site of the frame that
made the request and keyed by the request URL. An entry holds
its expiry, whether the preflighting request was credentialed, and the allowed methods and
headers. A lookup that finds an expired entry, or one that does not cover the request, removes
it and a preflight goes out. Fetches made with cache no-store skip the lookup and store
nothing; URLs of 1024 characters or more are never stored.
"""
import bisect
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from urllib.parse import parse_qs, urlsplit

DATA = sys.argv[1] if len(sys.argv) > 1 else "/app/data"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/app/output/preflights.json"
API = "http://api.fleetdesk.test"
CONSOLE_SITE = "fleetdesk.test"
AUTHOR = {"authorization", "content-type", "idempotency-key", "x-desk-trace"}
SAFE_CT = {"application/x-www-form-urlencoded", "multipart/form-data", "text/plain"}
SAFE_METHODS = {"GET", "HEAD", "POST"}


def parse_ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc).timestamp()


def site_of(url):
    host = urlsplit(url).hostname or ""
    return ".".join(host.split(".")[-2:])


# ---------------------------------------------------------------- gateway preflight replies
def load_gateway():
    """Small reader for the two shipped config files (only the keys they use)."""
    text = open(f"{DATA}/gateway/edge.yaml").read()
    lines = [re.sub(r"\s+#.*$", "", l).rstrip() for l in text.splitlines()]
    lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]

    def val(v):
        v = v.strip()
        if v.startswith("["):
            return [x.strip().strip('"') for x in v[1:-1].split(",") if x.strip()]
        if v.startswith('"'):
            return v.strip('"')
        if v in ("true", "false"):
            return v == "true"
        try:
            return int(v)
        except ValueError:
            return v

    glob, routes, cur, sub, sect = {}, [], None, None, None
    for l in lines:
        ind = len(l) - len(l.lstrip())
        s = l.strip()
        if ind == 0:
            sect = s.rstrip(":")
            continue
        if sect == "cors" and ind == 2:
            k, v = s.split(":", 1)
            glob[k.strip()] = val(v)
        elif sect == "routes":
            if s.startswith("- "):
                cur = {"cors": {}, "add": []}
                routes.append(cur)
                k, v = s[2:].split(":", 1)
                cur[k.strip()] = val(v)
                sub = None
            elif ind == 4:
                k, v = s.split(":", 1)
                if v.strip():
                    cur[k.strip()] = val(v)
                    sub = None
                else:
                    sub = k.strip()
            elif ind == 6 and sub == "cors":
                k, v = s.split(":", 1)
                cur["cors"][k.strip()] = val(v)
            elif ind == 6 and sub == "append_response_headers":
                k, v = s.split(":", 1)
                cur["add"].append((k.strip(), str(val(v))))
    svc = json.load(open(f"{DATA}/gateway/reports-svc.cors.json"))["cors"]
    return glob, routes, svc


GLOB, ROUTES, SVC = load_gateway()


def route_for(path):
    best = None
    for r in ROUTES:
        if path.startswith(r["prefix"]) and (best is None or len(r["prefix"]) > len(best["prefix"])):
            best = r
    return best


def preflight_reply(path, acrh, appended=True):
    """Header fields (name, value) of the OPTIONS reply, as the edge sends them."""
    r = route_for(path)
    c = r["cors"] if r else {}
    h = []
    if c.get("preflight") == "forward":
        h.append(("access-control-allow-methods", ",".join(SVC["methods"])))
        h.append(("access-control-allow-headers", ",".join(SVC["allowedHeaders"])))
        h.append(("access-control-max-age", str(SVC["maxAge"])))
    else:
        h.append(("access-control-allow-methods", ", ".join(GLOB["allow_methods"])))
        ah = c.get("allow_headers", GLOB["allow_headers"])
        if ah == "reflect":
            if acrh:
                h.append(("access-control-allow-headers", acrh))
        else:
            h.append(("access-control-allow-headers", ", ".join(ah)))
        h.append(("access-control-max-age", str(c.get("max_age", GLOB["max_age"]))))
    for k, v in (r["add"] if r and appended else []):
        h.append((k.lower(), v))
    return h


def entry_from_reply(h):
    vals = defaultdict(list)
    for k, v in h:
        vals[k].append(v)
    raw = ", ".join(vals["access-control-max-age"]).strip()
    try:
        ma = float(int(raw)) if raw else 5.0
    except ValueError:
        ma = 5.0          # Chromium's default when the field doesn't parse
    ma = min(ma, 7200.0)
    methods = {m.strip() for v in vals["access-control-allow-methods"] for m in v.split(",") if m.strip()}
    hdrs = {m.strip().lower() for v in vals["access-control-allow-headers"] for m in v.split(",") if m.strip()}
    return ma, methods, hdrs


# ---------------------------------------------------------------- request fields
def header(rec, name, which="request_headers"):
    for k, v in rec[which]:
        if k.lower() == name:
            return v
    return None


def pv_of(rec):
    ref = header(rec, "referer") or ""
    return parse_qs(urlsplit(ref).query).get("pv", [None])[0]


def sid(value):
    m = re.search(r"fd_sid=([^;\s]+)", value or "")
    return m.group(1) if m else None


def classify(rec):
    unsafe = set()
    for k, v in rec["request_headers"]:
        k = k.lower()
        if k not in AUTHOR:
            continue
        if k == "content-type" and v.split(";")[0].strip().lower() in SAFE_CT:
            continue
        unsafe.add(k)
    no_store = "no-cache" in (header(rec, "pragma") or "").lower()
    creds = header(rec, "cookie") is not None
    return sorted(unsafe), no_store, creds


def main():
    # top-level site of every page load: /desk/ pages are tabs, /embed/ pages sit in a
    # partner portal, which the iframe load's Referer names
    pv_site, pv_load, desk_pvs = {}, {}, []
    for line in open(f"{DATA}/console_access.jsonl"):
        d = json.loads(line)
        pv = parse_qs(urlsplit(d["path"]).query).get("pv", [None])[0]
        pv_site[(d["client"], pv)] = site_of(d["referer"]) if d["path"].startswith("/embed/") else CONSOLE_SITE
        pv_load[(d["client"], pv)] = parse_ts(d["ts"])
        if d["path"].startswith("/desk/"):
            desk_pvs.append((d["client"], pv))

    recs = [json.loads(l) for l in open(f"{DATA}/api_access.jsonl")]

    # The reports route's appended Access-Control-Max-Age shows on the actual responses only
    # after the edge moved to the shipped configuration; before that, report preflights carried
    # reports-svc's value alone.
    switch = None
    for r in recs:
        if r["url"].startswith("/v1/reports/") and header(r, "access-control-max-age", "response_headers"):
            switch = parse_ts(r["ts"])
            break
    late = [r for r in recs if r["url"].startswith("/v1/reports/") and parse_ts(r["ts"]) >= switch]
    assert all(header(r, "access-control-max-age", "response_headers") for r in late)

    # A page load belongs to the browser profile whose fd_sid its credentialed calls carry (a
    # sign-in: the one its Set-Cookie creates). Partner embeds make no credentialed calls; they
    # are put with the workstation's first profile, though an embed's partition shares no entry
    # with a desk page either way.
    pv_prof, main_prof, pv_last = {}, {}, {}
    for r in recs:
        c = sid(header(r, "cookie")) or sid(header(r, "set-cookie", "response_headers"))
        if c:
            pv_prof.setdefault((r["client"], pv_of(r)), c)
            main_prof.setdefault(r["client"], c)
        pv_last[(r["client"], pv_of(r))] = parse_ts(r["ts"])

    # Desk tabs are never reloaded, navigated or closed, so a profile's desk tabs stop only when
    # its browser closes. A desk page load starts a new browser run (an empty preflight cache)
    # unless an earlier desk tab of the same profile is still making requests after it; the
    # profile's cookie survives the restart, the in-memory cache doesn't.
    runs = defaultdict(list)
    seen = defaultdict(list)
    for key in sorted(desk_pvs, key=lambda k: pv_load[k]):
        if key not in pv_prof:
            continue    # a page load that made no API call
        prof = (key[0], pv_prof[key])
        if not any(pv_last[q] > pv_load[key] for q in seen[prof]):
            runs[prof].append(pv_load[key])
        seen[prof].append(key)

    def run_at(prof, t):
        return bisect.bisect_right(runs[prof], t)

    caches = defaultdict(dict)
    out = {}
    for r in recs:
        t = parse_ts(r["ts"])
        key = (r["client"], pv_of(r))
        site = pv_site[key]
        prof = (r["client"], pv_prof.get(key, main_prof[r["client"]]))
        part = caches[(prof, run_at(prof, t), site)]
        unsafe, no_store, creds = classify(r)
        method = r["method"]
        if method in SAFE_METHODS and not unsafe:
            out[r["rid"]] = False
            continue
        url = API + r["url"]
        ckey = url
        if not no_store:
            e = part.get(ckey)
            if e is not None:
                ok = t < e["exp"]
                ok = ok and (e["creds"] or not creds)
                ok = ok and (method in SAFE_METHODS or method in e["methods"])
                ok = ok and all(n in e["headers"] for n in unsafe)
                if ok:
                    out[r["rid"]] = False
                    continue
                del part[ckey]
        out[r["rid"]] = True
        reply = preflight_reply(r["url"].split("?")[0], ",".join(unsafe), t >= switch)
        ma, methods, hdrs = entry_from_reply(reply)
        if not no_store and len(url) < 1024 and ma > 0:
            part[ckey] = {"exp": t + ma, "creds": creds, "methods": methods, "headers": hdrs}
    json.dump({"preflighted": out}, open(OUT, "w"), indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
