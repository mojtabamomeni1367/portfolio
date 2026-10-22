#!/usr/bin/env python3
"""Collect Middle East and South Asia headlines into data/news.json.

Reads the feeds listed in config/sources.json, keeps only headlines that
mention a country on the site's map (config/countries.json), merges them
with the headlines already stored, and writes data/news.json.

Only the headline, source name, link and date are stored: the site shows
the headline and links readers to the original article.

Standard library only, so it runs anywhere Python 3.9+ is available.
"""
import email.utils
import hashlib
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "config" / "sources.json"
COUNTRIES = ROOT / "config" / "countries.json"
OUT = ROOT / "data" / "news.json"

KEEP_DAYS = 10          # drop headlines older than this
MAX_PER_COUNTRY = 40    # newest headlines kept per country
MAX_TOTAL = 400
TOP_COUNT = 14          # headlines flagged for the Top Stories column
TOP_PER_SOURCE = 3      # keep Top Stories varied across outlets
UA = "Mozilla/5.0 (compatible; momenimojtaba.com news bot)"


def now():
    return datetime.now(timezone.utc)


def build_matchers(cfg):
    """One compiled regex per (country, language)."""
    out = {}
    for code, langs in cfg["countries"].items():
        for lang, words in langs.items():
            words = [re.escape(w) for w in words if w]
            if not words:
                continue
            if lang == "en":
                # start-of-word match: "Iran" also matches "Iranian"
                pat = r"(?<![\w])(?:" + "|".join(words) + r")"
                out[(code, lang)] = re.compile(pat, re.IGNORECASE)
            else:
                # whole-word match for Persian/Arabic (ZWNJ counts as part of a word)
                pat = r"(?<![\w‌])(?:" + "|".join(words) + r")(?![\w‌])"
                out[(code, lang)] = re.compile(pat)
    return out


def tag(text, lang, matchers):
    found = []
    for (code, mlang), rx in matchers.items():
        if mlang == lang and rx.search(text):
            found.append(code)
    return sorted(set(found))


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def local(tagname):
    return tagname.rsplit("}", 1)[-1]


def child_text(el, name):
    for c in el:
        if local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_feed(raw):
    """Yield (title, link, date_str) from RSS 2.0, RSS 1.0 or Atom."""
    root = ET.fromstring(raw)
    for el in root.iter():
        name = local(el.tag)
        if name == "item":
            yield child_text(el, "title"), child_text(el, "link"), (
                child_text(el, "pubDate") or child_text(el, "date") or child_text(el, "updated"))
        elif name == "entry":
            link = ""
            for c in el:
                if local(c.tag) == "link" and c.get("rel", "alternate") == "alternate":
                    link = c.get("href", "")
                    break
            yield child_text(el, "title"), link, (
                child_text(el, "published") or child_text(el, "updated"))


def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = s.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm_title(t):
    return re.sub(r"[^\w]+", " ", t.lower()).strip()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def main():
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["feeds"]
    matchers = build_matchers(json.loads(COUNTRIES.read_text(encoding="utf-8")))

    old = []
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8")).get("items", [])
        except ValueError:
            old = []
    old_snapshot = json.dumps(old, sort_keys=True, ensure_ascii=False)

    cutoff = now() - timedelta(days=KEEP_DAYS)
    fresh, ok, failed = [], 0, []
    for src in sources:
        try:
            raw = fetch(src["url"])
            entries = list(parse_feed(raw))
            ok += 1
        except Exception as e:  # one broken feed must not stop the run
            failed.append(f"{src['name']} ({src['url']}): {e}")
            continue
        for title, link, ds in entries:
            title, link = clean(title), (link or "").strip()
            if not title or not link.startswith("http"):
                continue
            d = parse_date(ds) or now()
            if d < cutoff or d > now() + timedelta(hours=6):
                continue
            countries = tag(title, src.get("lang", "en"), matchers)
            if not countries:
                continue
            fresh.append({
                "id": hashlib.sha1(link.encode()).hexdigest()[:12],
                "title": title,
                "lang": src.get("lang", "en"),
                "source": src["name"],
                "url": link,
                "date": d.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "countries": countries,
            })

    # merge: fresh copies win, then keep stored ones that are still recent
    seen_id, seen_title, items = set(), set(), []
    for it in fresh + old:
        key_t = (it.get("lang"), norm_title(it["title"]))
        if it["id"] in seen_id or key_t in seen_title:
            continue
        if parse_date(it["date"]) and parse_date(it["date"]) < cutoff:
            continue
        seen_id.add(it["id"])
        seen_title.add(key_t)
        it.pop("top", None)
        items.append(it)

    items.sort(key=lambda x: x["date"], reverse=True)

    # cap per country and overall
    per, kept = {}, []
    for it in items:
        if all(per.get(c, 0) >= MAX_PER_COUNTRY for c in it["countries"]):
            continue
        for c in it["countries"]:
            per[c] = per.get(c, 0) + 1
        kept.append(it)
    kept = kept[:MAX_TOTAL]

    # Top Stories: newest headlines, a few per outlet
    by_src, n = {}, 0
    for it in kept:
        if n >= TOP_COUNT:
            break
        if by_src.get(it["source"], 0) >= TOP_PER_SOURCE:
            continue
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1
        it["top"] = True
        n += 1

    if ok == 0 and old:
        print("No feed could be read; keeping the existing file.", file=sys.stderr)
        for f in failed:
            print("  failed:", f, file=sys.stderr)
        return 1

    if json.dumps(kept, sort_keys=True, ensure_ascii=False) == old_snapshot:
        print(f"feeds read: {ok}/{len(sources)}; no change")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": now().strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(kept), "items": kept}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"feeds read: {ok}/{len(sources)}, new matches: {len(fresh)}, stored: {len(kept)}")
    for f in failed:
        print("  failed:", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
