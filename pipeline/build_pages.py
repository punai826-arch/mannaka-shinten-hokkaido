"""公開用サイト public/ を作る（SEOを考えた静的ページ＋まんなか検索アプリ）

できるページ
  /                         トップ：まんなか検索（主役）＋市町への入口
  /city/<市町>/              市町ごとの新店一覧（検索エンジンが読める静的HTML）
  /mannaka/<市町>-<市町>/    2つの市町の「まんなか」ページ（人口3万人以上どうし・車30分以上）
  /sitemap.xml /robots.txt /404.html

使い方: python pipeline/build_pages.py [--index]
  --index を付けると検索エンジンに載せる（PoCの間は付けない＝noindex）
公開してはいけない項目（電話番号・フリガナ・法人名）が shops.json に入っていたら止まる。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import shutil
import urllib.parse
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE, PUB = ROOT / "site", ROOT / "public"
SITE_URL = "https://shiroto-ransha.github.io/mannaka-shinten-hokkaido/"
BRAND = "まんなか新店 北海道"
PRIVATE_KEYS = {"tel", "kana", "corp", "kinds", "genreReason"}
PAIR_MIN_POP, PAIR_MIN_MINUTES = 30000, 30

SLUG = {
    "札幌市": "sapporo", "旭川市": "asahikawa", "函館市": "hakodate", "苫小牧市": "tomakomai", "帯広市": "obihiro",
    "釧路市": "kushiro", "江別市": "ebetsu", "北見市": "kitami", "小樽市": "otaru", "千歳市": "chitose",
    "室蘭市": "muroran", "岩見沢市": "iwamizawa", "恵庭市": "eniwa", "北広島市": "kitahiroshima", "石狩市": "ishikari",
    "音更町": "otofuke", "登別市": "noboribetsu", "北斗市": "hokuto", "滝川市": "takikawa", "網走市": "abashiri",
    "伊達市": "date", "稚内市": "wakkanai", "七飯町": "nanae", "名寄市": "nayoro", "幕別町": "makubetsu",
    "中標津町": "nakashibetsu", "根室市": "nemuro", "新ひだか町": "shinhidaka", "紋別市": "monbetsu",
    "富良野市": "furano", "釧路町": "kushiro-town", "深川市": "fukagawa", "美唄市": "bibai", "留萌市": "rumoi",
    "芽室町": "memuro", "遠軽町": "engaru", "美幌町": "bihoro", "余市町": "yoichi", "士別市": "shibetsu",
    "砂川市": "sunagawa", "当別町": "tobetsu", "八雲町": "yakumo", "倶知安町": "kutchan", "白老町": "shiraoi",
    "別海町": "betsukai", "森町": "mori", "浦河町": "urakawa", "斜里町": "shari", "芦別市": "ashibetsu",
    "栗山町": "kuriyama", "岩内町": "iwanai", "日高町": "hidaka",
}
RISK = {"確認済み": ("ok", "✓ 運営が確認済み"), "確実": ("hi", "自動照合・確度 高"), "おそらく": ("mid", "⚠ 自動照合・確度 中（別のお店の可能性）")}

e = lambda s: html.escape(str(s or ""), quote=True)  # noqa: E731


def hm(m: int) -> str:
    return f"{m}分" if m < 60 else f"{m // 60}時間" + (f"{m % 60}分" if m % 60 else "")


def fmt(d: str) -> str:
    y, m, dd = map(int, d.split("-"))
    return f"{y}年{m}月{dd}日"


# ---------------------------------------------------------------- 共通の枠
def page(*, rel: str, path: str, title: str, desc: str, body: str, noindex: bool, jsonld: list, app: bool = False,
         people: list[str] | None = None) -> str:
    canon = SITE_URL + path
    ld = "\n".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in jsonld)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canon)}">
{'<meta name="robots" content="noindex, nofollow">' if noindex else ''}
<meta name="theme-color" content="#F4F8FC">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(canon)}">
<meta property="og:locale" content="ja_JP">
<meta name="twitter:card" content="summary">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;500;700&family=Zen+Maru+Gothic:wght@500;700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{rel}style.css">
{ld}
</head>
<body{f' data-people="{e(",".join(people))}"' if people else ''}>
<header class="top"><a class="brand" href="{rel}" aria-label="{BRAND} トップへ">
  <svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><circle cx="5" cy="9" r="3.2" fill="#14284B"/><circle cx="27" cy="7" r="3.2" fill="#D9668A"/><circle cx="22" cy="27" r="3.2" fill="#8E7CD6"/><path d="M5 9L16 16M27 7L16 16M22 27L16 16" stroke="#2C5FA8" stroke-width="1.6" stroke-dasharray="2 2.4" fill="none"/><circle cx="16" cy="16" r="4.6" fill="#2C5FA8"/></svg>
  <span class="brand-name">まんなか新店<small>北海道</small></span></a>
  <p class="poc">試作版です。お店の情報とリンクは自動で集めたもので、誤りを含みます。<a href="https://github.com/shiroto-ransha/mannaka-shinten-hokkaido/issues/new" target="_blank" rel="noopener">誤りを知らせる</a></p></header>
{body}
<footer class="foot">
  <nav class="foot-nav"><a href="{rel}">まんなかを探す</a> ・ <a href="{rel}city/">市町から新店を探す</a></nav>
  <p><b>データについて</b>：お店は厚生労働省「食品衛生申請等システム」のオープンデータ（北海道・札幌市・函館市・旭川市・小樽市）を加工して作成しています（開店3年以内の抽出、ジャンル分類、以前から営業している可能性の推定などは、このサイトによる加工です）。電子申請で公開に同意したお店だけが載るため、すべての新店ではありません。「許可日」は開店日の目安です。</p>
  <p>リンク（Instagram・公式サイト・食べログ）は、公開情報をもとにプログラムが自動で紐づけたものを含み、確度を表示しています。写真や口コミは掲載していません。移動時間は OpenStreetMap の道路データによる車の所要時間の目安（OSRM）で、渋滞や積雪は考えていません。地図：© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors</p>
  <p class="gen" id="generated"></p>
</footer>
<div class="scrim" id="scrim"></div>
<aside class="sheet" id="sheet" role="dialog" aria-modal="true" aria-labelledby="dName"><button class="close" id="close" aria-label="閉じる">×</button><div class="grab"></div><div id="detail"></div></aside>
<div class="toast" id="toast" role="status"></div>
<script>window.SITE_ROOT = "{rel}";</script>
<script src="{rel}config.js"></script>
<script type="module" src="{rel}app.js"></script>
</body>
</html>
"""


SEARCH_FORM = """<section class="finder" id="finder" aria-labelledby="finderTitle">
  <h2 id="finderTitle" class="finder-title">住んでいる市町を、人数ぶん</h2>
  <div id="people" class="people"></div>
  <div class="finder-row">
    <button id="addPerson" class="add" type="button">＋ もう1人</button>
    <label class="toggle"><input type="checkbox" id="withBar"><span>お酒のお店も含める</span></label>
  </div>
  <button id="findMid" class="go" type="button">まんなかを探す</button>
</section>
<section class="results" id="results" hidden aria-live="polite" aria-labelledby="resTitle">
  <div class="res-head">
    <h2 id="resTitle" class="res-title">まんなかの候補</h2>
    <button class="edit" id="editPeople" type="button">市町を変える</button>
  </div>
  <div class="res-grid">
    <div id="map" class="map"><div class="map-off" id="mapOff" hidden></div></div>
    <div class="res-side">
      <div class="cand-tabs" id="cands" role="tablist" aria-label="まんなかの候補"></div>
      <div class="cand-meta" id="candMeta"></div>
      <h3 class="rail-title" id="railTitle"></h3>
      <div class="chips" id="genreChips" role="group" aria-label="ジャンルで絞る"></div>
      <div class="rail" id="list" aria-label="新しいお店"></div>
      <div class="res-actions"><a class="cityall" id="cityLink" href="#">この街の新店をすべて見る</a><button class="share" id="share" type="button">結果を送る</button></div>
    </div>
  </div>
  <p class="fine">車の所要時間の目安です（渋滞・積雪は含みません）。候補は、食事・お茶の新店が3店以上ある市町です。</p>
</section>"""


def shop_li(s: dict, genre: dict) -> str:
    g = genre[s["genre"]]
    links = []
    if s.get("instagram"):
        links.append((f"https://www.instagram.com/{s['instagram']}/", f"Instagram @{s['instagram']}", s.get("igConf")))
    if s.get("website"):
        links.append((s["website"], "公式サイト", s.get("webConf")))
    if s.get("tabelog"):
        links.append((s["tabelog"], "食べログ", s.get("tbConf")))
    lk = "".join(f'<a class="slink risk-{RISK.get(c, ("mid",""))[0]}" href="{e(u)}" target="_blank" rel="noopener nofollow">{e(t)}'
                 f'<small>{e(RISK.get(c, ("mid", "⚠ 自動照合"))[1])}</small></a>' for u, t, c in links)
    gmap = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(s["name"] + " " + s["address"])
    badges = ("" if not s.get("older") else '<span class="badge b-older">以前から営業？</span>') + \
             ("" if not s.get("warn") else f'<span class="badge b-warn">⚠ {e(s["warn"])}（未確認）</span>')
    return f"""<li class="sitem{' older' if s.get('older') else ''}" id="s-{e(s['id'])}">
  <div class="ico" style="background:{g['color']}1f" aria-hidden="true">{g['icon']}</div>
  <div class="sbody"><h3>{badges}{e(s['name'])}</h3>
    <p class="meta">{e(g['label'])}{('・' + e(s['gyotai'])) if s.get('gyotai') else ''}・{fmt(s['permitDate'])}許可</p>
    <p class="addr">{e(s['address'])} <a href="{e(gmap)}" target="_blank" rel="noopener">地図</a></p>
    {f'<div class="slinks">{lk}</div>' if lk else ''}</div></li>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", action="store_true", help="検索エンジンに載せる（本公開）")
    args = ap.parse_args()
    noindex = not args.index

    data = json.loads((SITE / "data" / "shops.json").read_text("utf-8"))
    leak = sorted({k for s in data["shops"] for k in s if k in PRIVATE_KEYS})
    if leak:
        raise SystemExit(f"公開してはいけない項目が入っています: {leak}")
    ar = json.loads((SITE / "data" / "areas.json").read_text("utf-8"))
    areas, minutes = ar["areas"], ar["minutes"]
    for a in areas:
        a["slug"] = SLUG[a["name"]]
    idx = {a["name"]: i for i, a in enumerate(areas)}
    genre = {g["id"]: g for g in data["genres"]}
    shops = data["shops"]
    by_area: dict[str, list] = {a["name"]: [] for a in areas}
    for s in shops:
        by_area[s["area"]].append(s)
    meal = lambda name: [s for s in by_area[name] if s["genre"] != "bar"]  # noqa: E731
    fresh = lambda name: [s for s in meal(name) if not s.get("older")]  # noqa: E731
    gen = data["generatedAt"][:10]

    if PUB.exists():
        shutil.rmtree(PUB)
    PUB.mkdir()
    for f in ("style.css", "config.js", "app.js"):
        shutil.copy(SITE / f, PUB / f)
    (PUB / "data").mkdir()
    shutil.copy(SITE / "data" / "shops.json", PUB / "data" / "shops.json")
    (PUB / "data" / "areas.json").write_text(json.dumps({**ar, "areas": areas}, ensure_ascii=False, separators=(",", ":")), "utf-8")
    urls = []

    def write(path: str, text: str, prio: str):
        out = PUB / path / "index.html" if path else PUB / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, "utf-8")
        urls.append((SITE_URL + path, prio))

    # ---- まんなかペア（人口3万人以上どうし、車で30分以上離れている組み合わせ）
    big = [a for a in sorted(areas, key=lambda a: -a["pop"]) if a["pop"] >= PAIR_MIN_POP]
    pairs = []
    for a, b in combinations(big, 2):
        if minutes[idx[a["name"]]][idx[b["name"]]] < PAIR_MIN_MINUTES:
            continue
        cands = []
        for j, c in enumerate(areas):
            t = [minutes[idx[a["name"]]][j], minutes[idx[b["name"]]][j]]
            if len(meal(c["name"])) >= 3:
                cands.append((max(t) // 10, -len(fresh(c["name"])), -len(meal(c["name"])), sum(t), c, t))
        cands.sort(key=lambda x: x[:4])
        pairs.append((a, b, [(c, t) for *_, c, t in cands[:3]]))

    # ---- トップ
    pop_pairs = sorted(pairs, key=lambda p: -(p[0]["pop"] * p[1]["pop"]))[:12]
    city_links = "".join(f'<li><a href="city/{a["slug"]}/">{e(a["name"])}<span>{len(fresh(a["name"]))}店</span></a></li>'
                         for a in sorted(areas, key=lambda a: -a["pop"]))
    top_body = f"""<main class="wrap home">
<section class="hero">
  <svg class="hero-art" viewBox="0 0 360 220" aria-hidden="true">
    <path class="route r1" d="M28 46 C 96 64, 130 96, 180 118"/><path class="route r2" d="M338 34 C 286 70, 236 92, 180 118"/><path class="route r3" d="M300 204 C 262 170, 214 140, 180 118"/>
    <circle class="pin p1" cx="28" cy="46" r="9"/><circle class="pin p2" cx="338" cy="34" r="9"/><circle class="pin p3" cx="300" cy="204" r="9"/>
    <circle class="halo" cx="180" cy="118" r="30"/><circle class="meet" cx="180" cy="118" r="15"/>
  </svg>
  <h1><span class="nb">離れて暮らす友だちと、</span><span class="nb">ちょうど真ん中の</span><span class="nb">新しいお店で。</span></h1>
  <p class="hero-lead">住んでいる市町を選ぶだけ。全員の車の移動時間がなるべく揃う街と、そこで開店3年以内のお店を見つけます。北海道52市町に対応。</p>
</section>
{SEARCH_FORM}
<section class="howto" id="howto">
  <h2 class="sec-title">使い方</h2>
  <ol class="steps"><li><b>住んでいる市町を選ぶ</b><span>2〜4人まで。📍で現在地から選べます。</span></li>
  <li><b>まんなかの街がわかる</b><span>一番遠い人の時間が短く、新しいお店が多い街を3つ提案します。</span></li>
  <li><b>新しいお店を選んで会う</b><span>Instagram・公式サイト・食べログで、お店の雰囲気を確かめられます。</span></li></ol>
</section>
<section id="pairs">
  <h2 class="sec-title">よく調べられる組み合わせ</h2>
  <ul class="pairlist">{''.join(f'<li><a href="mannaka/{a["slug"]}-{b["slug"]}/">{e(a["name"])}と{e(b["name"])}のまんなか</a></li>' for a, b, _ in pop_pairs)}</ul>
</section>
<section id="cities">
  <h2 class="sec-title">市町から新店を探す</h2>
  <ul class="citylist">{city_links}</ul>
</section>
</main>"""
    write("", page(rel="./", path="", title=f"{BRAND}｜離れて住む2〜4人の中間地点で新しいお店を探す",
                   desc="北海道52市町の開店3年以内のお店から、2〜4人の車での移動時間がなるべく揃う「まんなか」の市町と新店を提案します。札幌・旭川・函館・帯広・釧路・北見など。",
                   body=top_body, noindex=noindex, app=True,
                   jsonld=[{"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": SITE_URL, "inLanguage": "ja"}]), "1.0")

    # ---- 市町の一覧ページ
    city_links_sub = city_links.replace('href="city/', 'href="')
    write("city", page(rel="../", path="city/", title=f"市町から新店を探す｜{BRAND}",
                       desc="北海道52市町それぞれの、開店3年以内の新しいお店の一覧です。",
                       body=f'<main class="wrap"><nav class="crumbs"><a href="../">トップ</a> › 市町から探す</nav><h1>市町から新店を探す</h1><ul class="citylist">{city_links_sub}</ul></main>',
                       noindex=noindex, jsonld=[]), "0.6")

    # ---- 市町ページ
    for a in areas:
        name, slug = a["name"], a["slug"]
        new = sorted([s for s in by_area[name] if not s.get("older")], key=lambda s: s["permitDate"], reverse=True)
        old = sorted([s for s in by_area[name] if s.get("older")], key=lambda s: s["permitDate"], reverse=True)
        gcount = {}
        for s in new:
            gcount[s["genre"]] = gcount.get(s["genre"], 0) + 1
        gsum = "・".join(f'{genre[g]["label"]} {n}店' for g, n in sorted(gcount.items(), key=lambda x: -x[1])[:4])
        mypairs = [p for p in pairs if name in (p[0]["name"], p[1]["name"])][:8]
        near = sorted(areas, key=lambda b: minutes[idx[name]][idx[b["name"]]])[1:7]
        body = f"""<main class="wrap">
<nav class="crumbs"><a href="../../">トップ</a> › <a href="../">市町から探す</a> › {e(name)}</nav>
<h1>{e(name)}の新しいお店（開店3年以内）</h1>
<p class="lead">{e(name)}で営業許可から3年以内のお店は <b>{len(new)}店</b>{f'（{e(gsum)}）' if gsum else ''}です。{f'ほかに、以前から営業している可能性のあるお店が{len(old)}店あります。' if old else ''}（{gen}時点）</p>
<div class="cta"><a class="btn main" href="../../?p={e(name)}">{e(name)}を含めて、まんなかを探す</a></div>
{f'<section><h2 class="sec-title">{e(name)}からのまんなか</h2><ul class="pairlist">' + ''.join(f'<li><a href="../../mannaka/{p[0]["slug"]}-{p[1]["slug"]}/">{e(p[0]["name"])}と{e(p[1]["name"])}のまんなか</a></li>' for p in mypairs) + '</ul></section>' if mypairs else ''}
<section><h2 class="sec-title">新しいお店（許可日の新しい順）</h2>
<ul class="slist">{''.join(shop_li(s, genre) for s in new) or '<li class="note">まだありません。</li>'}</ul></section>
{f'<section><h2 class="sec-title">以前から営業している可能性のあるお店</h2><p class="note">営業許可を取り直したお店（経営者の交代・移転・改装など）の可能性があります。食べログの掲載時期などから自動で推定しています。</p><ul class="slist">' + ''.join(shop_li(s, genre) for s in old) + '</ul></section>' if old else ''}
<section><h2 class="sec-title">近くの市町</h2><ul class="citylist">{''.join(f'<li><a href="../{b["slug"]}/">{e(b["name"])}<span>車で{hm(minutes[idx[name]][idx[b["name"]]])}</span></a></li>' for b in near)}</ul></section>
</main>"""
        items = [{"@type": "ListItem", "position": i + 1, "item": {"@type": "FoodEstablishment", "name": s["name"], "address": s["address"]}}
                 for i, s in enumerate(new[:50])]
        write(f"city/{slug}/", page(
            rel="../../", path=f"city/{slug}/", title=f"{name}の新しいお店・新店一覧（開店3年以内）｜{BRAND}",
            desc=f"{name}の開店3年以内の新しいお店{len(new)}店の一覧。{gsum}。Instagram・公式サイト・食べログへのリンクつき（{gen}更新）。",
            body=body, noindex=noindex, jsonld=[
                {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "トップ", "item": SITE_URL},
                    {"@type": "ListItem", "position": 2, "name": "市町から探す", "item": SITE_URL + "city/"},
                    {"@type": "ListItem", "position": 3, "name": name, "item": SITE_URL + f"city/{slug}/"}]},
                {"@context": "https://schema.org", "@type": "ItemList", "name": f"{name}の新しいお店", "itemListElement": items}]), "0.8")

    # ---- まんなかページ
    for a, b, top in pairs:
        t_ab = minutes[idx[a["name"]]][idx[b["name"]]]
        rows = "".join(f"""<li class="cand static"><h3><span><span class="rank">{i + 1}</span>{e(c["name"])}</span><small>新店{len(fresh(c["name"]))}店</small></h3>
  <p class="times"><span class="time">{e(a["name"])}から {('地元' if t[0] == 0 else hm(t[0]))}</span><span class="time">{e(b["name"])}から {('地元' if t[1] == 0 else hm(t[1]))}</span></p>
  <p class="note"><a href="../../city/{c["slug"]}/">{e(c["name"])}の新店一覧を見る</a></p></li>""" for i, (c, t) in enumerate(top))
        first = top[0][0]["name"] if top else ""
        body = f"""<main class="wrap">
<nav class="crumbs"><a href="../../">トップ</a> › {e(a["name"])}と{e(b["name"])}のまんなか</nav>
<h1>{e(a["name"])}と{e(b["name"])}のまんなかで、新しいお店を探す</h1>
<p class="lead">{e(a["name"])}と{e(b["name"])}は車で約{hm(t_ab)}。2人の移動時間がなるべく揃い、新しいお店が多いのは「{e(first)}」です。3人以上のときは、下の検索に市町を足してください。</p>
<ol class="cands">{rows}</ol>
{SEARCH_FORM}
</main>"""
        write(f"mannaka/{a['slug']}-{b['slug']}/", page(
            rel="../../", path=f"mannaka/{a['slug']}-{b['slug']}/",
            title=f"{a['name']}と{b['name']}のまんなか｜中間地点の新しいお店｜{BRAND}",
            desc=f"{a['name']}と{b['name']}（車で約{hm(t_ab)}）の中間地点で会うなら{first}。車の移動時間がなるべく揃う市町と、開店3年以内の新店を提案します。",
            body=body, noindex=noindex, app=True, people=[a["name"], b["name"]], jsonld=[
                {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "トップ", "item": SITE_URL},
                    {"@type": "ListItem", "position": 2, "name": f"{a['name']}と{b['name']}のまんなか", "item": SITE_URL + f"mannaka/{a['slug']}-{b['slug']}/"}]}]), "0.5")

    # ---- sitemap / robots / 404
    today = dt.date.today().isoformat()
    (PUB / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
                                     "".join(f"<url><loc>{e(u)}</loc><lastmod>{today}</lastmod><priority>{p}</priority></url>\n" for u, p in urls) +
                                     "</urlset>\n", "utf-8")
    (PUB / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n", "utf-8")
    (PUB / "404.html").write_text(page(rel=SITE_URL, path="404.html", title=f"ページが見つかりません｜{BRAND}", desc="",
                                       body='<main class="wrap"><h1>ページが見つかりません</h1><p><a href="' + SITE_URL + '">トップへ戻る</a></p></main>',
                                       noindex=True, jsonld=[]), "utf-8")
    (PUB / ".nojekyll").write_text("", "utf-8")
    print(f"public/ を作りました：{len(urls)}ページ（市町{len(areas)}・まんなか{len(pairs)}）{'・noindex（PoC）' if noindex else '・検索エンジンに公開'}")


if __name__ == "__main__":
    main()
