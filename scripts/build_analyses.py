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
  topic/<topic>-<lang>.html     one page per site topic and language
  data/analyses.json            list the site reads for the map and Top Stories
  sitemap.xml                   every page, with its language versions
"""
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

import markdown

try:
    import yaml
except ImportError:  # the simple line parser below still works without it
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "content" / "analyses"
OUT_DIR = ROOT / "analysis"
OUT_JSON = ROOT / "data" / "analyses.json"
SITEMAP = ROOT / "sitemap.xml"
TOPIC_DIR = ROOT / "topic"
SITE = "https://momenimojtaba.com"
LANGS = ("en", "fa", "ar")
TOPICS = ("iran-policy", "mena-sa", "political-islam", "extremism", "migration", "security")

UI = {
    "en": {"back": "Back to site", "by": "Analysis by Mojtaba Momeni", "other": "Also available in"},
    "fa": {"back": "بازگشت به سایت", "by": "تحلیل از مجتبی مؤمنی", "other": "این تحلیل به زبان‌های دیگر"},
    "ar": {"back": "العودة إلى الموقع", "by": "تحليل مجتبى مؤمني", "other": "متوفر أيضاً بـ"},
}
LANG_NAME = {"en": "English", "fa": "فارسی", "ar": "العربية"}
OG_LOCALE = {"en": "en_US", "fa": "fa_IR", "ar": "ar_AR"}
AUTHOR = {"en": "Mojtaba Momeni", "fa": "مجتبی مؤمنی", "ar": "مجتبى مؤمني"}
HOME = {"en": "/", "fa": "/fa/", "ar": "/ar/"}
TOPIC_NAME = {
    "iran-policy": {"en": "Iran's Domestic Affairs & Foreign Policy", "fa": "مسائل داخلی و سیاست خارجی ایران", "ar": "الشؤون الداخلية والسياسة الخارجية لإيران"},
    "mena-sa": {"en": "Political Issues & Developments in the Middle East & South Asia", "fa": "مسائل و تحولات سیاسی خاورمیانه و جنوب آسیا", "ar": "القضايا والتطورات السياسية في الشرق الأوسط وجنوب آسيا"},
    "political-islam": {"en": "Political Islam & Islamist Movements", "fa": "اسلام سیاسی و جنبش‌های اسلام‌گرا", "ar": "الإسلام السياسي والحركات الإسلامية"},
    "extremism": {"en": "Extremism & Radicalism", "fa": "افراط‌گرایی و رادیکالیسم", "ar": "التطرف والراديكالية"},
    "migration": {"en": "Refugee & Migration Studies", "fa": "مطالعات پناهندگی و مهاجرت", "ar": "دراسات اللجوء والهجرة"},
    "security": {"en": "Regional Security & Geopolitics", "fa": "امنیت منطقه‌ای و ژئوپلیتیک", "ar": "الأمن الإقليمي والجغرافيا السياسية"},
}
TOPIC_DESC = {
    "iran-policy": {"en": "Analysis of Iran's domestic politics and its foreign policy towards the region and the wider world.",
                    "fa": "تحلیل سیاست داخلی ایران و سیاست خارجی آن در قبال منطقه و جهان.",
                    "ar": "تحليلات حول السياسة الداخلية الإيرانية وسياستها الخارجية تجاه المنطقة والعالم."},
    "mena-sa": {"en": "Analysis of political issues, elections and developments across the Middle East and South Asia.",
                "fa": "تحلیل مسائل سیاسی، انتخابات و تحولات خاورمیانه و جنوب آسیا.",
                "ar": "تحليلات حول القضايا السياسية والانتخابات والتطورات في الشرق الأوسط وجنوب آسيا."},
    "political-islam": {"en": "Analysis of political Islam and Islamist movements, their ideas, organisations and political roles.",
                        "fa": "تحلیل اسلام سیاسی و جنبش‌های اسلام‌گرا، اندیشه‌ها، سازمان‌ها و نقش سیاسی آن‌ها.",
                        "ar": "تحليلات حول الإسلام السياسي والحركات الإسلامية وأفكارها وتنظيماتها وأدوارها السياسية."},
    "extremism": {"en": "Analysis of extremism and radicalisation, violent groups and the responses to them.",
                  "fa": "تحلیل افراط‌گرایی و رادیکال‌شدن، گروه‌های خشونت‌گرا و واکنش‌ها به آن‌ها.",
                  "ar": "تحليلات حول التطرف والتحول إلى الراديكالية والجماعات العنيفة وسبل مواجهتها."},
    "migration": {"en": "Analysis of refugees, forced displacement and migration in the region and beyond.",
                  "fa": "تحلیل مسائل پناهندگان، آوارگی اجباری و مهاجرت در منطقه و فراتر از آن.",
                  "ar": "تحليلات حول اللاجئين والتهجير القسري والهجرة في المنطقة وخارجها."},
    "security": {"en": "Analysis of regional security, conflicts and the geopolitics of the Middle East and South Asia.",
                 "fa": "تحلیل امنیت منطقه‌ای، منازعات و ژئوپلیتیک خاورمیانه و جنوب آسیا.",
                 "ar": "تحليلات حول الأمن الإقليمي والنزاعات والجغرافيا السياسية في الشرق الأوسط وجنوب آسيا."},
}
TOPIC_UI = {
    "en": {"label": "Topic", "none": "Analyses on this topic will appear here soon.", "other": "In other languages", "home": "Home"},
    "fa": {"label": "موضوع", "none": "تحلیل‌های این موضوع به‌زودی اینجا منتشر می‌شود.", "other": "به زبان‌های دیگر", "home": "صفحهٔ اصلی"},
    "ar": {"label": "الموضوع", "none": "ستُنشر تحليلات هذا الموضوع هنا قريباً.", "other": "بلغات أخرى", "home": "الصفحة الرئيسية"},
}

PAGE = """<!DOCTYPE html>
<html lang="{lang}" dir="{dir}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{seo_title_esc}</title>
<meta name="description" content="{desc_esc}">
<meta name="author" content="{author}">
{keywords_meta}<link rel="canonical" href="{url}">
{alternates}<meta property="og:site_name" content="Mojtaba Momeni">
<meta property="og:title" content="{seo_title_esc}">
<meta property="og:description" content="{desc_esc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{url}">
<meta property="og:locale" content="{og_locale}">
<meta property="article:published_time" content="{date}">
{og_image}<meta name="twitter:card" content="{twitter_card}">
<meta name="twitter:title" content="{seo_title_esc}">
<meta name="twitter:description" content="{desc_esc}">
<script type="application/ld+json">{jsonld}</script>
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
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
article img,.cover img{{max-width:100%;height:auto;display:block}}
.cover{{margin:0 0 2rem}}
.other{{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--line);font-size:.9rem;color:var(--mut)}}
.other a{{color:var(--rust);margin-inline-end:1rem}}
.meta a{{color:var(--rust)}}
footer{{text-align:center;font-size:.8rem;color:var(--mut);padding:2rem 1rem;border-top:1px solid var(--line)}}
</style>
</head>
<body>
<header><div class="in"><a class="brand" href="{home}">Mojtaba Momeni</a><a href="{home}#analysis">{back}</a></div></header>
<main>
<p class="meta">{by} · <time datetime="{date}">{date}</time>{topics}</p>
<h1>{title_esc}</h1>
{summary_html}
{cover}<article>
{body}
</article>
{other}
</main>
<footer>© {year} Mojtaba Momeni</footer>
</body>
</html>
"""


def _header(block, name):
    """Read the header block. YAML first (the editing panel writes YAML), then a simple key: value fallback."""
    if yaml is not None:
        try:
            data = yaml.safe_load(block) or {}
            if isinstance(data, dict):
                return {str(k).strip().lower(): v for k, v in data.items()}
        except yaml.YAMLError:
            pass
    meta = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta


def _text(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip()


def _list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        items = v
    else:
        items = re.split(r"[,\s\[\]]+", str(v))
    return [str(x).strip() for x in items if str(x).strip()]


def _flag(v):
    return v is True or str(v).strip().lower() in ("true", "yes", "1")


def parse(path):
    text = path.read_text(encoding="utf-8").lstrip("\ufeff")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing the --- header block at the top")
    raw = _header(m.group(1), path.name)
    meta = {k: _text(v) for k, v in raw.items() if k not in ("countries", "topics")}
    for req in ("slug", "lang", "title", "date"):
        if not meta.get(req):
            raise ValueError(f"{path.name}: '{req}' is missing in the header")
    if meta["lang"] not in LANGS:
        raise ValueError(f"{path.name}: lang must be one of {', '.join(LANGS)}")
    meta["date"] = meta["date"][:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", meta["date"]):
        raise ValueError(f"{path.name}: date must look like 2026-10-22")
    meta["slug"] = re.sub(r"[^a-z0-9-]+", "-", meta["slug"].lower()).strip("-")
    meta["countries"] = [c.upper() for c in _list(raw.get("countries"))]
    meta["topics"] = [t.lower() for t in _list(raw.get("topics"))]
    bad = [t for t in meta["topics"] if t not in TOPICS]
    if bad:
        raise ValueError(f"{path.name}: unknown topic(s) {', '.join(bad)}; use {', '.join(TOPICS)}")
    meta["body_md"] = m.group(2).strip()
    meta["draft"] = _flag(raw.get("draft"))
    meta["translated"] = _flag(raw.get("translated"))
    return meta


def _abs(url):
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    # encode spaces and non-Latin letters so social networks can fetch the image
    return SITE + "/" + quote(url.lstrip("/"), safe="/%")


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
    url = f"{SITE}/analysis/{meta['slug']}-{lang}.html"
    seo_title = meta.get("seo_title") or f"{meta['title']} | {AUTHOR[lang]}"
    desc = meta.get("meta_description") or summary
    image = _abs(meta.get("image", ""))
    alt = meta.get("image_alt") or meta["title"]
    alternates = "".join(
        f'<link rel="alternate" hreflang="{s["lang"]}" href="{SITE}/analysis/{s["slug"]}-{s["lang"]}.html">\n'
        for s in siblings) if len(siblings) > 1 else ""
    ld = {
        "@context": "https://schema.org",
        "@type": "AnalysisNewsArticle",
        "headline": meta["title"][:110],
        "description": desc,
        "datePublished": meta["date"],
        "dateModified": meta.get("updated", "")[:10] or meta["date"],
        "inLanguage": lang,
        "mainEntityOfPage": url,
        "url": url,
        "author": {"@type": "Person", "name": AUTHOR[lang], "url": SITE + "/"},
        "publisher": {"@type": "Person", "name": AUTHOR[lang], "url": SITE + "/"},
    }
    if image:
        ld["image"] = [image]
    if meta.get("focus_keyword"):
        ld["keywords"] = meta["focus_keyword"]
    jsonld = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.format(
        seo_title_esc=html.escape(seo_title), desc_esc=html.escape(desc), author=AUTHOR[lang],
        keywords_meta=(f'<meta name="keywords" content="{html.escape(meta["focus_keyword"])}">\n'
                       if meta.get("focus_keyword") else ""),
        url=url, alternates=alternates, og_locale=OG_LOCALE[lang],
        og_image=(f'<meta property="og:image" content="{html.escape(image)}">\n'
                  f'<meta property="og:image:alt" content="{html.escape(alt)}">\n' if image else ""),
        twitter_card="summary_large_image" if image else "summary", jsonld=jsonld,
        cover=(f'<figure class="cover"><img src="{html.escape(image)}" alt="{html.escape(alt)}"></figure>\n'
               if image else ""),
        lang=lang, dir="rtl" if rtl else "ltr",
        title_esc=html.escape(meta["title"]), summary_esc=html.escape(summary),
        summary_html=f'<p class="sum">{html.escape(summary)}</p>' if summary else "",
        body_font=fonts[0], disp_font=fonts[1],
        brand_ls="0" if rtl else ".14em", brand_tt="none" if rtl else "uppercase",
        h_w="700" if rtl else "500",
        back=UI[lang]["back"], by=UI[lang]["by"], date=meta["date"], home=HOME[lang],
        topics="".join(f' · <a href="/topic/{t}-{lang}.html">{html.escape(TOPIC_NAME[t][lang])}</a>' for t in meta["topics"]),
        body=markdown.markdown(meta["body_md"], extensions=["extra", "sane_lists"]),
        other=other, year=meta["date"][:4],
    )


TOPIC_PAGE = """<!DOCTYPE html>
<html lang="{lang}" dir="{dir}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} | {author}</title>
<meta name="description" content="{desc}">
{robots}<link rel="canonical" href="{url}">
{alternates}<meta property="og:site_name" content="Mojtaba Momeni">
<meta property="og:title" content="{name}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=Instrument+Sans:wght@400;500&family=Vazirmatn:wght@400;500;700&display=swap">
<style>
:root{{--navy:#08141F;--or:#E2683A;--cream:#F5F0E7;--ink:#12212E;--mut:#5A6570;--line:#D9D0C0;--rust:#B5482A}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--cream);color:var(--ink);font:18px/1.75 {body_font}}}
header{{background:var(--navy);color:#EDE7DB;padding:1rem 1.25rem}}
header .in{{max-width:46rem;margin:0 auto;display:flex;justify-content:space-between;align-items:center;gap:1rem}}
header a{{color:inherit;text-decoration:none;font-size:.9rem}}
.brand{{font-family:{disp_font};letter-spacing:{brand_ls};text-transform:{brand_tt}}}
main{{max-width:46rem;margin:0 auto;padding:3rem 1.25rem 4rem}}
.meta{{font-size:.8rem;color:var(--rust);letter-spacing:.04em}}
h1{{font-family:{disp_font};font-weight:{h_w};font-size:clamp(1.8rem,5vw,2.6rem);line-height:1.25;margin:.6rem 0 1rem}}
.desc{{font-size:1.1rem;color:var(--mut);border-bottom:1px solid var(--line);padding-bottom:1.5rem}}
article{{padding:1.4rem 0;border-bottom:1px solid var(--line)}}
article time{{font-size:.8rem;color:var(--mut)}}
article h2{{font-family:{disp_font};font-weight:{h_w};font-size:1.35rem;line-height:1.45;margin:.3rem 0}}
article h2 a{{color:var(--ink);text-decoration:none}}article h2 a:hover{{text-decoration:underline}}
article p{{margin:.4rem 0 0;color:var(--mut);font-size:1rem}}
h3{{font-size:.95rem;color:var(--mut);margin-top:2.5rem}}
.none{{color:var(--mut)}}
.other{{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--line);font-size:.9rem;color:var(--mut)}}
.other a{{color:var(--rust);margin-inline-end:1rem}}
footer{{text-align:center;font-size:.8rem;color:var(--mut);padding:2rem 1rem;border-top:1px solid var(--line)}}
</style>
</head>
<body>
<header><div class="in"><a class="brand" href="{home}">Mojtaba Momeni</a><a href="{home}#research">{home_label}</a></div></header>
<main>
<p class="meta">{label}</p>
<h1>{name}</h1>
<p class="desc">{desc}</p>
{items}
{other}
</main>
<footer>© {year} Mojtaba Momeni</footer>
</body>
</html>
"""


def render_topic(topic, lang, items, year):
    rtl = lang in ("fa", "ar")
    ui = TOPIC_UI[lang]
    mine = [it for it in items if topic in it["topics"] and lang in it["versions"]]
    others = [it for it in items if topic in it["topics"] and lang not in it["versions"]]

    def card(it, l):
        v = it["versions"][l]
        summ = f'<p dir="auto">{html.escape(v["summary"])}</p>' if v.get("summary") else ""
        return (f'<article lang="{l}"><time datetime="{it["date"]}">{it["date"]}</time>'
                f'<h2 dir="auto"><a href="/{v["url"]}">{html.escape(v["title"])}</a></h2>{summ}</article>')

    body = "".join(card(it, lang) for it in mine)
    if others:
        body += f'<h3>{ui["other"]}</h3>' + "".join(card(it, next(iter(it["versions"]))) for it in others)
    if not body:
        body = f'<p class="none">{ui["none"]}</p>'
    url = f"{SITE}/topic/{topic}-{lang}.html"
    alts = "".join(f'<link rel="alternate" hreflang="{l}" href="{SITE}/topic/{topic}-{l}.html">\n' for l in LANGS)
    other = '<p class="other">' + "".join(
        f'<a href="{topic}-{l}.html" lang="{l}">{LANG_NAME[l]}</a>' for l in LANGS if l != lang) + "</p>"
    fonts = ("'Vazirmatn',sans-serif", "'Vazirmatn',sans-serif") if rtl else (
        "'Instrument Sans',system-ui,sans-serif", "'Newsreader',Georgia,serif")
    indexable = bool(mine or others)
    page = TOPIC_PAGE.format(
        lang=lang, dir="rtl" if rtl else "ltr", name=html.escape(TOPIC_NAME[topic][lang]), author=AUTHOR[lang],
        desc=html.escape(TOPIC_DESC[topic][lang]), url=url, alternates=alts,
        robots="" if indexable else '<meta name="robots" content="noindex, follow">\n',
        body_font=fonts[0], disp_font=fonts[1], brand_ls="0" if rtl else ".14em",
        brand_tt="none" if rtl else "uppercase", h_w="700" if rtl else "500",
        home=HOME[lang], home_label=ui["home"], label=ui["label"], items=body, other=other, year=year)
    return page, indexable


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
            "topics": sorted({t for v in versions for t in v["topics"]}, key=TOPICS.index),
            "versions": {v["lang"]: {"title": v["title"], "summary": v.get("summary", ""),
                                     "focus_keyword": v.get("focus_keyword", ""),
                                     "image": v.get("image", ""),
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
    # topic pages, one per topic and language
    TOPIC_DIR.mkdir(parents=True, exist_ok=True)
    year = items[0]["date"][:4] if items else "2026"
    topic_pages = []
    for t in TOPICS:
        for l in LANGS:
            page, indexable = render_topic(t, l, items, year)
            (TOPIC_DIR / f"{t}-{l}.html").write_text(page, encoding="utf-8")
            if indexable:
                topic_pages.append((t, l))

    # sitemap for search engines: every page, with its other language versions
    def entry(loc, lastmod, alts):
        links = "".join(f'<xhtml:link rel="alternate" hreflang="{h}" href="{u}"/>' for h, u in alts)
        return (f"  <url><loc>{loc}</loc>" + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "")
                + links + "</url>\n")

    latest = items[0]["date"] if items else None
    home_alts = [("en", SITE + "/"), ("fa", SITE + "/fa/"), ("ar", SITE + "/ar/"), ("x-default", SITE + "/")]
    rows = [entry(u, latest, home_alts) for _, u in home_alts[:3]]
    for it in items:
        alts = [(l, f"{SITE}/{v['url']}") for l, v in it["versions"].items()] if len(it["versions"]) > 1 else []
        rows += [entry(f"{SITE}/{v['url']}", it["date"], alts) for v in it["versions"].values()]
    for t in TOPICS:
        langs = [l for tt, l in topic_pages if tt == t]
        alts = [(l, f"{SITE}/topic/{t}-{l}.html") for l in langs] if len(langs) > 1 else []
        last = max((it["date"] for it in items if t in it["topics"]), default=None)
        rows += [entry(f"{SITE}/topic/{t}-{l}.html", last, alts) for l in langs]
    SITEMAP.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                       'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "".join(rows) + "</urlset>\n",
                       encoding="utf-8")

    print(f"analyses: {len(items)} ({sum(len(v) for v in groups.values())} language versions)")
    for e in errors:
        print("  skipped:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
