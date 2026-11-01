#!/usr/bin/env python3
"""Tell search engines about new or changed pages, after each publish.

- Reads sitemap.xml, finds pages that are new or whose file changed since the last run
  (state kept in data/search_ping.json).
- IndexNow (Bing, Yandex, Seznam, Naver and others): submits those pages. Needs only the
  key file at the site root ({key}.txt), which is in the repository.
- Google Search Console (optional, needs the GSC_SERVICE_ACCOUNT secret: a service account
  JSON key whose e-mail is added as a user of the momenimojtaba.com property):
  re-submits the sitemap and checks the index status of each new page, saving the result
  to data/index_status.json so it can be read later.
  Google offers no API for "Request indexing" on ordinary pages; sitemap submission is the
  supported route.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://momenimojtaba.com"
GSC_PROPERTY = "sc-domain:momenimojtaba.com"
STATE = ROOT / "data" / "search_ping.json"
STATUS = ROOT / "data" / "index_status.json"


def key():
    for p in ROOT.glob("*.txt"):
        k = p.read_text().strip()
        if p.stem == k and re.fullmatch(r"[0-9a-f]{32}", k):
            return k
    return None


def page_file(url):
    path = url[len(SITE):].lstrip("/")
    if path == "" or path.endswith("/"):
        path += "index.html"
    return ROOT / path


def sitemap_urls():
    return re.findall(r"<loc>([^<]+)</loc>", (ROOT / "sitemap.xml").read_text(encoding="utf-8"))


def post_json(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read().decode("utf-8", "replace")


def indexnow(urls, k):
    body = {"host": "momenimojtaba.com", "key": k, "keyLocation": f"{SITE}/{k}.txt", "urlList": urls}
    status, _ = post_json("https://api.indexnow.org/indexnow", body)
    return status in (200, 202)


def google_token(sa):
    from google.oauth2 import service_account          # pip install google-auth
    from google.auth.transport.requests import Request
    cred = service_account.Credentials.from_service_account_info(
        sa, scopes=["https://www.googleapis.com/auth/webmasters"])
    cred.refresh(Request())
    return cred.token


def google(urls, sa_json):
    tok = google_token(json.loads(sa_json))
    auth = {"Authorization": f"Bearer {tok}"}
    prop = urllib.parse.quote(GSC_PROPERTY, safe="")
    sm = urllib.parse.quote(f"{SITE}/sitemap.xml", safe="")
    req = urllib.request.Request(f"https://www.googleapis.com/webmasters/v3/sites/{prop}/sitemaps/{sm}",
                                 method="PUT", headers=auth)
    urllib.request.urlopen(req, timeout=60).read()
    print("::notice::Google: sitemap submitted")
    status = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    for u in urls[:200]:  # URL Inspection API quota is 2,000 a day
        try:
            _, txt = post_json("https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                               {"inspectionUrl": u, "siteUrl": GSC_PROPERTY}, auth)
            r = json.loads(txt)["inspectionResult"]["indexStatusResult"]
            status[u] = {"verdict": r.get("verdict"), "coverage": r.get("coverageState"),
                         "lastCrawl": r.get("lastCrawlTime"), "checked": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        except Exception as e:
            status[u] = {"error": str(e)[:200]}
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    wait = int(os.environ.get("WAIT_FOR_DEPLOY", "0"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    changed, hashes = [], {}
    for u in sitemap_urls():
        f = page_file(u)
        if not f.exists():
            continue
        h = hashlib.sha1(f.read_bytes()).hexdigest()
        hashes[u] = h
        if state.get(u) != h:
            changed.append(u)
    if not changed:
        print("No new or changed pages.")
        return 0
    print(f"{len(changed)} new or changed pages:\n  " + "\n  ".join(changed))
    if wait:
        time.sleep(wait)  # let Cloudflare finish deploying before engines fetch the pages
    k, ok = key(), False
    if k:
        try:
            ok = indexnow(changed, k)
            print(f"::notice::IndexNow: {len(changed)} pages submitted" if ok else "::warning::IndexNow refused the request")
        except Exception as e:
            print(f"::warning::IndexNow failed: {e}")
    sa = os.environ.get("GSC_SERVICE_ACCOUNT", "").strip()
    if sa:
        try:
            google(changed, sa)
        except Exception as e:
            print(f"::warning::Google Search Console step failed: {e}")
    else:
        print("::notice::Google: GSC_SERVICE_ACCOUNT not set; sitemap re-submission skipped (Google still reads sitemap.xml on its own)")
    if ok:
        for u in changed:
            state[u] = hashes[u]
        STATE.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
