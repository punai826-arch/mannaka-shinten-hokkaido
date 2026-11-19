"""屋号（店名）と業種から、提供内容を8ジャンルに分類する。

判定の順番:
  1. 管理者が overrides.csv で指定したジャンル
  2. Google Places の primaryType（位置特定時に取得できた場合）
  3. 屋号のキーワード
  4. 業種（菓子製造業 → カフェ・スイーツ・パン）
  5. どれにも当たらなければ「その他」
"""
import re
import unicodedata

GENRES = [
    {"id": "washoku",  "label": "和食",               "color": "#c92a2a", "icon": "🍣"},
    {"id": "noodle",   "label": "ラーメン・麺類",      "color": "#e8590c", "icon": "🍜"},
    {"id": "meat",     "label": "焼肉・肉料理",        "color": "#862e9c", "icon": "🥩"},
    {"id": "asian",    "label": "中華・アジア・エスニック", "color": "#d6336c", "icon": "🥟"},
    {"id": "western",  "label": "洋食・イタリアン・フレンチ", "color": "#1971c2", "icon": "🍝"},
    {"id": "bar",      "label": "居酒屋・バー",        "color": "#5f3dc4", "icon": "🍺"},
    {"id": "cafe",     "label": "カフェ・スイーツ・パン", "color": "#2b8a3e", "icon": "☕"},
    {"id": "other",    "label": "食堂・その他", "color": "#495057", "icon": "🍱"},
]
GENRE_IDS = {g["id"] for g in GENRES}

# 先に書いたものほど優先（具体的なものを先に）。港区の実データ（2026-11）で調整済み
KEYWORDS = [
    ("asian",  r"中華|中国|飯店|酒家|菜館|四川|重慶|広州|上海|北京|台湾|台北|小籠包|餃子|ぎょうざ|点心|飲茶|麻辣|火鍋|珉珉|味仙|担々|"
               r"韓国|コリア|ソウル|seoul|タッカンマリ|参鶏湯|サムギョプサル|チーズタッカルビ|ビビンバ|"
               r"タイ料理|タイの|thai|バンコク|bangkok|siam|サイアム|ベトナム|viet|バインミー|バインセオ|フォー|pho|"
               r"インド|india|delhi|ネパール|カレー|curry|タンドール|tandoor|ビリヤニ|スパイス|spice|モンゴル|bao|"
               r"エスニック|アジア|asian|ケバブ|kebab|スープカレー|トルコ|シンガポール|マレー|インドネシア|ナシゴレン"),
    ("noodle", r"ラーメン|らーめん|拉麺|らあめん|中華そば|つけ麺|つけめん|まぜそば|油そば|油堂|油党|油組|家系|壱角家|神座|萬馬軒|"
               r"ramen|noodle|ヌードル|うどん|饂飩|udon|丸亀|蕎麦|そば|soba|更科|長寿庵|大村庵|川上庵|松原庵|ゆで太郎|麺"),
    ("meat",   r"焼肉|焼き肉|やきにく|yakiniku|ホルモン|もつ|ステーキ|steak|ハンバーグ|ハンバーガー|バーガー|burger|マクドナルド|ケンタッキー|フライドチキン|ザンギ|"
               r"焼鳥|焼き鳥|やきとり|yakitori|鳥|鶏|とり|串焼|串八|地鶏|からあげ|唐揚|とんかつ|豚カツ|カツ|かつ(?!お)|豚|"
               r"しゃぶしゃぶ|すき焼|ジンギスカン|成吉思汗|しゃぶ|羊|ラム|肉|にく|牛|wagyu|beef|ビーフ|butcher|meat|bbq|グリル|grill|"
               r"シュラスコ|churrascaria|ロースト"),
    ("washoku",r"寿司|鮨|すし|sushi|割烹|料亭|懐石|和食|日本料理|料理|天ぷら|天麩羅|てんぷら|鰻|うなぎ|おでん|小料理|定食|丼|"
               r"おにぎり|おむすび|おばんざい|わっぱ|茶漬|一汁|海鮮|魚|水産|漁|鮮|さば|鯖|まぐろ|鮪|鰹|かき小屋|牡蠣|"
               r"鉄板焼|鉄ぱん|お好み焼|もんじゃ|たこ焼|銀だこ|串揚|串カツ|串の坊|とうふ|豆腐|味噌|わらやき|藁焼|炉端|炉ばた|ろばた|浜焼|"
               r"松屋|すき家|吉野家|なか卯|和食処|御膳|膳"),
    ("western",r"イタリア|伊太利|italia|trattoria|トラットリア|osteria|オステリア|ristorante|リストランテ|cucina|forno|"
               r"pizza|ピザ|ピッツァ|pizzeria|パスタ|pasta|スパゲッ|spaghetti|フレンチ|フランス|french|bistro|ビストロ|"
               r"brasserie|ブラッスリー|restaurant|レストラン|洋食|スペイン|バル(?!ー)|メキシ|taco|タコス|オムライス|"
               r"oyster|オイスター|cuisine|dining|ダイニング|デニーズ|サイゼリヤ|ロイヤルホスト|trattoria"),
    ("bar",    r"居酒屋|居楽屋|酒場|大衆酒|立ち飲み|立飲|立呑|角打|呑|飲み|酒|bar|バー|pub|パブ|hub|ワイン|wine|vin|ビール|beer|"
               r"brew|ブルワリー|taps|スナック|すなっく|snack|ラウンジ|lounge|club|クラブ|izakaya|やきとん|sake|ハイボール|"
               r"サワー|泡|庄や|白木屋|千年の宴|土風炉|塚田農場|てけてけ|山ちゃん|鳥貴族|赤ちょうちん|屋台|宴|cigar|"
               r"whisky|ウイスキー|spirits|cocktail|カクテル"),
    ("cafe",   r"カフェ|cafe|café|coffee|珈琲|コーヒー|喫茶|ティー|tea|茶房|甘味|スイーツ|sweets|パティスリー|patisserie|"
               r"ケーキ|cake|ベーカリー|bakery|パン|bread|boulangerie|ブーランジェリー|ドーナツ|donut|doughnut|クレープ|"
               r"crepe|ジェラート|gelato|アイス|ice\s?cream|チョコ|choco|タルト|tart|プリン|パフェ|ワッフル|ベーグル|bagel|"
               r"かき氷|抹茶|matcha|菓子|大福|団子|たいやき|鯛焼|roaster|ロースタリー|プロント|ドトール|スターバックス|"
               r"starbucks|タリーズ|コメダ|サラダ|salad|スムージー|smoothie|ジュース|juice"),
    ("other",  r"弁当|べんとう|bento|ほっともっと|オリジン|デリ|deli|惣菜|そうざい|キッチン|kitchen|テイクアウト|takeout|"
               r"ケータリング|catering|ゴーストキッチン|食堂|ビュッフェ|buffet"),
]
_COMPILED = [(g, re.compile(p, re.IGNORECASE)) for g, p in KEYWORDS]

# Google Places (New) の primaryType → ジャンル
PLACE_TYPE_MAP = {
    "japanese_restaurant": "washoku", "sushi_restaurant": "washoku", "seafood_restaurant": "washoku",
    "ramen_restaurant": "noodle", "noodle_shop": "noodle", "udon_noodle_shop": "noodle", "soba_noodle_shop": "noodle",
    "barbecue_restaurant": "meat", "yakiniku_restaurant": "meat", "steak_house": "meat", "hamburger_restaurant": "meat",
    "yakitori_restaurant": "meat", "tonkatsu_restaurant": "meat", "shabu_shabu_restaurant": "meat", "korean_barbecue_restaurant": "meat",
    "chinese_restaurant": "asian", "korean_restaurant": "asian", "thai_restaurant": "asian", "vietnamese_restaurant": "asian",
    "indian_restaurant": "asian", "asian_restaurant": "asian", "dumpling_restaurant": "asian", "curry_restaurant": "asian",
    "nepalese_restaurant": "asian", "middle_eastern_restaurant": "asian", "taiwanese_restaurant": "asian",
    "italian_restaurant": "western", "french_restaurant": "western", "pizza_restaurant": "western", "spanish_restaurant": "western",
    "american_restaurant": "western", "mexican_restaurant": "western", "mediterranean_restaurant": "western", "western_restaurant": "western",
    "fine_dining_restaurant": "western", "bistro": "western",
    "bar": "bar", "pub": "bar", "wine_bar": "bar", "izakaya_restaurant": "bar", "cocktail_bar": "bar", "brewpub": "bar", "beer_hall": "bar",
    "cafe": "cafe", "coffee_shop": "cafe", "bakery": "cafe", "dessert_shop": "cafe", "dessert_restaurant": "cafe", "ice_cream_shop": "cafe",
    "donut_shop": "cafe", "confectionery": "cafe", "tea_house": "cafe", "cake_shop": "cafe", "pastry_shop": "cafe", "bagel_shop": "cafe",
    "juice_shop": "cafe", "chocolate_shop": "cafe", "japanese_confectionery_shop": "cafe",
    "meal_takeaway": "other", "meal_delivery": "other", "deli": "other", "food_court": "other", "cafeteria": "other",
}


def classify(name: str, kinds: list[str], place_type: str | None = None, override: str | None = None) -> tuple[str, str]:
    """(genre_id, 判定理由) を返す。"""
    if override and override in GENRE_IDS:
        return override, "管理者指定"
    if place_type and place_type in PLACE_TYPE_MAP:
        return PLACE_TYPE_MAP[place_type], f"Google分類:{place_type}"
    text = unicodedata.normalize("NFKC", name or "")
    for gid, rx in _COMPILED:
        m = rx.search(text)
        if m:
            return gid, f"屋号:{m.group(0)}"
    if any("菓子" in k or "喫茶" in k for k in kinds):
        return "cafe", "業種"
    return "other", "判定不能"


# OpenStreetMap の cuisine / amenity タグ → ジャンル
OSM_CUISINE = {
    "japanese": "washoku", "sushi": "washoku", "tempura": "washoku", "unagi": "washoku", "seafood": "washoku", "fish": "washoku",
    "okonomiyaki": "washoku", "takoyaki": "washoku", "donburi": "washoku", "teishoku": "washoku", "kaiseki": "washoku",
    "oden": "washoku", "onigiri": "washoku", "regional": "washoku", "gyudon": "washoku", "kushikatsu": "washoku",
    "ramen": "noodle", "noodle": "noodle", "udon": "noodle", "soba": "noodle", "tsukemen": "noodle",
    "yakiniku": "meat", "yakitori": "meat", "chicken": "meat", "fried_chicken": "meat", "burger": "meat", "steak_house": "meat",
    "barbecue": "meat", "tonkatsu": "meat", "shabu-shabu": "meat", "sukiyaki": "meat", "meat": "meat", "grill": "meat",
    "chinese": "asian", "korean": "asian", "thai": "asian", "vietnamese": "asian", "indian": "asian", "curry": "asian",
    "nepalese": "asian", "asian": "asian", "taiwanese": "asian", "dumpling": "asian", "turkish": "asian", "kebab": "asian",
    "malaysian": "asian", "indonesian": "asian", "singaporean": "asian", "sichuan": "asian", "cantonese": "asian",
    "italian": "western", "pizza": "western", "pasta": "western", "french": "western", "spanish": "western",
    "mexican": "western", "american": "western", "western": "western", "european": "western", "mediterranean": "western",
    "brazilian": "western", "peruvian": "western", "german": "western", "oyster": "western",
    "izakaya": "bar", "wine": "bar", "beer": "bar", "sake": "bar",
    "coffee_shop": "cafe", "cake": "cafe", "crepe": "cafe", "ice_cream": "cafe", "donut": "cafe", "dessert": "cafe",
    "bubble_tea": "cafe", "tea": "cafe", "sandwich": "cafe", "salad": "cafe", "juice": "cafe", "pancake": "cafe",
    "bagel": "cafe", "pastry": "cafe", "wagashi": "cafe",
}
OSM_AMENITY = {"bar": "bar", "pub": "bar", "biergarten": "bar", "nightclub": "bar", "cafe": "cafe", "ice_cream": "cafe",
               "bakery": "cafe", "confectionery": "cafe", "pastry": "cafe", "coffee": "cafe", "tea": "cafe"}


def genre_from_osm(tags: dict):
    """(genre, 根拠) を返す。cuisine を優先、なければ amenity/shop。決められなければ (None, None)。"""
    for c in (tags.get("cuisine") or "").lower().replace(" ", "").split(";"):
        if c in OSM_CUISINE:
            return OSM_CUISINE[c], f"OSM料理:{c}"
    for k in ("amenity", "shop"):
        v = tags.get(k)
        if v in OSM_AMENITY:
            return OSM_AMENITY[v], f"OSM種別:{v}"
    return None, None
