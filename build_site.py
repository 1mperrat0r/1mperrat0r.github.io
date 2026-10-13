"""Сайт-каталог Hustlers Bag для Pinterest: пины 1000x1500 + RSS-лента + index.html.

Запускается GitHub Actions раз в день. Берёт АКТИВНЫЕ товары из Etsy API, для новых делает пины.
Нужны секреты: ETSY_KEYSTRING, ETSY_SHARED_SECRET, ETSY_REFRESH_TOKEN.
"""
import html, io, json, os, sys, textwrap, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
SITE = "https://1mperrat0r.github.io"
API = "https://api.etsy.com/v3"
KEY, SECRET, REFRESH = (os.environ[k].strip() for k in ("ETSY_KEYSTRING", "ETSY_SHARED_SECRET", "ETSY_REFRESH_TOKEN"))
UA = {"User-Agent": "HustlersBag/1.0 (+https://1mperrat0r.github.io)"}
PINS_PER_LISTING = 3  # картинки карточки №1, 2, 4 → разные пины на один товар


def post_token():
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": KEY, "refresh_token": REFRESH}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{API}/public/oauth/token", data=data, headers=UA)) as r:
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
    state = json.loads(state_file.read_text()) if state_file.exists() else []
    known = {p["file"] for p in state}
    now = format_datetime(datetime.now(timezone.utc))
    for l in listings:
        lid = l["listing_id"]
        try:
            tr = api(f"/application/shops/{sid}/listings/{lid}/translations/en")
        except Exception:
            tr = {"title": l["title"], "description": l["description"]}
        full_title = html.unescape(tr["title"])
        short = full_title.split(",")[0].strip()
        desc = html.unescape(tr["description"]).split("\n\n")[0][:400]
        tags = " ".join("#" + t.replace(" ", "") for t in (tr.get("tags") or l.get("tags") or [])[:5])
        imgs = sorted(l.get("images") or [], key=lambda i: i["rank"])
        picks = [imgs[i] for i in (0, 1, 3) if i < len(imgs)][:PINS_PER_LISTING]
        for n, im in enumerate(picks, 1):
            name = f"pins/{lid}-{n}.jpg"
            if name in known:
                continue
            make_pin(im["url_fullxfull"], short, ROOT / name)
            state.append({"file": name, "listing_id": lid, "title": short if n == 1 else f"{short} — {['', 'Digital download', 'What you get', 'Printable'][n]}",
                          "description": f"{desc} {tags}".strip(), "link": l["url"].split("?")[0], "date": now})
            print("Новый пин:", name)
    active = {l["listing_id"] for l in listings}
    state = [p for p in state if p["listing_id"] in active]  # снятые с продажи товары убираем из ленты
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1))

    items = "".join(
        f"<item><title>{html.escape(p['title'])}</title><link>{html.escape(p['link'])}</link>"
        f"<description>{html.escape(p['description'])}</description><guid isPermaLink=\"false\">{p['file']}</guid>"
        f"<pubDate>{p['date']}</pubDate><enclosure url=\"{SITE}/{p['file']}\" type=\"image/jpeg\" length=\"0\"/></item>"
        for p in reversed(state))
    (ROOT / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Hustlers Bag</title>'
        f"<link>{SITE}</link><description>Printable planners, spreadsheets and wall art by Hustlers Bag</description>{items}</channel></rss>",
        encoding="utf-8")

    meta = (ROOT / "pinterest-meta.txt").read_text().strip() if (ROOT / "pinterest-meta.txt").exists() else ""
    cards = "".join(f'<a href="{html.escape(p["link"])}"><img src="{p["file"]}" alt="{html.escape(p["title"])}" loading="lazy"></a>'
                    for p in reversed(state) if p["file"].endswith("-1.jpg"))
    (ROOT / "index.html").write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>Hustlers Bag — Printable Planners, Spreadsheets & Wall Art</title>
<meta name="description" content="Digital planners, Excel and Google Sheets templates and printable wall art. Instant download on Etsy.">
<link rel="alternate" type="application/rss+xml" href="feed.xml">
<style>body{{margin:0;font-family:system-ui,sans-serif;background:#F4ECE2;color:#1F1D1A}}header{{text-align:center;padding:48px 16px 24px}}
header img{{width:96px;border-radius:50%}}h1{{font-family:Georgia,serif;font-size:40px;margin:12px 0 6px}}p{{color:#6B6359;margin:0}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:18px;max-width:1100px;margin:0 auto;padding:24px 16px 60px}}
.g img{{width:100%;border-radius:12px;box-shadow:0 10px 24px rgba(0,0,0,.12)}}a.shop{{display:inline-block;margin-top:16px;background:#1F1D1A;color:#fff;
padding:12px 28px;border-radius:30px;text-decoration:none}}</style></head><body>
<header><img src="logo.png" alt="Hustlers Bag"><h1>Hustlers Bag</h1><p>Printable planners, spreadsheets and wall art for people who get things done</p>
<a class="shop" href="https://www.etsy.com/shop/Hustlersbag">Visit the Etsy shop</a></header><div class="g">{cards}</div></body></html>""",
                                     encoding="utf-8")
    print(f"Товаров: {len(listings)}, пинов в ленте: {len(state)}")


if __name__ == "__main__":
    main()
