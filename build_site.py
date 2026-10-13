"""Сайт-каталог Hustlers Bag для Pinterest: пины 1000x1500 + RSS-лента + index.html.

Запускается GitHub Actions раз в день. Берёт АКТИВНЫЕ товары из Etsy API, для новых делает пины.
Нужны секреты: ETSY_KEYSTRING, ETSY_SHARED_SECRET, ETSY_REFRESH_TOKEN.
"""
import html, io, json, os, re, sys, textwrap, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
SITE = "https://1mperrat0r.github.io"
API = "https://api.etsy.com/v3"
KEY, SECRET, REFRESH = (os.environ[k].strip().strip("\ufeff") for k in ("ETSY_KEYSTRING", "ETSY_SHARED_SECRET", "ETSY_REFRESH_TOKEN"))
UA = {"User-Agent": "HustlersBag/1.0 (+https://1mperrat0r.github.io)"}
PINS_PER_LISTING = 3
URL_RE = re.compile(r"https?://\S+")  # картинки карточки №1, 2, 4 → разные пины на один товар


def post_token():
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": KEY, "refresh_token": REFRESH}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{API}/public/oauth/token", data=data, headers={"x-api-key": f"{KEY}:{SECRET}", **UA})) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Etsy token error {e.code}: {e.read()[:300]!r}")


TOKEN = post_token()


def api(path):
    req = urllib.request.Request(API + path, headers={"x-api-key": f"{KEY}:{SECRET}", "Authorization": f"Bearer {TOKEN}", **UA})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def font(name, size):
    return ImageFont.truetype(str(ROOT / "fonts" / name), size)


def make_pin(img_url, title, out):
    with urllib.request.urlopen(urllib.request.Request(img_url, headers=UA)) as r:
        src = Image.open(io.BytesIO(r.read())).convert("RGB")
    pin = Image.new("RGB", (1000, 1500), (244, 236, 226))
    d = ImageDraw.Draw(pin)
    d.rectangle([0, 0, 1000, 14], fill=(200, 85, 61))
    f = font("DMSerifDisplay-Regular.ttf", 78)
    lines = textwrap.wrap(title, 16)[:3]
    y = 90
    for line in lines:
        d.text((500, y), line, font=f, fill=(31, 29, 26), anchor="mt")
        y += 92
    w = 940
    h = int(src.height * w / src.width)
    if h > 1500 - y - 230:
        h = 1500 - y - 230
        w = int(src.width * h / src.height)
    src = src.resize((w, h), Image.LANCZOS)
    top = y + 40 + (1500 - y - 230 - h) // 2
    pin.paste(src, ((1000 - w) // 2, top))
    d.rounded_rectangle([250, 1330, 750, 1420], radius=45, fill=(31, 29, 26))
    d.text((500, 1375), "Instant download", font=font("Poppins-SemiBold.ttf", 38), fill=(255, 255, 255), anchor="mm")
    d.text((500, 1462), "HUSTLERS BAG  ·  ETSY", font=font("Poppins-Regular.ttf", 26), fill=(140, 130, 118), anchor="mm")
    pin.save(out, quality=90)


def main():
    user_id = TOKEN.split(".")[0]
    shop = api(f"/application/users/{user_id}/shops")
    sid = shop["shop_id"]
    listings = api(f"/application/shops/{sid}/listings?state=active&limit=100&includes=Images")["results"]
    state_file = ROOT / "pins.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else []
    known = {p["file"] for p in state}
    now = format_datetime(datetime.now(timezone.utc))
    products = {}
    for l in listings:
        lid = l["listing_id"]
        try:
            tr = api(f"/application/shops/{sid}/listings/{lid}/translations/en")
        except Exception:
            tr = {"title": l["title"], "description": l["description"]}
        full_title = html.unescape(tr["title"])
        short = full_title.split(",")[0].strip()
        full_desc = URL_RE.sub("", html.unescape(tr["description"]))
        desc = full_desc.split("\n\n")[0][:400]
        tags = " ".join("#" + t.replace(" ", "") for t in (tr.get("tags") or l.get("tags") or [])[:5])
        price = l["price"]["amount"] / l["price"]["divisor"]
        products[lid] = {"title": full_title, "short": short, "desc": full_desc, "currency": l["price"]["currency_code"],
                         "price": price, "etsy": l["url"].split("?")[0]}
        imgs = sorted(l.get("images") or [], key=lambda i: i["rank"])
        picks = [imgs[i] for i in (0, 1, 3) if i < len(imgs)][:PINS_PER_LISTING]
        for n, im in enumerate(picks, 1):
            name = f"pins/{lid}-{n}.jpg"
            if name in known:
                continue
            make_pin(im["url_fullxfull"], short, ROOT / name)
            state.append({"file": name, "listing_id": lid, "title": short if n == 1 else f"{short} — {['', 'Digital download', 'What you get', 'Printable'][n]}",
                          "description": f"{desc} {tags}".strip(), "date": now})
            print("Новый пин:", name)
    state = [p for p in state if p["listing_id"] in products]  # снятые с продажи товары убираем из ленты
    for p in state:
        p.pop("link", None)  # раньше тут была ссылка на Etsy — в ленте только наш домен
        p["description"] = URL_RE.sub("", p["description"]).strip()
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    page = lambda lid: f"{SITE}/p/{lid}.html"
    items = "".join(
        f"<item><title>{html.escape(p['title'])}</title><link>{page(p['listing_id'])}</link>"
        f"<description>{html.escape(p['description'])}</description>"
        f"<guid isPermaLink=\"false\">{page(p['listing_id'])}#{Path(p['file']).stem}</guid>"
        f"<pubDate>{p['date']}</pubDate><enclosure url=\"{SITE}/{p['file']}\" type=\"image/jpeg\" length=\"{(ROOT / p['file']).stat().st_size}\"/></item>"
        for p in reversed(state))
    (ROOT / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Hustlers Bag</title>'
        f"<link>{SITE}/</link><description>Printable planners, spreadsheets and wall art by Hustlers Bag</description>{items}</channel></rss>",
        encoding="utf-8")

    meta = (ROOT / "pinterest-meta.txt").read_text(encoding="utf-8").strip() if (ROOT / "pinterest-meta.txt").exists() else ""
    head = (f'<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta}'
            '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
            "<style>body{margin:0;font-family:system-ui,sans-serif;background:#F4ECE2;color:#1F1D1A}a{color:inherit}"
            "header{text-align:center;padding:48px 16px 24px}header img{width:96px;border-radius:50%}"
            "h1{font-family:Georgia,serif;font-size:40px;margin:12px 0 6px}.lead{color:#6B6359;margin:0}"
            ".g{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:18px;max-width:1100px;margin:0 auto;padding:24px 16px 60px}"
            ".g a{text-decoration:none}.g img{width:100%;border-radius:12px;box-shadow:0 10px 24px rgba(0,0,0,.12)}"
            ".g span{display:block;margin-top:8px;font-weight:600}"
            ".btn{display:inline-block;margin-top:16px;background:#1F1D1A;color:#fff;padding:14px 32px;border-radius:30px;text-decoration:none;font-weight:600}"
            ".pp{max-width:1100px;margin:0 auto;padding:24px 16px 60px;display:grid;grid-template-columns:1fr 1fr;gap:40px}"
            ".pp .pics{display:grid;gap:14px}.pp .pics img{width:100%;border-radius:12px;box-shadow:0 10px 24px rgba(0,0,0,.12)}"
            ".pp h1{font-size:34px;line-height:1.15}.price{font-size:28px;font-weight:700;color:#C8553D;margin:10px 0}"
            ".desc{white-space:pre-line;line-height:1.6;color:#3a352f}.back{display:inline-block;margin:24px 16px 0;color:#6B6359}"
            "@media(max-width:760px){.pp{grid-template-columns:1fr}}</style>")

    (ROOT / "p").mkdir(exist_ok=True)
    for old in (ROOT / "p").glob("*.html"):
        if int(old.stem) not in products:
            old.unlink()
    for lid, pr in products.items():
        pics = [p["file"] for p in state if p["listing_id"] == lid]
        imgs = "".join(f'<img src="/{f}" alt="{html.escape(pr["short"])}">' for f in pics)
        og = f'<meta property="og:title" content="{html.escape(pr["short"])}"><meta property="og:image" content="{SITE}/{pics[0]}">' if pics else ""
        (ROOT / "p" / f"{lid}.html").write_text(
            f'<!doctype html><html lang="en"><head>{head}<title>{html.escape(pr["short"])} — Hustlers Bag</title>'
            f'<meta name="description" content="{html.escape(pr["desc"][:155])}">{og}</head><body>'
            f'<a class="back" href="/">&larr; All products</a><div class="pp"><div class="pics">{imgs}</div><div>'
            f'<h1>{html.escape(pr["title"])}</h1><div class="price">{pr["price"]:.2f} {pr["currency"]}</div>'
            f'<a class="btn" href="{html.escape(pr["etsy"])}">Buy on Etsy</a>'
            f'<p class="desc">{html.escape(pr["desc"])}</p>'
            f'<a class="btn" href="{html.escape(pr["etsy"])}">Buy on Etsy</a></div></div></body></html>', encoding="utf-8")

    cards = "".join(f'<a href="/p/{p["listing_id"]}.html"><img src="/{p["file"]}" alt="{html.escape(p["title"])}" loading="lazy">'
                    f'<span>{html.escape(products[p["listing_id"]]["short"])}</span></a>'
                    for p in reversed(state) if p["file"].endswith("-1.jpg"))
    (ROOT / "index.html").write_text(
        f'<!doctype html><html lang="en"><head>{head}<title>Hustlers Bag — Printable Planners, Spreadsheets &amp; Wall Art</title>'
        '<meta name="description" content="Digital planners, Excel and Google Sheets templates and printable wall art. Instant download."></head><body>'
        '<header><img src="/logo.png" alt="Hustlers Bag"><h1>Hustlers Bag</h1>'
        '<p class="lead">Printable planners, spreadsheets and wall art for people who get things done</p>'
        f'<a class="btn" href="https://www.etsy.com/shop/Hustlersbag">Visit the Etsy shop</a></header><div class="g">{cards}</div></body></html>',
        encoding="utf-8")
    print(f"Товаров: {len(listings)}, страниц: {len(products)}, пинов в ленте: {len(state)}")


if __name__ == "__main__":
    main()
