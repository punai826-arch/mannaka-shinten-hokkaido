// まんなか新店 北海道 の設定（APIキーは不要です）
window.SITE_CONFIG = {
  // 地図のデザイン（OpenFreeMap：無料・回数無制限）。liberty / bright / positron
  mapStyle: "https://tiles.openfreemap.org/styles/positron",
  center: { lat: 43.25, lng: 142.6 },
  zoom: 5.6,
  // エリアカラー（企画書の色彩ブランディング）
  rings: [
    { id: "sapporo",   label: "札幌",           color: "#2F5D8C", motif: "冬空の藍" },
    { id: "asahikawa", label: "旭川",           color: "#7B5EA7", motif: "ラベンダー" },
    { id: "hakodate",  label: "函館",           color: "#A63D40", motif: "赤レンガ" },
    { id: "tomakomai", label: "苫小牧・室蘭",   color: "#1E7F86", motif: "港の青緑" },
    { id: "obihiro",   label: "帯広",           color: "#8C6409", motif: "十勝の小麦" },
    { id: "kushiro",   label: "釧路・根室",     color: "#3E7D4F", motif: "湿原の緑" },
    { id: "kitami",    label: "北見・オホーツク", color: "#2E7499", motif: "流氷の水色" }
  ],
  // 中間地点の候補にする条件：食事・お茶の新店がこの数以上ある市町
  minShopsForCandidate: 3,
  // 「情報の訂正・Instagramを教える」の行き先（Googleフォームなど・任意）
  feedbackFormUrl: "https://github.com/punai826-arch/mannaka-shinten-hokkaido/issues/new"
};
