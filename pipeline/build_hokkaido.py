#!/usr/bin/env python3
"""北海道 まんなか新店マップ：厚生労働省「食品衛生申請等システム」のオープンデータ → site/data/shops.json

使い方:
  python pipeline/build_hokkaido.py --download   # 北海道・札幌・函館・旭川・小樽のCSVを取得してから作る
  python pipeline/build_hokkaido.py              # pipeline/raw/ にあるCSVで作る

対象: site/data/areas.json の52市町（人口1万〜20万人の49市町＋札幌・旭川・函館）
条件: 飲食店営業・喫茶店営業・菓子製造業の「許可」で、初回許可日が基準日から3年以内、廃業していないもの
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import sys
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from genres import GENRES, classify  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent / "linker"))
from link_shops import PORTALS  # noqa: E402  公式サイトとして扱わないサイト（クーポン・紹介記事など）

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "pipeline" / "raw"
OUT = ROOT / "pipeline" / "out"
SITE_DATA = ROOT / "site" / "data"
OVERRIDES = ROOT / "pipeline" / "overrides.csv"
AUTO_LINKS = ROOT / "pipeline" / "linker" / "auto_links.json"
AUTO_OK = ("確実", "おそらく")  # 承認なしでサイトに出す確度

# 「以前から営業している可能性」の判定（食べログの店舗番号から登録時期をおおまかに推定）
# 北海道の食べログ番号は登録順に増える。2026年11月時点の新規登録は 1086xxx 台で、年におよそ4,000件増える前提。
# 営業許可日より1年以上前に食べログへ登録されていれば、許可を取り直した既存店（経営者交代・移転・改装など）とみなす
TABELOG_RATE_PER_YEAR = 4000
TABELOG_MARGIN_YEARS = 1.0

SOURCES = {  # 自治体コード → 名前（食品衛生申請等システムのオープンデータ）
    "01000": "北海道", "01100": "札幌市", "01202": "函館市", "01204": "旭川市", "01203": "小樽市",
}
DL_URL = "https://i2fas.mhlw.go.jp/faspub/page/opendatadownload.jsp?param={code}_food_business_all.csv"

KINDS = re.compile(r"飲食店営業|喫茶店営業|菓子製造業")
# 業態・名前で「食事やお茶の新店」から外すもの
EXCLUDE_GYOTAI = re.compile(
    r"コンビニ|スーパー|百貨店|臨時|催事|自動車|キッチンカー|移動|行商|給食|病院|学校|保育|社員|寮|"
    r"旅館|ホテル|宿泊|民宿|ペンション|車内|露店|祭|仮設|イベント|宅配|デリバリー|仕出し|ケータリング|"
    r"弁当|仕込|(食品|食肉|水産|そうざい|惣菜|麺類|豆腐|農産)(製造|加工)|小売|販売(?!.*(カフェ|喫茶))|自動販売|売店|配食|カラオケ|ネットカフェ|まんが|"
    r"パチンコ|ゴルフ|スキー場|浴場|温泉|サウナ|ゲーム|ボウリング|映画|劇場|スタジアム|球場")
EXCLUDE_NAME = re.compile(
    r"(社員|職員|行員|学生|従業員)食堂|厨房|給食|保育|幼稚園|学校|病院|クリニック|介護|老人|特養|デイサービス|"
    r"寮|臨時|イベント|仮設|露店|祭|模擬店|キッチンカー|移動販売|"
    r"セブン[‐\-－ー]?イレブン|ファミリーマート|ファミマ|ローソン|セイコーマート|セコマ|デイリーヤマザキ|"
    r"ミニストップ|コープ|生協|イオン|アークス|ラルズ|ビッグハウス|トライアル|ダイイチ|フクハラ|ホクレン|"
    r"売店|宴会場|カラオケ|まねきねこ|快活CLUB|ネットカフェ|麻雀|ダーツ|ゲーム|競技場|スタジアム|"
    r"ホテル|旅館|民宿|ヒルトン|温泉|保養|センター$|株式会社$|有限会社|マックスバリュ|ザ・ビッグ|業務スーパー|"
    r"あいちょう|ほっともっと|オリジン弁当|子ども食堂|診療所|配食|ゴルフ|ミュージアム|ライフプレステージ|シェアリング|仕込み場", re.I)
EXCLUDE_ADDR = re.compile(r"一円|管内")

# 業態の言葉 → ジャンル（店名より優先。ただし「食堂」「レストラン」など広い言葉は店名で判定できないときだけ使う）
GYOTAI_SPECIFIC = [
    ("noodle", r"ラーメン|らーめん|拉麺|そば|蕎麦|うどん|麺"),
    ("meat", r"焼肉|焼き肉|ジンギスカン|フライドチキン|焼鳥|焼き鳥|やきとり|ステーキ|ハンバーガー|とんかつ|からあげ|ホルモン"),
    ("washoku", r"寿司|鮨|すし|和食|日本料理|割烹|料亭|天ぷら|うなぎ|海鮮|炉端|お好み焼|定食"),
    ("asian", r"中華|中国料理|韓国|タイ料理|ベトナム|インド|ネパール|カレー|スープカレー|エスニック|餃子"),
    ("western", r"イタリア|フレンチ|フランス|洋食|ピザ|パスタ|ビストロ|スペイン|ファミリーレストラン|ファミレス"),
    ("bar", r"居酒屋|バー|BAR|スナック|ラウンジ|パブ|クラブ|酒場|立ち飲み|ビアホール|ワイン"),
    ("cafe", r"カフェ|喫茶|珈琲|コーヒー|スイーツ|ケーキ|パン|ベーカリー|菓子|甘味|ジェラート|アイス|クレープ|ジュース|ドーナツ|ティー"),
]
GYOTAI_RX = [(g, re.compile(p, re.I)) for g, p in GYOTAI_SPECIFIC]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "").strip())


def norm_key(s: str) -> str:
    s = norm(s).lower()
    s = re.sub(r"[\s・\-‐－―ー、。,.()（）「」『』\"'＊*]", "", s)
    s = re.sub(r"(\d+)丁目", r"\1-", s)
    s = re.sub(r"(\d+)番地?", r"\1-", s)
    return re.sub(r"(\d+)号", r"\1", s)


def parse_date(v: str):
    m = re.match(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", norm(v))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def municipality(addr: str, names: set[str]) -> str | None:
    a = norm(addr).replace("北海道", "", 1)
    a = re.sub(r"^[^\s]{1,4}?郡", "", a)  # 「余市郡余市町」→「余市町」
    for n in sorted(names, key=len, reverse=True):
        if a.startswith(n):
            return n
    return None


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    for code, name in SOURCES.items():
        url = DL_URL.format(code=code)
        print(f"取得中: {name} …", end=" ", flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "hokkaido-shinten-map data builder"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        (RAW / f"{code}_food_business_all.csv").write_bytes(data)
        print(f"{len(data) // 1024:,} KB")


def read_csv(path: Path) -> list[dict]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return list(csv.DictReader(io.StringIO(text)))


def genre_for(name: str, gyotai: str, kinds: list[str], override: str | None):
    if override:
        return classify(name, kinds, None, override)
    g = norm(gyotai)
    for gid, rx in GYOTAI_RX:
        m = rx.search(g)
        if m:
            return gid, f"業態:{m.group(0)}"
    gid, why = classify(name, kinds, None, None)
    if why == "判定不能" and re.search(r"レストラン", g):
        return "western", "業態:レストラン"
    return gid, why


PRIVATE_FIELDS = ("genreReason", "kinds", "kana", "tel", "corp")


def link_fields(s: dict, o: dict, a: dict):
    """リンクは「人が確認したもの（overrides.csv）」→「自動照合で確度が確実・おそらく」の順に採用。
    overrides.csv のセルに - を入れると、そのリンクは出さない。確度もサイトに出してリスクを表示する"""
    for key, conf in (("instagram", "igConf"), ("website", "webConf"), ("tabelog", "tbConf")):
        manual, value, c = (o.get(key) or "").strip(), None, None
        if manual == "-":
            pass
        elif manual:
            value, c = manual, "確認済み"
        elif a.get(key) and a.get(conf) in AUTO_OK and not (key == "website" and PORTALS.search(a[key])):
            value, c = a[key], a[conf]
        if key == "instagram" and value:
            value = value.lstrip("@").lower()
        if key == "tabelog" and value and not re.match(r"https://tabelog\.com/", value):
            value = None
        if key == "website" and value and not re.match(r"https?://", value):
            value = None
        s[key], s[conf] = value, (c if value else None)
    if a.get("warn") and o.get("hide") != "warnok":
        s["warn"], s["warnReason"] = a["warn"], (a.get("warnReason") or "")[:80]


def tabelog_no(url):
    m = re.search(r"/hokkaido/A\d{4}/A\d{6}/(\d{7,8})/", url or "")
    return int(m.group(1)) if m else None


def mark_older(shops: list, today: dt.date, ov: dict):
    """以前から営業している可能性がある店に older（理由）を付ける。サイトでは表示の優先順位を下げる。
    overrides.csv の hide 列に notold と書くと、この判定を外せる"""
    nos = [tabelog_no(s.get("tabelog")) for s in shops]
    latest = max([n for n in nos if n] or [0])
    for s, no in zip(shops, nos):
        if (ov.get(s["id"], {}).get("hide") or "") == "notold":
            continue
        reason = None
        if no and latest:
            years = (today - dt.date.fromisoformat(s["permitDate"])).days / 365.25
            limit = latest - TABELOG_RATE_PER_YEAR * (years + TABELOG_MARGIN_YEARS)
            if no < limit:
                reason = "営業許可日より前から食べログに掲載されています（掲載番号からの推定）"
        if not reason and s.get("warn") == "移転の疑い":
            reason = "別の場所から移転してきたお店の可能性があります（自動判定）"
        if reason:
            s["older"] = reason


def load_overrides() -> dict:
    if not OVERRIDES.exists():
        return {}
    try:
        text = OVERRIDES.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:  # Excelで上書き保存するとShift_JISになる
        text = OVERRIDES.read_text(encoding="cp932")
    return {r["id"].strip(): {k: (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text)) if r.get("id")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--download", action="store_true", help="オープンデータを取得してから作る")
    ap.add_argument("--raw", default=str(RAW))
    args = ap.parse_args()
    if args.download:
        download()

    today = dt.date.fromisoformat(args.today)
    try:
        cutoff = today.replace(year=today.year - args.years)
    except ValueError:
        cutoff = today.replace(year=today.year - args.years, day=28)

    areas = json.loads((SITE_DATA / "areas.json").read_text("utf-8"))["areas"]
    names = {a["name"] for a in areas}
    ring_of = {a["name"]: a["ring"] for a in areas}

    files = sorted(Path(args.raw).glob("*.csv"))
    if not files:
        sys.exit("CSVがありません。--download を付けて実行してください")

    report, shops = [], {}
    total = 0
    for f in files:
        for r in read_csv(f):
            total += 1
            name = norm(r.get("営業施設名称、屋号又は商号", ""))
            kind = norm(r.get("営業の種類", ""))
            gyotai = norm(r.get("業態", ""))
            addr = norm(r.get("営業施設所在地", ""))
            first = parse_date(r.get("初回許可年月日", "")) or parse_date(r.get("許可年月日", ""))
            reason = ""
            muni = municipality(addr, names) if addr else None
            if not KINDS.search(kind):
                continue  # 飲食以外は報告にも載せない
            if r.get("申請区分", "") != "許可":
                reason = f"許可ではない（{r.get('申請区分', '')}）"
            elif r.get("廃業年月日"):
                reason = "廃業"
            elif not name:
                reason = "店名が非公開"
            elif not muni:
                reason = "対象の52市町の外"
            elif EXCLUDE_ADDR.search(addr) or EXCLUDE_GYOTAI.search(gyotai) or EXCLUDE_NAME.search(name):
                reason = "店舗での食事・お茶ではない（コンビニ・臨時・移動販売・給食など）"
            elif not first:
                reason = "初回許可日が読めない"
            elif first < cutoff:
                reason = f"{args.years}年より前の許可"
            elif first > today:
                reason = "基準日より後"
            report.append({"result": reason or "採用", "name": name, "gyotai": gyotai, "kind": kind,
                           "address": addr, "first": first.isoformat() if first else "", "file": f.name})
            if reason:
                continue
            key = hashlib.sha1(f"{norm_key(name)}|{norm_key(addr)}".encode()).hexdigest()[:12]
            lat, lng = r.get("緯度", ""), r.get("経度", "")
            s = shops.get(key)
            if s:
                s["kinds"] = sorted(set(s["kinds"]) | {kind})
                s["permitDate"] = min(s["permitDate"], first.isoformat())
                s["gyotai"] = s["gyotai"] or gyotai
                s["tel"] = s["tel"] or norm(r.get("営業施設電話番号", ""))
                if not s["lat"] and lat:
                    s["lat"], s["lng"] = round(float(lat), 6), round(float(lng), 6)
                continue
            shops[key] = {"id": key, "name": name, "address": addr, "area": muni, "ring": ring_of[muni],
                          "kana": norm(r.get("営業施設名称、屋号又は商号（フリガナ）", "")),
                          "tel": norm(r.get("営業施設電話番号", "")), "corp": norm(r.get("法人名", "")),
                          "kinds": [kind], "gyotai": gyotai, "permitDate": first.isoformat(),
                          "lat": round(float(lat), 6) if lat else None, "lng": round(float(lng), 6) if lng else None}

    ov = load_overrides()
    auto = json.loads(AUTO_LINKS.read_text("utf-8")) if AUTO_LINKS.exists() else {}
    out = []
    for s in shops.values():
        o = ov.get(s["id"], {})
        if o.get("hide") in ("1", "true", "yes"):
            continue
        s["genre"], s["genreReason"] = genre_for(s["name"], s["gyotai"], s["kinds"], o.get("genre") or None)
        s["pr"] = o.get("pr") in ("1", "true", "yes")
        link_fields(s, o, auto.get(s["id"], {}))
        # 写真・画像は載せない（著作権のおそれ）。文字とリンク先URLだけ
        out.append(s)
    mark_older(out, today, ov)
    out.sort(key=lambda s: s["permitDate"], reverse=True)

    SITE_DATA.mkdir(parents=True, exist_ok=True)
    payload = {"generatedAt": dt.datetime.now().isoformat(timespec="seconds"), "today": today.isoformat(),
               "cutoff": cutoff.isoformat(), "genres": GENRES,
               "source": "厚生労働省「食品衛生申請等システム」オープンデータ（北海道・札幌市・函館市・旭川市・小樽市）",
               "shops": [{k: v for k, v in s.items() if k not in PRIVATE_FIELDS and v not in (None, False, "")} for s in out]}
    (SITE_DATA / "shops.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")

    OUT.mkdir(parents=True, exist_ok=True)
    # 紐づけスクリプト用（電話番号・フリガナ入り。サイトには出さない）
    (OUT / "link_input.json").write_text(json.dumps(
        [{k: s.get(k) for k in ("id", "name", "kana", "tel", "corp", "address", "area", "gyotai", "genre", "permitDate", "instagram", "website", "tabelog")}
         for s in out], ensure_ascii=False), "utf-8")
    with (OUT / "report.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["result", "name", "gyotai", "kind", "address", "first", "file"])
        w.writeheader()
        w.writerows(report)
    with (OUT / "shops_review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "area", "name", "gyotai", "genre", "genreReason", "permitDate", "lat", "lng"])
        for s in out:
            w.writerow([s["id"], s["area"], s["name"], s["gyotai"], s["genre"], s["genreReason"], s["permitDate"], s["lat"], s["lng"]])

    print(f"読み込み {total:,}行 → 新店 {len(out):,}店（{cutoff} 以降の許可）")
    print("除外の内訳:", Counter(r["result"].split("（")[0] for r in report if r["result"] != "採用").most_common(6))
    g = Counter(s["genre"] for s in out)
    print("ジャンル:", ", ".join(f"{x['label']} {g.get(x['id'], 0)}" for x in GENRES))
    print(f"位置あり {sum(1 for s in out if s['lat']):,}店")
    by = Counter(s["area"] for s in out)
    print("市町別（上位）:", ", ".join(f"{k} {v}" for k, v in by.most_common(15)))


if __name__ == "__main__":
    import urllib.parse  # noqa: E402
    main()
