#!/usr/bin/env python3
"""Make the Persian and Arabic home pages: fa/index.html and ar/index.html.

index.html is the English home page and the only one to edit by hand. This script
copies it, translates its fixed text with the page's own dictionary (const D in
index.html), and gives each copy its own language, title, description, canonical
address and topic links, so search engines can index all three languages.
The page's script still builds the dynamic parts (news, analyses, map) in the
right language, because each copy tells it which language it is (data-page-lang).

Needs Node.js (to read the dictionary). Run from anywhere:
    python scripts/build_langs.py
"""
import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "index.html"
SITE = "https://momenimojtaba.com"
IX = {"fa": 0, "ar": 1}

META = {
    "fa": {
        "title": "مجتبی مؤمنی | خاورمیانه",
        "og_title": "مجتبی مؤمنی | پژوهشگر خاورمیانه و مفسر رسانه‌ای",
        "description": "مجتبی مؤمنی؛ پژوهشگر سیاسی، تحلیلگر منطقه‌ای و روزنامه‌نگار. پژوهش، تحلیل و تفسیر دربارهٔ ایران، خاورمیانه و جنوب آسیا، منازعات منطقه‌ای و پناهندگی و مهاجرت.",
        "og_description": "پژوهش، تحلیل و تفسیر دربارهٔ ایران، خاورمیانه و جنوب آسیا، منازعات منطقه‌ای و پناهندگی و مهاجرت.",
        "locale": "fa_IR",
    },
    "ar": {
        "title": "مجتبى مؤمني | الشرق الأوسط",
        "og_title": "مجتبى مؤمني | باحث في شؤون الشرق الأوسط ومعلّق إعلامي",
        "description": "مجتبى مؤمني: باحث سياسي ومحلل إقليمي وصحفي. أبحاث وتحليلات وتعليقات حول إيران والشرق الأوسط وجنوب آسيا والنزاعات الإقليمية واللجوء والهجرة.",
        "og_description": "أبحاث وتحليلات وتعليقات حول إيران والشرق الأوسط وجنوب آسيا والنزاعات الإقليمية واللجوء والهجرة.",
        "locale": "ar_AR",
    },
}


def read_dictionary(src):
    """Return the D object from index.html as a Python dict (evaluated with Node)."""
    start = src.index("const D={") + len("const D=")
    depth, quote, escape, i = 0, None, False, start
    while True:
        c = src[i]
        if quote:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    literal = src[start:i + 1]
    out = subprocess.run(["node", "-e", "process.stdout.write(JSON.stringify(" + literal + "))"],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def translate_text(body, D, lang):
    """Translate text nodes that exactly match a dictionary entry, as the page's tr() does."""
    parts = re.split(r"(<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)", body, flags=re.S | re.I)
    for k, part in enumerate(parts):
        if not part or part.startswith("<"):
            continue
        text = html.unescape(part)
        key = text.strip()
        if key and key in D:
            lead = text[:len(text) - len(text.lstrip())]
            tail = text[len(text.rstrip()):]
            parts[k] = lead + html.escape(D[key][IX[lang]], quote=False) + tail
    return "".join(parts)


def set_meta(page, attr, name, value):
    pat = re.compile(r'(<meta\s+' + attr + r'="' + re.escape(name) + r'"\s+content=")[^"]*(")')
    if not pat.search(page):
        raise ValueError(f"meta {name} not found in index.html")
    return pat.sub(lambda m: m.group(1) + html.escape(value) + m.group(2), page, count=1)


def build(lang, src, D):
    m = META[lang]
    head_end = src.index("</head>")
    head, body = src[:head_end], src[head_end:]
    head = head.replace('<html lang="en">', f'<html lang="{lang}" dir="rtl" data-page-lang="{lang}">', 1)
    head = re.sub(r"<title>.*?</title>", f"<title>{html.escape(m['title'])}</title>", head, count=1, flags=re.S)
    head = set_meta(head, "name", "description", m["description"])
    head = set_meta(head, "property", "og:title", m["og_title"])
    head = set_meta(head, "property", "og:description", m["og_description"])
    head = set_meta(head, "property", "og:url", f"{SITE}/{lang}/")
    head = head.replace(f'<link rel="canonical" href="{SITE}/">', f'<link rel="canonical" href="{SITE}/{lang}/">', 1)
    head = head.replace('<meta property="og:type"', f'<meta property="og:locale" content="{m["locale"]}">\n<meta property="og:type"', 1)
    body = translate_text(body, D, lang)
    body = re.sub(r'href="/topic/([a-z-]+)-en\.html"', lambda x: f'href="/topic/{x.group(1)}-{lang}.html"', body)
    body = body.replace('href="/analyses/"', f'href="/analyses/{lang}/"')
    out = head + body
    if '<html lang="en">' in out or f'data-page-lang="{lang}"' not in out:
        raise ValueError("could not set the page language")
    return out


def main():
    src = SRC.read_text(encoding="utf-8")
    if 'data-page-lang' in src.split("</head>")[0]:
        sys.exit("index.html must be the English page without data-page-lang")
    D = read_dictionary(src)
    for lang in ("fa", "ar"):
        out_dir = ROOT / lang
        out_dir.mkdir(exist_ok=True)
        (out_dir / "index.html").write_text(build(lang, src, D), encoding="utf-8")
    print(f"home pages: fa/index.html, ar/index.html ({len(D)} dictionary entries)")


if __name__ == "__main__":
    main()
