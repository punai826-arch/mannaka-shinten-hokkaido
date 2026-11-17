"""新店と「Instagram・公式サイト・食べログ」のリンクを紐づける候補を作る（Claude不要・無料枠で動く版）

方針：サイトに出すのは「文字」と「リンク先URL」だけ。写真・画像・他サイトの文章（口コミや説明文）は
取得も表示もしない（著作権に触れるおそれがあるため）。

しくみ
  1. pipeline/out/link_input.json（build_hokkaido.py が作る）から、まだ調べていないお店を新しい順に選ぶ
  2. Tavily（ウェブ検索API・無料枠 月1,000クレジット）で「店名＋市町」を検索する
  3. 検索で出てきた公式サイトらしいページを1〜3件だけ開き、電話番号・住所・SNSリンクが載っているかを確かめる
     （Instagram・食べログ等のサイトそのものは開かない。規約で自動取得が禁止されているため）
  4. Gemini（無料枠）が、許可データの店名・市町・住所・電話番号と照らし合わせて判定する
  5. 結果を pipeline/linker/auto_links.json に保存 → サイトに「自動照合・確度」の表示付きで出る（承認は不要）
     確度「不明」のリンクは出さない。同じ内容を確認用に pipeline/out/link_candidates_日付.csv にも書く

使い方
  python pipeline/linker/link_shops.py --limit 50
  オプション: --include-bar（居酒屋・バーも対象）
             --area 釧路市（市町を絞る） --retry-unknown（前回「見つからない」だった店も再調査）

APIキーは pipeline/linker/keys.txt に書く（keys.example.txt をコピー）。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
INPUT = ROOT / "pipeline" / "out" / "link_input.json"
OUT_DIR = ROOT / "pipeline" / "out"
STATE = HERE / "state.json"
AUTO = HERE / "auto_links.json"   # 承認なしでサイトに出す自動紐づけの結果（build_hokkaido.py が読む）
KEYS = HERE / "keys.txt"

UA = "Mozilla/5.0 (compatible; shinten-map-linker/1.0; +https://github.com/)"
DEFAULT_MODELS = "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash"

# 公式サイトとしては扱わないドメイン（口コミ・予約・地図・SNS・ニュースなど）
PORTALS = re.compile(r"(tabelog\.com|hotpepper\.jp|retty\.me|gnavi\.co\.jp|google\.|goo\.gl|instagram\.com|"
                     r"facebook\.com|fb\.com|(//|\.)x\.com|twitter\.com|tiktok\.com|youtube\.com|line\.me|"
                     r"hamoni\.jp|tripadvisor|yelp\.|jalan\.net|rakuten\.|ikyu\.com|mapion|navitime|itp\.ne\.jp|"
                     r"ekiten\.jp|yahoo\.co\.jp|tabelog|hokkaido-np\.co\.jp|doshin|nikkei|asahi\.com|"
                     r"yomiuri|mainichi|wikipedia|amazon\.|minkou|townwork|indeed|baitoru|mynavi|"
                     r"en-gage\.net|jobs?\.|wantedly|smartnews|ameblo\.jp/.+/entry|note\.com/.+/n/|"
                     # 実データで公式サイトと誤判定したもの（2026-11-17）：ダーツ店検索・個人ブログ・地域の店紹介サイト
                     r"dartslive\.com|foodplace\.jp|mypl\.net|mombero\.net|fc2\.com|blog-entry-|livedoor\.(jp|blog)|"
                     r"hatenablog\.com/entry|kanko|kankou|tourism|visit-|navi\.jp|gourmet\.|hitosara|favy|ubereats|"
                     r"demae-can|epark|gurunavi|mapfan|jorudan|walkerplus|jalan|asoview|bing\.com|"
                     r"menu\.(?:hokkaido|jp)|town\.|machi-|machinavi|ekiten|mylove|coupon|/archives/|/blog/|/article|/news/)", re.I)
# 北海道の食べログ店舗ページは「/hokkaido/A0101/A010101/1000001/」のように番号が7桁（都府県は8桁）
TABELOG_RE = re.compile(r"(?:https?://)?(?:s\.)?tabelog\.com/hokkaido/A\d{4}/A\d{6}/\d{7,8}(?=[/?#\s\"'<]|$)", re.I)
IG_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]{1,30})(?=[/?#\"'\s<]|$)", re.I)
IG_NOT_USER = {"p", "reel", "reels", "explore", "stories", "accounts", "tv", "tags", "direct", "about",
               "developer", "legal", "web", "share", "s", "invites", "privacy"}
SNS_RE = re.compile(r"https?://(?:www\.)?(?:facebook\.com|x\.com|twitter\.com|tiktok\.com)/[^\s\"'<>)]+", re.I)
COMPANY_RE = re.compile(r"株式会社|有限会社|合同会社|合資会社|一般社団|社団法人|財団法人|ＮＰＯ|NPO|協同組合|\(株\)|（株）|\(有\)|（有）")


# ---------------------------------------------------------------- 設定・状態
def load_keys() -> dict:
    keys = {k: v for k, v in os.environ.items() if k in ("GEMINI_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "GEMINI_MODELS") and v}
    if KEYS.exists():
        for line in KEYS.read_text("utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    keys[k.strip()] = v.strip()
    return keys


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text("utf-8"))
    return {"shops": {}, "usage": {}}


def save_state(st: dict):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(STATE)


class QuotaOver(Exception):
    pass


# ---------------------------------------------------------------- 通信
def http(url, data=None, headers=None, timeout=25, limit=600_000):
    h = {"User-Agent": UA, **(headers or {})}
    body = json.dumps(data).encode() if isinstance(data, (dict, list)) else data
    if isinstance(data, (dict, list)):
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit), r.headers.get("Content-Type", ""), r.geturl()


class Tavily:
    name = "tavily"

    def __init__(self, key, st, month, cap):
        self.key, self.st, self.month, self.cap = key, st, month, cap

    def used(self):
        return self.st["usage"].get(self.month, {}).get("tavily", 0)

    def search(self, query, max_results=8, domains=None):
        if self.used() >= self.cap:
            raise QuotaOver(f"今月の検索上限（{self.cap}回）に達しました")
        try:
            raw, _, _ = http("https://api.tavily.com/search",
                             {"query": query, "search_depth": "basic", "max_results": max_results,
                              "include_answer": False, "include_images": False,
                              **({"include_domains": domains} if domains else {})},
                             {"Authorization": f"Bearer {self.key}"})
        except urllib.error.HTTPError as e:
            body = e.read(500).decode("utf-8", "replace")
            if e.code in (401, 403):
                raise QuotaOver(f"TavilyのAPIキーが受け付けられませんでした（HTTP {e.code}）。keys.txt の TAVILY_API_KEY を確認してください。{body[:200]}")
            if e.code in (429, 432, 433):
                raise QuotaOver(f"Tavilyの無料枠を使い切りました（HTTP {e.code}）")
            raise RuntimeError(f"Tavily HTTP {e.code}: {body[:200]}")
        u = self.st["usage"].setdefault(self.month, {})
        u["tavily"] = u.get("tavily", 0) + 1
        return json.loads(raw).get("results", [])


class Exa:
    """Exa（無料：毎月10ドル分のクレジット。1回あたり約0.007ドル）"""
    name = "exa"

    def __init__(self, key, st, month, cap):
        self.key, self.st, self.month, self.cap = key, st, month, cap

    def used(self):
        return self.st["usage"].get(self.month, {}).get("exa", 0)

    def search(self, query, max_results=8, domains=None):
        if self.used() >= self.cap:
            raise QuotaOver(f"Exaの今月の上限（{self.cap}回）に達しました")
        try:
            raw, _, _ = http("https://api.exa.ai/search",
                             {"query": query, "numResults": max_results, "type": "auto",
                              **({"includeDomains": domains} if domains else {})},
                             {"x-api-key": self.key})
        except urllib.error.HTTPError as e:
            body = e.read(500).decode("utf-8", "replace")
            if e.code in (401, 403):
                raise QuotaOver(f"ExaのAPIキーが受け付けられませんでした（HTTP {e.code}）。{body[:200]}")
            if e.code in (402, 429):
                raise QuotaOver(f"Exaの無料クレジットを使い切りました（HTTP {e.code}）")
            raise RuntimeError(f"Exa HTTP {e.code}: {body[:200]}")
        u = self.st["usage"].setdefault(self.month, {})
        u["exa"] = u.get("exa", 0) + 1
        return [{"title": r.get("title") or "", "url": r.get("url") or "", "content": (r.get("text") or r.get("summary") or "")[:300]}
                for r in json.loads(raw).get("results", [])]


class SearchPool:
    """複数の無料検索を、今月の残りが多い順に使う。1つが上限に達したら次へ"""

    def __init__(self, providers):
        self.providers = [p for p in providers if p]
        self.dead = set()

    def used(self):
        return sum(p.used() for p in self.providers)

    def cap(self):
        return sum(p.cap for p in self.providers)

    def search(self, query, max_results=8, domains=None):
        for p in sorted(self.providers, key=lambda p: p.used() - p.cap):
            if p.name in self.dead:
                continue
            try:
                return p.search(query, max_results, domains)
            except QuotaOver as e:
                print(f"\n  ・{e}。ほかの検索に切り替えます", end=" ")
                self.dead.add(p.name)
        raise QuotaOver("今月の無料の検索をすべて使い切りました。来月また続きから再開します")


class Osm:
    """OpenStreetMap に登録された飲食店の公式サイト・Instagram（無料。1回の実行で1度だけ取得）"""
    URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
    CACHE = ROOT / "pipeline" / "out" / "osm_food.json"

    def __init__(self):
        self.items = []
        try:
            if self.CACHE.exists() and time.time() - self.CACHE.stat().st_mtime < 86400 * 7:
                self.items = json.loads(self.CACHE.read_text("utf-8"))
            else:
                self.items = self._download()
                self.CACHE.parent.mkdir(parents=True, exist_ok=True)
                self.CACHE.write_text(json.dumps(self.items, ensure_ascii=False), "utf-8")
            print(f"OpenStreetMap：公式サイトかInstagramが登録された北海道の飲食店 {len(self.items):,}件")
        except Exception as e:  # noqa: BLE001  取れなくても検索だけで続ける
            print(f"OpenStreetMapを取得できませんでした（検索だけで続けます）：{str(e)[:100]}")

    def _download(self):
        sel = ['["amenity"~"^(restaurant|cafe|bar|pub|fast_food|izakaya|ice_cream|food_court|biergarten)$"]',
               '["shop"~"^(bakery|confectionery|pastry|coffee|tea|deli)$"]']
        tags = ["website", "contact:website", "url", "contact:instagram", "instagram"]
        body = "".join(f"nwr(area.a){s_}[\"{t}\"];" for s_ in sel for t in tags)
        q = f'[out:json][timeout:180];area["name"="北海道"]["admin_level"="4"]->.a;({body});out center tags;'
        last = None
        for u in self.URLS:
            try:
                raw, _, _ = http(u, urllib.parse.urlencode({"data": q}).encode(), {"Content-Type": "application/x-www-form-urlencoded"},
                                 timeout=200, limit=60_000_000)
                out = []
                for el in json.loads(raw).get("elements", []):
                    t = el.get("tags", {})
                    lat, lon = el.get("lat") or el.get("center", {}).get("lat"), el.get("lon") or el.get("center", {}).get("lon")
                    ig = t.get("contact:instagram") or t.get("instagram") or ""
                    web = t.get("website") or t.get("contact:website") or t.get("url") or ""
                    if (ig or web) and t.get("name"):
                        out.append({"name": t["name"], "lat": lat, "lng": lon, "web": web, "ig": ig,
                                    "url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}"})
                return out
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(last)

    def match(self, shop):
        if not self.items:
            return None
        n = norm_name(shop["name"])
        best = None
        for it in self.items:
            m = norm_name(it["name"])
            if not (n and m and (n in m or m in n)):
                continue
            if shop.get("lat") and it.get("lat"):
                d = ((shop["lat"] - it["lat"]) * 111000) ** 2 + ((shop["lng"] - it["lng"]) * 81000) ** 2
                if d > 300 ** 2:
                    continue
                if not best or d < best[0]:
                    best = (d, it)
        return best[1] if best else None


class Gemini:
    def __init__(self, key, models, st, month, pause):
        self.key, self.models, self.st, self.month, self.pause = key, list(models), st, month, pause
        self.last = 0.0

    def ask(self, parts, retries=3):
        while self.models:
            model = self.models[0]
            for attempt in range(retries):
                wait = self.pause - (time.time() - self.last)
                if wait > 0:
                    time.sleep(wait)
                self.last = time.time()
                try:
                    raw, _, _ = http(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                     {"contents": [{"role": "user", "parts": parts}],
                                      "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}},
                                     {"x-goog-api-key": self.key}, timeout=60)
                    u = self.st["usage"].setdefault(self.month, {})
                    u["gemini"] = u.get("gemini", 0) + 1
                    res = json.loads(raw)
                    text = "".join(p.get("text", "") for c in res.get("candidates", [])[:1]
                                   for p in c.get("content", {}).get("parts", []))
                    return parse_json(text)
                except urllib.error.HTTPError as e:
                    msg = e.read(4000).decode("utf-8", "replace")
                    if e.code == 429 and re.search(r"per ?day|PerDay|daily", msg, re.I):
                        print(f"  ・{model} は今日の無料枠を使い切りました。次のモデルに切り替えます")
                        break
                    if e.code in (404, 400) and "model" in msg.lower() and "not" in msg.lower():
                        print(f"  ・{model} は使えないモデル名でした。次のモデルに切り替えます")
                        break
                    if e.code in (401, 403) or (e.code == 400 and "API key" in msg):
                        raise QuotaOver(f"GeminiのAPIキーが受け付けられませんでした（HTTP {e.code}）。keys.txt の GEMINI_API_KEY を確認してください。{msg[:200]}")
                    if e.code in (429, 500, 502, 503, 504):
                        m = re.search(r'"retryDelay":\s*"(\d+)', msg)
                        time.sleep(int(m.group(1)) + 1 if m else 20 * (attempt + 1))
                        continue
                    raise RuntimeError(f"Gemini HTTP {e.code}: {msg[:300]}")
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(5 * (attempt + 1))
                    continue
            else:
                raise RuntimeError(f"Geminiの応答がありませんでした（{model}）")
            self.models.pop(0)
        raise QuotaOver("Geminiの今日の無料枠をすべて使い切りました。明日また実行すると続きから再開します")


def parse_json(text: str):
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------- 照合用の小道具
def digits(s):
    return re.sub(r"\D", "", s or "")


def zen2han(s):
    return (s or "").translate(str.maketrans("０１２３４５６７８９－ー", "0123456789--"))


def addr_key(addr):
    """「北海道釧路市末広町5丁目13番地 …」→ 「末広町5」のような照合キー"""
    a = zen2han(re.sub(r"^北海道", "", addr or ""))
    a = re.sub(r"^[^\s]{1,4}?郡", "", a)
    m = re.search(r"(?:市|町|村)(.+?\d+)", a)
    return re.sub(r"\s", "", m.group(1)) if m else ""


def ig_handles(text):
    return {h.lower().rstrip(".") for h in IG_RE.findall(text or "") if h.lower() not in IG_NOT_USER}


def domain(url):
    return urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")


def read_page(url):
    """公式サイト候補を1ページだけ読む。返すのは判定に必要な要点だけ"""
    try:
        raw, ctype, final = http(url, headers={"Accept-Language": "ja"}, timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": str(e)[:80]}
    if "html" not in ctype.lower():
        return {"url": url, "error": f"HTMLではない（{ctype}）"}
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:3000])
    enc = (m.group(1).decode() if m else None) or ("utf-8" if "utf-8" in ctype.lower() else "utf-8")
    try:
        doc = raw.decode(enc, "replace")
    except LookupError:
        doc = raw.decode("utf-8", "replace")

    def meta(prop):
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]*content=["\']([^"\']*)', doc, re.I) or \
            re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{prop}["\']', doc, re.I)
        return html.unescape(m.group(1)).strip() if m else ""

    title = re.search(r"<title[^>]*>(.*?)</title>", doc, re.I | re.S)
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", doc, flags=re.I | re.S)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    return {"url": final, "title": html.unescape(title.group(1)).strip()[:120] if title else "",
            "siteName": meta("og:site_name")[:60], "instagram": sorted(ig_handles(doc))[:5],
            "sns": sorted(set(SNS_RE.findall(doc)))[:5], "text": text[:1200], "_text_full": text[:20000]}


# ---------------------------------------------------------------- 1店分の処理
def gather(shop, tavily, osm=None):
    name, area = shop["name"], shop["area"]
    hits, handles, first_pages = [], set(), []
    o = osm.match(shop) if osm else None
    if o:  # OpenStreetMap に同じ名前・300m以内で登録があれば、そのリンクを材料に入れる
        ig = o["ig"].strip()
        ig_text = ig if "instagram.com" in ig else (f"instagram.com/{ig.lstrip('@')}" if ig else "")
        hits.append({"title": f"OpenStreetMap登録：{o['name']}（同じ場所）", "url": o["url"],
                     "content": f"公式サイト: {o['web']} {ig_text}".strip()})
        if o["web"].startswith("http") and not PORTALS.search(o["web"]):
            first_pages.append(o["web"])
    hits += tavily.search(f"{name} {area} 北海道")
    for h in hits:
        handles |= ig_handles(h.get("url", "") + " " + h.get("content", ""))
    if not handles:  # Instagramが見つからないときだけ、もう1回
        more = tavily.search(f"{name} {area} instagram", max_results=6)
        seen = {h["url"] for h in hits}
        hits += [h for h in more if h.get("url") not in seen]

    if not tabelog_urls(hits):  # 食べログが出てこなければ、食べログの中だけを1回検索
        seen = {h["url"] for h in hits}
        hits += [h for h in tavily.search(f"{name} {area}", max_results=5, domains=["tabelog.com"]) if h.get("url") not in seen]

    # 公式サイト候補：ポータル以外で、店名か市町が載っているもの（最大3件）
    pages, tel, akey = [], digits(shop.get("tel")), addr_key(shop.get("address"))
    cands = first_pages + [h["url"] for h in hits if h.get("url", "").startswith("http") and not PORTALS.search(h["url"]) and "openstreetmap.org" not in h["url"]]
    for url in list(dict.fromkeys(cands))[:3]:
        p = read_page(url)
        if p.get("error"):
            pages.append(p)
            continue
        full = zen2han(p.pop("_text_full"))
        p["電話番号が一致"] = bool(tel) and tel in digits(full)
        p["住所が一致"] = bool(akey) and akey in re.sub(r"\s", "", full)
        p["店名が載っている"] = norm_name(name) in norm_name(full)
        p["市町が載っている"] = area in full
        pages.append(p)
        time.sleep(1)  # 相手のサイトに負担をかけない
    for p in pages:
        handles |= set(p.get("instagram", []))
    return hits, pages, handles


def norm_name(s):
    import unicodedata
    return re.sub(r"[\s・･\-ー－'’\"]", "", unicodedata.normalize("NFKC", s or "")).lower()


JUDGE_PROMPT = """あなたは飲食店データの照合係です。下の「お店（営業許可データ）」と同じお店の、
(1) 公式Instagramアカウント、(2) 公式ウェブサイト、(3) 食べログのお店ページ を、「材料」の中からだけ選んでください。

大事なルール
- 材料に出てこないアカウントやURLを作ってはいけません。見つからなければ空欄にして確度「不明」。
- お客さんの投稿・まとめサイト・グルメサイトの紹介ページは「公式」ではありません。ハッシュタグ付きの来店投稿のアカウントも違います。
- 同じ名前の別の店（別の市町、チェーンの他店舗）に注意。北海道{area}のお店かどうかを必ず確かめます。
- 確度の決め方：
  「確実」= 電話番号か住所が一致、または確かな公式サイトがそのInstagramへリンクしている
  「おそらく」= 店名と市町が合い、ほかに食い違いがない
  「不明」= 決め手がない、または候補がない
- 食べログは、材料の「食べログURLの候補」からだけ選び、店名と市町が合うものにします。
- 移転（住所が違う既存店）、閉店、同名の別店の疑いがあれば status に書きます。
- 開店日やオープン時期が材料に書かれていれば opening_hint に短く書きます。

お店（営業許可データ）
{shop}

材料：Instagramアカウントの候補（検索結果や公式サイトに出てきたもの）
{handles}

材料：食べログURLの候補
{tabelog}

材料：検索結果（タイトル・URL・抜粋）
{hits}

材料：公式サイト候補のページを読んだ結果
{pages}

次のJSONだけを返してください。
{{"instagram":{{"handle":"","confidence":"確実|おそらく|不明","evidence_url":"","reason":"30字以内"}},
 "website":{{"url":"","confidence":"確実|おそらく|不明","reason":"30字以内"}},
 "other_sns":[""],
 "tabelog":{{"url":"","confidence":"確実|おそらく|不明","reason":"30字以内"}},
 "status":{{"flag":"なし|移転の疑い|閉店の疑い|同名の別店の疑い","reason":""}},
 "opening_hint":""}}"""

def tabelog_norm(url):
    """s.tabelog.com や http:// の違いをそろえて https://tabelog.com/…/1234567/ にする"""
    return "https://" + re.sub(r"^(?:https?://)?(?:s\.)?", "", url).rstrip("/") + "/"


def tabelog_urls(hits):
    return sorted({tabelog_norm(m.group(0))
                   for h in hits for m in TABELOG_RE.finditer(h.get("url", "") + " " + (h.get("content") or ""))})


def judge(shop, hits, pages, handles, gemini):
    facts = {"店名": shop["name"], "フリガナ": shop.get("kana"), "住所": shop["address"], "市町": shop["area"],
             "電話番号": shop.get("tel") or "（非公開）", "業態": shop.get("gyotai") or "",
             "営業許可日": shop["permitDate"]}
    if shop.get("corp") and COMPANY_RE.search(shop["corp"]):
        facts["運営会社"] = shop["corp"]  # 個人名は送らない
    slim_hits = [{"title": h.get("title", "")[:80], "url": h.get("url"), "抜粋": (h.get("content") or "")[:300]} for h in hits[:12]]
    prompt = JUDGE_PROMPT.format(area=shop["area"], shop=json.dumps(facts, ensure_ascii=False),
                                 handles=json.dumps(sorted(handles), ensure_ascii=False),
                                 tabelog=json.dumps(tabelog_urls(hits), ensure_ascii=False),
                                 hits=json.dumps(slim_hits, ensure_ascii=False),
                                 pages=json.dumps(pages, ensure_ascii=False))
    return gemini.ask([{"text": prompt}])


def validate(res, hits, pages, handles):
    """Geminiの答えを、材料に実在するものだけに絞る（作り話の混入を防ぐ）"""
    ig = res.get("instagram") or {}
    h = (ig.get("handle") or "").lstrip("@").lower().strip()
    if h and h not in handles:
        ig = {"handle": "", "confidence": "不明", "evidence_url": "", "reason": f"材料にない候補（{h}）を除外"}
    elif not h:
        ig["confidence"] = "不明"
    ig["handle"] = h if h in handles else ""

    urls = {p["url"] for p in pages if not p.get("error")} | {x.get("url") for x in hits} | \
        {w for x in hits for w in re.findall(r"https?://[^\s]+", x.get("content") or "")}
    web = res.get("website") or {}
    if web.get("url") and web["url"] not in urls and not any(domain(web["url"]) == domain(u) for u in urls if u):
        web = {"url": "", "confidence": "不明", "reason": "材料にないURLを除外"}
    if not web.get("url"):
        web["confidence"] = "不明"
    elif PORTALS.search(web["url"]):
        web = {"url": "", "confidence": "不明", "reason": "グルメサイト等は公式サイトとしない"}

    tb = res.get("tabelog") or {}
    m = TABELOG_RE.match((tb.get("url") or "").strip())
    tb_url = tabelog_norm(m.group(0)) if m else ""
    if tb_url not in tabelog_urls(hits):
        tb = {"url": "", "confidence": "不明", "reason": "材料にないURLを除外" if tb_url else tb.get("reason", "")}
    else:
        tb["url"] = tb_url
    res.update(instagram=ig, website=web, tabelog=tb)
    return res


# ---------------------------------------------------------------- 出力
COLUMNS = ["承認", "id", "店名", "市町", "住所", "許可日",
           "instagram", "ig確度", "ig根拠URL", "ig理由",
           "公式サイト", "サイト確度", "サイト理由", "食べログ", "食べログ確度", "他SNS",
           "注意", "注意の理由", "開店日ヒント", "調べた日"]


def row_for(shop, res):
    ig, web, tb, stt = res.get("instagram", {}), res.get("website", {}), res.get("tabelog", {}), res.get("status", {})
    return {"承認": "", "id": shop["id"], "店名": shop["name"], "市町": shop["area"],
            "住所": shop["address"], "許可日": shop["permitDate"],
            "instagram": ig.get("handle", ""), "ig確度": ig.get("confidence", "不明"),
            "ig根拠URL": ig.get("evidence_url", ""), "ig理由": ig.get("reason", ""),
            "公式サイト": web.get("url", ""), "サイト確度": web.get("confidence", "不明"), "サイト理由": web.get("reason", ""),
            "他SNS": " ".join(x for x in res.get("other_sns", []) if x)[:300],
            "食べログ": tb.get("url", ""), "食べログ確度": tb.get("confidence", "不明"),
            "注意": "" if stt.get("flag") in (None, "", "なし") else stt["flag"], "注意の理由": stt.get("reason", ""),
            "開店日ヒント": res.get("opening_hint", ""), "調べた日": dt.date.today().isoformat()}


def tabelog_match(shop, hits):
    """食べログの検索結果から、Geminiを使わずに同じ店のページを選ぶ（店名がタイトルにあり、市町か住所が合うもの）"""
    name, akey = norm_name(shop["name"]), addr_key(shop.get("address"))
    best = None
    for h in hits:
        urls = tabelog_urls([h])
        if not urls:
            continue
        title, body = norm_name(h.get("title", "")), zen2han(h.get("content") or "")
        if name and name in title:
            if akey and akey in re.sub(r"\s", "", body):
                return urls[0], "確実"
            if shop["area"] in (h.get("content") or "") + h.get("title", ""):
                best = best or (urls[0], "おそらく")
    return best or ("", "不明")


def fill_tabelog(auto, shops_by_id, tavily, save):
    """前の版（食べログURLを拾えなかった版）で調べた店に、食べログだけを追加で探す。1店あたり検索1回、Geminiは使わない"""
    todo = [i for i, a in auto.items() if not a.get("tabelog") and not a.get("tbChecked") and i in shops_by_id]
    if not todo:
        return
    print(f"調査済みの{len(todo)}店に、食べログだけを追加で探します")
    for n, i in enumerate(todo, 1):
        s = shops_by_id[i]
        hits = tavily.search(f"{s['name']} {s['area']}", max_results=5, domains=["tabelog.com"])
        url, conf = tabelog_match(s, hits)
        auto[i].update(tabelog=url, tbConf=conf, tbChecked=dt.date.today().isoformat())
        print(f"  [{n}/{len(todo)}] {s['area']} {s['name']} … " + (f"食べログ（{conf}）" if url else "なし"))
        save()


def main():
    ap = argparse.ArgumentParser(description="新店とInstagram・公式サイト・食べログの紐づけ候補を作る")
    ap.add_argument("--limit", type=int, default=50, help="今回調べる店数（既定50）")
    ap.add_argument("--include-bar", action="store_true", help="居酒屋・バー・スナックも対象にする")
    ap.add_argument("--area", help="市町で絞る（例：釧路市）")
    ap.add_argument("--retry-unknown", action="store_true", help="前回なにも見つからなかった店も調べ直す")
    ap.add_argument("--monthly-search-cap", type=int, default=950, help="Tavilyの月の検索上限（無料枠1,000の手前で止める）")
    ap.add_argument("--exa-cap", type=int, default=1300, help="Exaの月の検索上限（毎月10ドル分の無料クレジットの手前で止める）")
    ap.add_argument("--pause", type=float, default=4.5, help="Gemini呼び出しの最小間隔（秒）")
    args = ap.parse_args()

    keys = load_keys()
    missing = [k for k in ("GEMINI_API_KEY",) if not keys.get(k)] + \
        ([] if keys.get("TAVILY_API_KEY") or keys.get("EXA_API_KEY") else ["TAVILY_API_KEY か EXA_API_KEY"])
    if missing:
        sys.exit(f"APIキーがありません：{', '.join(missing)}\n"
                 f"{HERE / 'keys.example.txt'} を keys.txt という名前でコピーして、キーを書いてください。")
    if not INPUT.exists():
        sys.exit("pipeline/out/link_input.json がありません。先に run.bat（build_hokkaido.py）を実行してください。")

    shops = json.loads(INPUT.read_text("utf-8"))
    st = load_state()
    month = dt.date.today().strftime("%Y-%m")
    todo = []
    for s in shops:  # すでに新しい順
        prev = st["shops"].get(s["id"])
        if prev and not (args.retry_unknown and prev.get("found") is False):
            continue
        if s.get("instagram") and s.get("website"):
            continue
        if s["genre"] == "bar" and not args.include_bar:
            continue
        if args.area and s["area"] != args.area:
            continue
        todo.append(s)
    todo = todo[: args.limit]

    tavily = SearchPool([Tavily(keys["TAVILY_API_KEY"], st, month, args.monthly_search_cap) if keys.get("TAVILY_API_KEY") else None,
                         Exa(keys["EXA_API_KEY"], st, month, args.exa_cap) if keys.get("EXA_API_KEY") else None])
    osm = Osm()
    models = [m.strip() for m in keys.get("GEMINI_MODELS", DEFAULT_MODELS).split(",") if m.strip()]
    gemini = Gemini(keys["GEMINI_API_KEY"], models, st, month, args.pause)

    auto = json.loads(AUTO.read_text("utf-8")) if AUTO.exists() else {}

    def save_auto():
        tmp = AUTO.with_suffix(".tmp")
        tmp.write_text(json.dumps(auto, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(AUTO)
        save_state(st)

    try:
        fill_tabelog(auto, {s["id"]: s for s in shops}, tavily, save_auto)
    except QuotaOver as e:
        print(f"\n{e}")
        return
    if not todo:
        print("新しく調べるお店はありません（すべて調査済み）。")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"link_candidates_{dt.datetime.now():%Y%m%d-%H%M}.csv"
    f = out.open("w", encoding="utf-8-sig", newline="")
    w = csv.DictWriter(f, fieldnames=COLUMNS)
    w.writeheader()
    print(f"{len(todo)}店を調べます（今月の検索 {tavily.used()}/{tavily.cap()}回）")
    fails = 0
    stats = {"店": 0, "IG確実": 0, "IGおそらく": 0, "サイト": 0, "食べログ": 0, "注意": 0}
    try:
        for i, s in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {s['area']} {s['name']}", end=" … ", flush=True)
            try:
                hits, pages, handles = gather(s, tavily, osm)
                res = validate(judge(s, hits, pages, handles, gemini) or {}, hits, pages, handles)
            except QuotaOver:
                raise
            except Exception as e:  # noqa: BLE001  1店の失敗で全体を止めない
                fails += 1
                print(f"エラー（次回やり直します）: {type(e).__name__}: {str(e)[:300]}")
                if fails >= 3:
                    hint = ""
                    if "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper():
                        hint = "\n→ 通信の証明書エラーです。ウイルス対策ソフトや会社のネットワークが通信を検査している可能性があります。"
                    elif isinstance(e, urllib.error.URLError):
                        hint = "\n→ インターネットに接続できていません。ネット接続やプロキシの設定を確認してください。"
                    print(f"\n3店続けて失敗したので止めました。上のエラー内容を確認してください。{hint}")
                    break
                continue
            fails = 0
            row = row_for(s, res)
            w.writerow(row)
            f.flush()
            found = bool(row["instagram"] or row["公式サイト"] or row["食べログ"])
            st["shops"][s["id"]] = {"date": row["調べた日"], "found": found}
            auto[s["id"]] = {"name": s["name"], "checked": row["調べた日"],
                             "instagram": row["instagram"], "igConf": row["ig確度"], "igEvidence": row["ig根拠URL"],
                             "website": row["公式サイト"], "webConf": row["サイト確度"],
                             "tabelog": row["食べログ"], "tbConf": row["食べログ確度"],
                             "warn": row["注意"], "warnReason": row["注意の理由"], "tbChecked": row["調べた日"]}
            save_auto()
            stats["店"] += 1
            stats["IG確実"] += row["ig確度"] == "確実"
            stats["IGおそらく"] += row["ig確度"] == "おそらく"
            stats["サイト"] += bool(row["公式サイト"])
            stats["食べログ"] += bool(row["食べログ"])
            stats["注意"] += bool(row["注意"])
            print(" / ".join(x for x in [
                f"IG @{row['instagram']}（{row['ig確度']}）" if row["instagram"] else "IGなし",
                "サイトあり" if row["公式サイト"] else "", "食べログあり" if row["食べログ"] else "",
                f"⚠{row['注意']}" if row["注意"] else ""] if x))
    except QuotaOver as e:
        print(f"\n{e}")
    finally:
        f.close()
        save_state(st)

    u = st["usage"].get(month, {})
    print(f"\n調べた店 {stats['店']}店：Instagram 確実{stats['IG確実']}・おそらく{stats['IGおそらく']}、"
          f"公式サイト {stats['サイト']}、食べログ {stats['食べログ']}、注意 {stats['注意']}")
    print(f"今月の使用量：Tavily {u.get('tavily', 0)}回・Exa {u.get('exa', 0)}回・Gemini {u.get('gemini', 0)}回")
    print(f"候補一覧：{out}")
    print("結果はサイトに自動で反映されます（確度「不明」は出しません。確度は詳細画面に表示）。")
    print("間違いを直したいときだけ、この一覧で「承認」に ○（正しい）か ×（リンクを出さない）を入れて apply_linker.bat を実行します。")


if __name__ == "__main__":
    main()
