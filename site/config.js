// まんなか新店 北海道 の設定（APIキーは不要です）
window.SITE_CONFIG = {
  // 地図のデザイン（OpenFreeMap：無料・回数無制限）。liberty / bright / positron
  mapStyle: "https://tiles.openfreemap.org/styles/positron",
  center: { lat: 43.25, lng: 142.6 },
  zoom: 5.6,
  // 中間地点の候補にする条件：食事・お茶の新店がこの数以上ある市町
  minShopsForCandidate: 3,
  // 「情報の訂正を知らせる」の行き先（GitHub の Issues）
  feedbackFormUrl: "https://github.com/shiroto-ransha/mannaka-shinten-hokkaido/issues/new"
};
