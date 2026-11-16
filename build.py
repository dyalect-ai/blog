"""Build the blog from posts.json.

  python build.py

Each post is a self-contained page in <slug>/ (index.html, og.jpg, fonts/), exported by the
project that writes it. This script:

  * generates the home page, the post index and the 404 page (posts/ holds the index);
  * enhances every exported post in place: heading ids, a table of contents, figure
    anchors, a reading time, Article JSON-LD, a footer and a back-to-contents link;
  * writes feed.xml, sitemap.xml and robots.txt.

Enhancement is idempotent: a post that already carries the marker comment is left alone.

site.json holds the public base URL, used for absolute og: links, the feed and the sitemap.
"""
import datetime
import html
import json
import os
import re
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = json.load(open(os.path.join(HERE, "site.json"), encoding="utf-8"))
BASE_PATH = urlparse(SITE["base"]).path or "/"
AUTHOR = "Dyalect Research"
# back matter stays out of the table of contents
SKIP_TOC = {"acknowledgements", "acknowledgments", "citation", "references"}
POSTS = sorted(json.load(open(os.path.join(HERE, "posts.json"), encoding="utf-8")), key=lambda p: p["date"], reverse=True)
MINUTES = {}  # slug -> reading time, filled while each post is enhanced

# The Dyalect mark: a frame with a gem in its top-right corner. On the page it takes the
# text colour (one orange element per screen is the headline's); the favicon carries the orange.
MARK = ('<svg viewBox="0 0 32 32" class="mark" aria-hidden="true">'
        '<rect x="2.6" y="2.6" width="26.8" height="26.8" rx="3" fill="none" stroke="currentColor" stroke-width="2.4"/>'
        '<rect x="16.4" y="7" width="8.6" height="8.6" fill="currentColor"/></svg>')
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='4' fill='%23000'/%3E%3Crect x='6' y='6' width='20' height='20' rx='2' "
           "fill='none' stroke='%23fff' stroke-width='2'/%3E%3Crect x='15.5' y='9.5' width='7' height='7' "
           "fill='%23F7611D'/%3E%3C/svg%3E")

FEED_LINK = '<link rel="alternate" type="application/atom+xml" title="{name}" href="{href}">'
SKIP = '<a class="skip" href="#main">Skip to content</a>'

FOOTER_NAV = ('<nav><a href="{rel}">Home</a><a href="{rel}posts/">All posts</a>'
              '<a href="{rel}feed.xml">RSS</a></nav>')

POST_CSS = """<style>
/* build.py additions: skip link, contents, figure links, footer, print (Signal design system) */
.skip { position: absolute; left: -9999px; top: 0; z-index: 99; background: #000; color: #fff; padding: 10px 16px; }
.skip:focus { left: 0; }
:focus-visible { outline: 2px solid #CF4607; outline-offset: 2px; }
nav.toc { margin: 0 0 72px; padding: 0; border-top: 1px solid #000; }
nav.toc .toc-h { margin: 0; padding: 12px 0 14px; font: 500 12px/1.3 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: #5B5A55; }
nav.toc ol { margin: 0; padding: 0; list-style: none; border-bottom: 1px solid #C2C0B9; }
nav.toc li { margin: 0; }
nav.toc li.l2 { border-top: 1px solid #E8E6E0; }
nav.toc a { position: relative; display: grid; grid-template-columns: 44px 1fr; align-items: baseline; padding: 11px 32px 11px 0;
            border: 0; color: #000; text-decoration: none; font-size: 16px; line-height: 1.35; }
nav.toc a::after { content: "→"; position: absolute; right: 4px; top: 11px; opacity: 0; transition: opacity 120ms cubic-bezier(.2,0,0,1); }
nav.toc a:hover .t { text-decoration: underline; text-underline-offset: 4px; }
nav.toc a:hover::after { opacity: 1; }
nav.toc .n { font: 500 12px/1 var(--mono); letter-spacing: .06em; color: #7B7973; }
nav.toc li.l3 a { padding: 0 32px 11px 0; margin-top: -3px; font-size: 14px; color: #5B5A55; }
nav.toc li.l3 a::before { content: "↳"; color: #A09E97; font-size: 12px; }
nav.toc li.l3 .n { display: none; }
nav.toc li.l3 a::after { top: 0; }
nav.toc + h2 { margin-top: 0; }
a.figref { color: #000; text-decoration: none; white-space: nowrap; border-bottom: 1px solid #A09E97; }
a.figref:hover { border-bottom-color: #000; }
figure[id] { scroll-margin-top: 24px; }
h2[id], h3[id] { scroll-margin-top: 24px; }
p.totop { margin: 56px 0 0; }
p.totop a { font: 500 12px var(--mono); letter-spacing: .06em; text-transform: uppercase; color: #000; text-decoration: none; border-bottom: 1px solid #000; }
p.totop a:hover { border-bottom-width: 2px; }
footer nav { display: flex; gap: 28px; }
footer nav a { color: inherit; text-decoration: none; border-bottom: 0; }
footer nav a:hover { color: #fff; }
@media print {
  header.hero, footer, nav.toc, p.totop, .skip { display: none !important; }
  main { max-width: none; padding: 0; }
  figure.wide { width: 100% !important; }
  body { font-size: 11pt; }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
</style>
"""


def esc(s):
    return html.escape(s, quote=True)


def nice_date(d):
    day = datetime.date.fromisoformat(d)
    return f"{day:%b} {day.day}, {day:%Y}"


def slugify(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "section"


def reading_minutes(body):
    """Words in the article itself: chrome, contents and footers are not reading."""
    text = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", body, flags=re.S)
    text = re.sub(r'<nav class="toc".*?</nav>', " ", text, flags=re.S)
    text = re.sub(r'<p class="totop">.*?</p>', " ", text, flags=re.S)
    text = re.sub(r"<footer.*?</footer>", " ", text, flags=re.S)
    text = re.sub(r'<div class="byline">.*?</div>', " ", text, flags=re.S)
    text = re.sub(r'<a class="skip".*?</a>', " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    words = len(text.split())
    return max(1, round(words / 220))


def topbar(rel, tab):
    on = ' class="on"'
    tabs = "".join(f'<a href="{rel}{href}"{on if name == tab else ""}><span class="n">{n}</span>{name}</a>'
                   for n, name, href in (("01", "Home", ""), ("02", "Blog", "posts/")))
    return (f'<nav class="top"><div class="wrap"><a class="brand" href="{rel}" aria-label="Dyalect home">{MARK}'
            f'<span class="word">dyalect</span></a><div class="tabs">{tabs}</div></div></nav>')


def site_footer(rel):
    return f"""<footer class="site" data-theme="dark">
<div class="wrap">
<div class="foot">
<div><a class="brand" href="{rel}">{MARK}<span class="word">dyalect</span></a>
<p>Specialized models for the enterprise, and the research behind them.</p></div>
{FOOTER_NAV.format(rel=rel)}
</div>
<p class="giant" aria-hidden="true">dyalect.</p>
<div class="base mono"><span>© {datetime.date.today().year} {esc(SITE['name'])}</span><span>Posts CC BY 4.0 · code MIT</span></div>
</div>
</footer>"""


def page(rel, path, title, desc, tab, hero, body, image=None, short=True):
    url = SITE["base"] + path
    image = image or SITE["base"] + "assets/og.jpg"
    slash = ("<script>if(!location.pathname.endsWith('/'))"
             "location.replace(location.pathname+'/'+location.search+location.hash)</script>\n" if path.endswith("/") or not path else "")
    feed = FEED_LINK.format(name=esc(SITE["name"]), href=rel + "feed.xml")
    return f"""<!doctype html>
<html lang="en">
<head>
{slash}<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="theme-color" content="#000000">
<meta property="og:url" content="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(SITE['name'])}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{image}">
<meta name="twitter:card" content="{'summary_large_image' if 'og.' in image else 'summary'}">
{feed}
<link rel="icon" href="{FAVICON}">
<link rel="apple-touch-icon" href="{rel}assets/avatar.png">
<link rel="stylesheet" href="{rel}assets/site.css">
</head>
<body>
{SKIP}
<header class="hero{' short' if short else ''}" data-theme="dark">
{topbar(rel, tab)}
<div class="wrap hero-in">
{hero}
</div>
</header>
<main id="main" class="wrap">
{body}
</main>
{site_footer(rel)}
</body>
</html>
"""


def post_meta(p):
    date = nice_date(p["date"])
    minutes = MINUTES.get(p["slug"])
    return f"{date} · {minutes} min read" if minutes else date


def display(title):
    """Display titles are sentence case closed by a full stop: a capital first letter, the rest lower case.
    Names and units with digits or inner capitals (Qwen2.5, 0.8B, LoRA) keep their spelling."""
    def word(w):
        letters = re.sub(r"[^A-Za-z]", "", w)
        if any(c.isdigit() for c in w) or (letters[1:] and letters[1:] != letters[1:].lower()):
            return w
        return w.lower()
    title = " ".join(word(w) for w in title.strip().split())
    title = title[0].upper() + title[1:]
    return title + ("" if title[-1] in ".?!" else ".")


def cards(rel):
    out = []
    for p in POSTS:
        href = f"{rel}{p['slug']}/"
        # the card shows the post's signature figure (cover.jpg); og.jpg, with the title on it, is for link previews
        art = "cover.jpg" if os.path.exists(os.path.join(HERE, p["slug"], "cover.jpg")) else "og.jpg"
        out.append(f"""<a class="post" href="{href}">
<img src="{href}{art}" alt="" loading="lazy">
<div class="body"><div class="meta"><span class="tag">{esc(p['tag'])}</span><span class="mono">{post_meta(p)}</span></div>
<h3>{esc(display(p['title']))}</h3>
<p>{esc(p['summary'])}</p>
<span class="link more">Read the post →</span></div>
</a>""")
    return '<div class="posts">\n' + "\n".join(out) + "\n</div>"


def section(num, title, intro=""):
    head = f'<div class="sec-head"><span class="mono">{num}</span><h2>{title}</h2></div>'
    return head + (f'\n<p class="intro">{intro}</p>\n' if intro else '\n<div style="height:40px"></div>\n')


def home():
    hero = """<div class="eyebrow">Dyalect / research</div>
<h1>Specialized intelligence for the <span class="hl">enterprise.</span></h1>
<p class="lead">General models know a little about everything. We build models that know your business.</p>
<div class="cta"><a class="btn" href="posts/">Read our research →</a></div>
<div class="pillars">
<div class="pillar"><h2><span class="marker">1</span>Adapt</h2><p>Adapted to your data and your tasks.</p></div>
<div class="pillar"><h2><span class="marker">2</span>Measure</h2><p>Measured on the checks that matter to you.</p></div>
<div class="pillar"><h2><span class="marker">3</span>Serve</h2><p>Served where you need them.</p></div>
</div>"""
    body = section("01", "Research.", "Part of our work is research on what happens inside models, and how to change it directly.") + cards("")
    return page("", "", SITE["name"], "Specialized intelligence for the enterprise.", "Home", hero, body, short=False)


def index():
    hero = """<div class="eyebrow">Blog / Dyalect research</div>
<h1>Research from <span class="hl">dyalect.</span></h1>
<p class="lead">What we learn while building specialized models: how to train them, measure them, serve them, and what happens inside them. Every post comes with the numbers behind its claims.</p>"""
    body = section("01", "All posts.") + cards("../")
    return page("../", "posts/", f"Blog · {SITE['name']}", "Research notes from Dyalect on building, measuring and understanding specialized models.",
                "Blog", hero, body)


def not_found():
    hero = """<div class="eyebrow">404 / not found</div>
<h1>This page doesn't <span class="hl">exist.</span></h1>
<p class="lead">The link may be old, or the post may have moved. Everything we have published is below.</p>"""
    body = section("01", "Try the blog.") + cards(BASE_PATH)
    return page(BASE_PATH, "404.html", f"Not found · {SITE['name']}", "Page not found.", "", hero, body)


def enhance_post(text, post):
    """Add ids, contents, figure anchors, reading time, JSON-LD and a footer to an export."""
    if "build:enhanced" in text:
        return text

    url = SITE["base"] + post["slug"] + "/"
    heading_count = len(re.findall(r"<h[23][^>]*>", text))
    minutes = reading_minutes(text)

    # 0. posts live one level below the site root, so nav written for the old
    #    blog/<slug>/ layout points one directory too high. Normalise it here so a
    #    fresh export is fixed on the next build.
    text = text.replace('class="brand" href="../../"', 'class="brand" href="../"')
    text = text.replace('<a href="../../">Home</a>', '<a href="../">Home</a>')
    text = text.replace('<a class="on" href="../">Blog</a>', '<a class="on" href="../posts/">Blog</a>')

    # 1. heading ids, collecting the contents on the way
    entries = []

    def head(m):
        lvl, attrs, inner = m.group(1), m.group(2), m.group(3)
        plain = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        num = ""
        mm = re.match(r"^(\d{2})\s*(.+)$", plain)
        if mm:
            num, plain = mm.group(1), mm.group(2)
        if "id=" in attrs:
            hid = re.search(r'id="([^"]+)"', attrs).group(1)
        else:
            hid = "sec-" + slugify(plain)
            attrs = f' id="{hid}"' + attrs
        entries.append((lvl, hid, num, plain))
        return f"<h{lvl}{attrs}>{inner}</h{lvl}>"

    text = re.sub(r"<h([23])([^>]*)>(.*?)</h\1>", head, text, flags=re.S)

    # 2. table of contents, right after the article opens
    if len(entries) >= 3 and 'nav class="toc"' not in text:
        has_intro = 'id="sec-introduction"' in text
        rows = ([] if has_intro else [("l2", "intro", "00", "Introduction")]) + [
            (f"l{lvl}", hid, num, label)
            for lvl, hid, num, label in entries
            if label.strip().lower() not in SKIP_TOC]
        items = "\n".join(
            f'<li class="{cls}"><a href="#{hid}"><span class="n">{num}</span>'
            f'<span class="t">{esc(label)}</span></a></li>'
            for cls, hid, num, label in rows)
        toc = ('<nav class="toc" id="toc" aria-label="Contents">\n'
               '<p class="toc-h">Contents</p>\n<ol>\n' + items + "\n</ol>\n</nav>\n")
        if not has_intro:
            toc += '<span id="intro"></span>\n'
        text = text.replace('<article class="col">', '<article class="col">\n' + toc, 1)

    # 3. figure anchors
    def figure(m):
        attrs, body = m.group(1), m.group(2)
        if "id=" in attrs:
            return m.group(0)
        n = re.search(r"Figure\s+(\d+)", body)
        if not n:
            return m.group(0)
        return f'<figure id="figure-{n.group(1)}"{attrs}>{body}</figure>'

    text = re.sub(r"<figure([^>]*)>(.*?)</figure>", figure, text, flags=re.S)

    # 4. in-text "Figure N" becomes a jump link
    def para(m):
        block = m.group(0)
        if "figref" in block:
            return block
        return re.sub(r"Figure (\d+)",
                      r'<a class="figref" href="#figure-\1">Figure \1</a>',
                      block)

    text = re.sub(r"<p(?: [^>]*)?>.*?</p>", para, text, flags=re.S)

    # 5. reading time, back to contents
    text = re.sub(r'(<div class="byline">.*?)(</div>)',
                  lambda m: f"{m.group(1)} · {minutes} min read{m.group(2)}",
                  text, count=1, flags=re.S)
    if 'class="totop"' not in text and "</article>" in text:
        text = text.replace("</article>",
                            '<p class="totop"><a href="#toc">↑ Back to contents</a></p>\n</article>', 1)

    # 6. footer with somewhere to go
    text = re.sub(
        r"<footer><div><span>.*?</span><span>.*?</span></div></footer>",
        '<footer><div><span>{name}</span>{nav}</div></footer>'.format(
            name=esc(AUTHOR), nav=FOOTER_NAV.format(rel="../")),
        text, count=1, flags=re.S)

    # 7. skip link
    if 'class="skip"' not in text:
        text = text.replace("<body>", "<body>\n" + SKIP, 1)
        text = re.sub(r"<main>", '<main id="main">', text, count=1)

    # 8. head additions: feed discovery, Article JSON-LD, styles
    ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post["title"],
        "description": post["summary"],
        "datePublished": post["date"],
        "url": url,
        "image": url + "og.jpg",
        "author": {"@type": "Organization", "name": AUTHOR},
        "publisher": {"@type": "Organization", "name": AUTHOR},
    }
    head_add = (
        FEED_LINK.format(name=esc(SITE["name"]), href="../feed.xml") + "\n"
        + ("" if 'rel="canonical"' in text else '<link rel="canonical" href="' + url + '">\n')
        + '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>\n"
        + POST_CSS
    )
    text = text.replace("</head>", head_add + "</head>", 1)
    text = text.rstrip() + "\n<!-- build:enhanced -->\n"
    return text


def feed():
    updated = POSTS[0]["date"] + "T00:00:00Z" if POSTS else "2026-01-01T00:00:00Z"
    entries = []
    for p in POSTS:
        url = SITE["base"] + p["slug"] + "/"
        entries.append(f"""  <entry>
    <title>{esc(p['title'])}</title>
    <link href="{url}"/>
    <id>{url}</id>
    <updated>{p['date']}T00:00:00Z</updated>
    <summary>{esc(p['summary'])}</summary>
  </entry>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{esc(SITE['name'])}</title>
  <link rel="alternate" type="text/html" href="{SITE['base']}"/>
  <link rel="self" type="application/atom+xml" href="{SITE['base']}feed.xml"/>
  <id>{SITE['base']}</id>
  <updated>{updated}</updated>
  <author><name>{esc(AUTHOR)}</name></author>
{chr(10).join(entries)}
</feed>
"""


def sitemap():
    urls = [SITE["base"], SITE["base"] + "posts/"]
    urls += [SITE["base"] + p["slug"] + "/" for p in POSTS]
    body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}\n</urlset>\n")


def robots():
    return ("User-agent: *\nAllow: /\n\n"
            f"Sitemap: {SITE['base']}sitemap.xml\n")


def write(path, text):
    full = os.path.join(HERE, path)
    os.makedirs(os.path.dirname(full) or HERE, exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    for p in POSTS:
        page_path = os.path.join(HERE, p["slug"], "index.html")
        assert os.path.exists(page_path), f"missing post {p['slug']}"
        original = open(page_path, encoding="utf-8").read()
        updated = enhance_post(original, p)
        minutes = reading_minutes(updated)
        updated = re.sub(r"·\s*\d+\s*min read", f"· {minutes} min read", updated, count=1)
        MINUTES[p["slug"]] = minutes
        if updated != original:
            with open(page_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(updated)
            print(f"enhanced {p['slug']} ({minutes} min)")
    write("index.html", home())
    write("posts/index.html", index())
    write("404.html", not_found())
    write("feed.xml", feed())
    write("sitemap.xml", sitemap())
    write("robots.txt", robots())
    write(".nojekyll", "")
    print(f"built {len(POSTS)} post(s) for {SITE['base']}")


if __name__ == "__main__":
    main()
