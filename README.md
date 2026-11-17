# まんなか新店 北海道（PoC）

離れて住む2〜4人の「まんなか」の市町で、開店3年以内の新しいお店を探すサイトです。

公開URL：https://punai826-arch.github.io/mannaka-shinten-hokkaido/

## しくみ
- `pipeline/build_hokkaido.py` … 厚生労働省「食品衛生申請等システム」のオープンデータから、北海道52市町の開店3年以内のお店を作る
- `pipeline/linker/link_shops.py` … Instagram・公式サイト・食べログを自動で紐づける。検索は Tavily・Exa の無料枠を残りの多い順に使い、OpenStreetMap に登録された公式サイト・Instagram も材料にする。判定は Gemini の無料枠。承認作業はなく、確度「確実」「おそらく」だけを確度つきで載せる
- `pipeline/build_pages.py` … トップ（まんなか検索）・市町ページ・まんなかページ・sitemap.xml を `public/` に作る
- `.github/workflows/monthly-update.yml` … 毎月2・9・16・23日に上の3つを自動で実行（紐づけは1回150店＝月600店。Geminiの1日の無料枠に収まるよう分けている）し、GitHub Pages に公開する

## 毎月の自動更新に必要な設定（1回だけ）
Settings → Secrets and variables → Actions に次の2つを登録します（ないときは紐づけだけ飛ばして、お店データは更新されます）。
- `GEMINI_API_KEY`（Google AI Studio）
- `TAVILY_API_KEY`（Tavily・毎月1,000回）
- `EXA_API_KEY`（Exa・毎月10ドル分＝約1,400回。なくても動きます）

## 直したいとき（任意）
`pipeline/overrides.csv` を GitHub の画面で編集すると、次の公開から反映されます。
- instagram / website / tabelog のセルに `-` … そのリンクを出さない（URLやアカウント名を書くと「運営が確認済み」で出す）
- hide 列に `1` … お店を出さない / `warnok` … 注意表示を消す / `notold` … 「以前から営業」の表示を外す

## 出典
- お店：厚生労働省「食品衛生申請等システム」オープンデータを加工して作成
- 地図：© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors
- 移動時間：OSRM（OpenStreetMap）による車の所要時間の目安
- 写真や口コミは掲載していません
