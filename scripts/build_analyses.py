#!/usr/bin/env python3
"""Turn the Markdown analyses in content/analyses/ into web pages.

Each analysis is one Markdown file per language, with a short header:

    ---
    slug: iran-gulf-detente-2026
    lang: fa
    title: عنوان تحلیل
    date: 2026-10-22
    countries: IRN, SAU
    summary: یک یا دو جمله خلاصه
    ---
    متن تحلیل ...

Files that share a slug are translations of the same analysis.

Output:
  analysis/<slug>-<lang>.html   one page per language version
  data/analyses.json            list the site reads for the map and Top Stories
"""
import html
import json
import re
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "content" / "analyses"
OUT_DIR = ROOT / "analysis"
OUT_JSON = ROOT / "data" / "analyses.json"
LANGS = ("en", "fa", "ar")

UI = {
    "en": {"back": "Back to site", "by": "Analysis by Mojtaba Momeni", "other": "Also available in"},
    "fa": {"back": "بازگشت به سایت", "by": "تحلیل از مجتبی مؤمنی", "other": "این تحلیل به زبان‌های دیگر"},
    "ar": {"back": "العودة إلى الموقع", "by": "تحليل مجتبى مؤمني", "other": "متوفر أيضاً بـ"},
}
LANG_NAME = {"en": "English", "fa": "فارسی", "ar": "العربية"}

PAGE = """<!DOCTYPE html>
<html lang="{lang}" dir="{dir}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_esc} | Mojtaba Momeni</title>
<meta name="description" content="{summary_esc}">
<meta property="og:title" content="{title_esc}">
<meta property="og:description" content="{summary_esc}">
<meta property="og:type" content="article">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=Instrument+Sans:wght@400;500&family=Vazirmatn:wght@400;500;700&display=swap">
<style>
:root{{--navy:#08141F;--or:#E2683A;--or2:#F08A5D;--cream:#F5F0E7;--ink:#12212E;--mut:#5A6570;--line:#D9D0C0;--rust:#B5482A}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--cream);color:var(--ink);font:18px/1.75 {body_font};}}
header{{background:var(--navy);color:#EDE7DB;padding:1rem 1.25rem}}
header .in{{max-width:46rem;margin:0 auto;display:flex;justify-content:space-between;align-items:center;gap:1rem}}
header a{{color:inherit;text-decoration:none;font-size:.9rem}}
.brand{{font-family:{disp_font};letter-spacing:{brand_ls};text-transform:{brand_tt}}}
main{{max-width:46rem;margin:0 auto;padding:3rem 1.25rem 4rem}}
.meta{{font-size:.8rem;color:var(--rust);letter-spacing:.04em}}
h1{{font-family:{disp_font};font-weight:{h_w};font-size:clamp(2rem,6vw,3rem);line-height:1.2;margin:.6rem 0 1rem}}
.sum{{font-size:1.15rem;color:var(--mut);border-bottom:1px solid var(--line);padding-bottom:1.5rem}}
article h2,article h3{{font-family:{disp_font};font-weight:{h_w};line-height:1.3;margin-top:2.2rem}}
article a{{color:var(--rust)}}
article blockquote{{margin:1.5rem 0;padding:.2rem 1.2rem;border-inline-start:3px solid var(--or);color:var(--mut)}}
article img{{max-width:100%;height:auto}}
.other{{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--line);font-size:.9rem;color:var(--mut)}}
.other a{{color:var(--rust);margin-inline-end:1rem}}
footer{{text-align:center;font-size:.8rem;color:var(--mut);padding:2rem 1rem;border-top:1px solid var(--line)}}
</style>
</head>
<body>
<header><div class="in"><a class="brand" href="../">Mojtaba Momeni</a><a href="../#news">{back}</a></div></header>
<main>
<p class="meta">{by} · <time datetime="{date}">{date}</time></p>
<h1>{title_esc}</h1>
{summary_html}
<article>
{body}
</article>
{other}
</main>
<footer>© {year} Mojtaba Momeni</footer>
</body>
</html>
"""


def parse(path):
    text = path.read_text(encoding="utf-8").lstrip("﻿")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing the --- header block at the top")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    for req in ("slug", "lang", "title", "date"):
        if not meta.get(req):
            raise ValueError(f"{path.name}: '{req}' is missing in the header")
    if meta["lang"] not in LANGS:
        raise ValueError(f"{path.name}: lang must be one of {', '.join(LANGS)}")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", meta["date"]):
        raise ValueError(f"{path.name}: date must look like 2026-10-22")
    meta["slug"] = re.sub(r"[^a-z0-9-]+", "-", meta["slug"].lower()).strip("-")
    meta["countries"] = [c.strip().upper() for c in re.split(r"[,\s\[\]]+", meta.get("countries", "")) if c.strip()]
    meta["body_md"] = m.group(2).strip()
    meta["draft"] = meta.get("draft", "").lower() in ("true", "yes", "1")
    return meta


def render(meta, siblings):
    lang = meta["lang"]
    rtl = lang in ("fa", "ar")
    fonts = ("'Vazirmatn',sans-serif", "'Vazirmatn',sans-serif") if rtl else (
        "'Instrument Sans',system-ui,sans-serif", "'Newsreader',Georgia,serif")
    other = ""
    alts = [s for s in siblings if s["lang"] != lang]
    if alts:
        other = '<p class="other">' + UI[lang]["other"] + ": " + "".join(
            f'<a href="{s["slug"]}-{s["lang"]}.html" lang="{s["lang"]}">{LANG_NAME[s["lang"]]}</a>' for s in alts) + "</p>"
    summary = meta.get("summary", "")
    return PAGE.format(
        lang=lang, dir="rtl" if rtl else "ltr",
        title_esc=html.escape(meta["title"]), summary_esc=html.escape(summary),
        summary_html=f'<p class="sum">{html.escape(summary)}</p>' if summary else "",
        body_font=fonts[0], disp_font=fonts[1],
        brand_ls="0" if rtl else ".14em", brand_tt="none" if rtl else "uppercase",
        h_w="700" if rtl else "500",
        back=UI[lang]["back"], by=UI[lang]["by"], date=meta["date"],
        body=markdown.markdown(meta["body_md"], extensions=["extra", "sane_lists"]),
        other=other, year=meta["date"][:4],
    )


def main():
    SRC.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    groups, errors = {}, []
    for p in sorted(SRC.glob("*.md")):
        if p.name.startswith("_") or p.name.lower() == "readme.md":
            continue
        try:
            meta = parse(p)
        except ValueError as e:
            errors.append(str(e))
            continue
        if meta["draft"]:
            continue
        groups.setdefault(meta["slug"], []).append(meta)

    wanted = set()
    items = []
    for slug, versions in groups.items():
        versions.sort(key=lambda v: LANGS.index(v["lang"]))
        for v in versions:
            name = f"{slug}-{v['lang']}.html"
            wanted.add(name)
            (OUT_DIR / name).write_text(render(v, versions), encoding="utf-8")
        countries = sorted({c for v in versions for c in v["countries"]})
        items.append({
            "id": slug,
            "date": max(v["date"] for v in versions),
            "countries": countries,
            "versions": {v["lang"]: {"title": v["title"], "summary": v.get("summary", ""),
                                     "url": f"analysis/{slug}-{v['lang']}.html"} for v in versions},
        })

    # remove pages whose source file was deleted
    for old in OUT_DIR.glob("*.html"):
        if old.name not in wanted:
            old.unlink()

    items.sort(key=lambda x: x["date"], reverse=True)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(f"analyses: {len(items)} ({sum(len(v) for v in groups.values())} language versions)")
    for e in errors:
        print("  skipped:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
