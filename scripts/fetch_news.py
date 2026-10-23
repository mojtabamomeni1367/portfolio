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
import os
import re
import sys
import time
import urllib.error
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

# Headline translation with Google Gemini (key in the GEMINI_API_KEY secret)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
TRANSLATE_BATCH = 20        # headlines per Gemini request
TRANSLATE_MAX_PER_RUN = 240 # safety cap per run
LANGS = ("en", "fa", "ar")
LANG_NAME = {"en": "English", "fa": "Persian (Farsi)", "ar": "Arabic"}


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


def err_text(e):
    """Short readable error, including the body of an HTTP error from the API."""
    msg = str(e)
    if hasattr(e, "read"):
        try:
            msg += " " + e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
    return msg.replace("\n", " ")


_MODEL = {"name": None, "candidates": None}


def model_candidates(key):
    """Text models this key can call, best first: newest stable 'flash' models, then others."""
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                                 headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        models = json.loads(r.read()).get("models", [])
    names = [m["name"].split("/", 1)[-1] for m in models
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("image", "tts", "audio", "live", "embedding", "vision", "banana", "robotics", "computer", "gemma", "learnlm")

    def ver(n):
        return [int(x) for x in re.findall(r"\d+", n)[:3]] or [0]

    def rank(n):
        return ("flash" in n, "preview" not in n and "exp" not in n, "lite" not in n, ver(n))

    good = [n for n in names if not any(x in n for x in bad)]
    return sorted(good, key=rank, reverse=True)


def gemini_call(body, key):
    if _MODEL["candidates"] is None:
        cands = []
        if os.environ.get("GEMINI_MODEL"):
            cands.append(os.environ["GEMINI_MODEL"])
        try:
            cands += [c for c in model_candidates(key) if c not in cands]
        except Exception as e:
            print(f"::warning::could not list Gemini models ({err_text(e)})")
        _MODEL["candidates"] = cands or [GEMINI_MODEL]
        print("::notice::Gemini models available: " + ", ".join(_MODEL["candidates"][:8]))
    payload = json.loads(body)
    tries = 0
    while True:
        name = _MODEL["name"] or _MODEL["candidates"][0]
        cfg = payload["generationConfig"]
        # translation needs no long reasoning: ask for minimal "thinking" to keep calls fast
        if _MODEL.get("thinking", True):
            cfg["thinkingConfig"] = {"thinkingLevel": "low"} if re.search(r"gemini-[3-9]|omni", name) else {"thinkingBudget": 0}
        else:
            cfg.pop("thinkingConfig", None)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
            if _MODEL["name"] != name:
                _MODEL["name"] = name
                print(f"::notice::Gemini model: {name}")
            return data
        except urllib.error.HTTPError as e:
            detail = err_text(e)
            if e.code == 400 and "thinking" in detail.lower() and _MODEL.get("thinking", True):
                _MODEL["thinking"] = False
                continue
            if e.code in (403, 404) and not _MODEL["name"] and len(_MODEL["candidates"]) > 1:
                print(f"::warning::model {name} unavailable ({e.code}); trying next")
                _MODEL["candidates"].pop(0)
                continue
            if e.code in (429, 500, 503) and tries < 2:
                tries += 1
                time.sleep(15 * tries)
                continue
            if e.code in (429, 500, 503) and not _MODEL["name"] and len(_MODEL["candidates"]) > 1:
                print(f"::warning::model {name} busy ({e.code}); trying next")
                _MODEL["candidates"].pop(0)
                tries = 0
                continue
            raise
        except (TimeoutError, OSError) as e:
            if tries < 1:
                tries += 1
                continue
            if not _MODEL["name"] and len(_MODEL["candidates"]) > 1:
                print(f"::warning::model {name} too slow ({e}); trying next")
                _MODEL["candidates"].pop(0)
                tries = 0
                continue
            raise


def gemini_translate(batch, key):
    """batch: list of items sharing one source language. Returns {id: {lang: title}}."""
    src = batch[0]["lang"]
    targets = [l for l in LANGS if l != src]
    lines = "\n".join(f'{i}\t{it["title"]}' for i, it in enumerate(batch))
    prompt = (
        f"You translate news headlines about the Middle East and South Asia for a researcher's website.\n"
        f"Translate each {LANG_NAME[src]} headline below into " + " and ".join(LANG_NAME[t] for t in targets) + ".\n"
        "Rules: translate faithfully and neutrally, as a news agency would; keep every claim, name and number; "
        "do not add, soften or comment; use the standard spelling of names in each language; "
        ""
        "Persian must be standard Iranian Persian; Arabic must be Modern Standard Arabic.\n"
        "Return only JSON: a list of objects with keys \"i\" (the number) and "
        + ", ".join(f'\"{t}\"' for t in targets) + ".\n\n"
        "Headlines (number, tab, headline):\n" + lines
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }).encode()
    data = gemini_call(body, key)
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    out = {}
    for row in json.loads(text):
        try:
            it = batch[int(row["i"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        tr = {t: clean(str(row.get(t, ""))) for t in targets}
        if all(tr.values()):
            out[it["id"]] = tr
    return out


def translate_missing(items):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("::warning::GEMINI_API_KEY not set: headlines stay in their original language.")
        return 0
    todo = [it for it in items if any(not it.get("title_" + l) for l in LANGS if l != it["lang"])]
    todo = todo[:TRANSLATE_MAX_PER_RUN]
    done = 0
    for lang in LANGS:
        group = [it for it in todo if it["lang"] == lang]
        for i in range(0, len(group), TRANSLATE_BATCH):
            batch = group[i:i + TRANSLATE_BATCH]
            try:
                res = gemini_translate(batch, key)
            except Exception as e:  # a failed batch is retried on the next run
                print(f"::warning::translation failed ({lang}, {len(batch)} headlines): {err_text(e)}")
                continue
            for it in batch:
                if it["id"] in res:
                    it["title_" + it["lang"]] = it["title"]
                    for t, v in res[it["id"]].items():
                        it["title_" + t] = v
                    done += 1
    print(f"::notice::translated with Gemini: {done}/{len(todo)}")
    return done


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
    old_by_id = {o["id"]: o for o in old}
    for it in fresh:
        prev = old_by_id.get(it["id"])
        if prev and prev.get("title") == it["title"]:
            for k, v in prev.items():
                if k.startswith("title_"):
                    it[k] = v
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

    translate_missing(kept)

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
