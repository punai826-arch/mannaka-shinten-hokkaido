// まんなか新店 北海道 — 「まんなかを探す」が主役。地図とお店の提案は検索の結果として出す
const CFG = window.SITE_CONFIG;
const ROOT = window.SITE_ROOT || "./";
const PERSON = [{ k: "A", c: "#14284B" }, { k: "B", c: "#D9668A" }, { k: "C", c: "#2A9A93" }, { k: "D", c: "#8E7CD6" }];
const BRAND_COLOR = "#2C5FA8";
const PAGE = 24; // 横スクロールに並べる数（それ以上は市町ページで）
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

let DATA, AREAS, MIN, GENRE = {}, AIDX = {};
const lastVisit = store.get("mn-last-visit", null);
const went = new Set(store.get("mn-went", []));
const state = { people: [], cands: [], cand: null, genre: "", shown: PAGE };
let ml = null, mapLoading = null;

// 詳細シートは市町ページ（静的HTML）でも使う
$("#close").onclick = closeDetail; $("#scrim").onclick = closeDetail;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });

init();
async function init() {
  const [shops, areas] = await Promise.all([fetch(ROOT + "data/shops.json").then((r) => r.json()), fetch(ROOT + "data/areas.json").then((r) => r.json())]);
  DATA = shops; AREAS = areas.areas; MIN = areas.minutes;
  AREAS.forEach((a, i) => (AIDX[a.name] = i));
  DATA.genres.forEach((g) => (GENRE[g.id] = g));
  const gen = $("#generated");
  if (gen) gen.textContent = `データ更新：${DATA.generatedAt.slice(0, 10)}（${DATA.cutoff} 以降に許可されたお店 ${DATA.shops.length.toLocaleString()}店）`;
  store.set("mn-last-visit", DATA.generatedAt);
  if (!$("#finder")) return; // 市町ページは検索フォームなし

  // 最初の人たち：共有リンク（?p=札幌市,帯広市&bar=1）→ ページの指定（まんなかページ）→ 空欄2人
  const q = new URLSearchParams(location.search);
  const preset = (q.get("p") || document.body.dataset.people || "").split(",").filter((n) => n in AIDX).slice(0, 4);
  state.people = preset.length ? preset : ["", ""];
  while (state.people.length < 2) state.people.push("");
  $("#withBar").checked = q.get("bar") === "1";
  $("#addPerson").onclick = () => { if (state.people.length < 4) { state.people.push(""); renderPeople(); } };
  $("#findMid").onclick = () => findMid(true);
  $("#share").onclick = share;
  $("#editPeople").onclick = () => $("#finder").scrollIntoView({ behavior: "smooth", block: "start" });
  renderPeople();
  if (state.people.filter(Boolean).length >= 2) findMid(false);
}

// ---------- 人と市町 ----------
function areaOptions(sel) {
  return `<option value="">住んでいる市町を選ぶ</option>` + [...AREAS].sort((a, b) => b.pop - a.pop)
    .map((a) => `<option ${a.name === sel ? "selected" : ""}>${esc(a.name)}</option>`).join("");
}
function renderPeople() {
  const box = $("#people");
  box.innerHTML = "";
  state.people.forEach((p, i) => {
    const d = document.createElement("div");
    d.className = "person";
    d.innerHTML = `<span class="who" style="background:${PERSON[i].c}">${PERSON[i].k}</span>
      <select aria-label="${PERSON[i].k}さんの市町">${areaOptions(p)}</select>
      <button class="iconbtn" type="button" title="現在地から選ぶ" aria-label="現在地から選ぶ">📍</button>
      ${state.people.length > 2 ? `<button class="iconbtn" type="button" title="この人を外す" aria-label="この人を外す">×</button>` : "<span></span>"}`;
    d.querySelector("select").onchange = (e) => { state.people[i] = e.target.value; };
    d.querySelectorAll("button")[0].onclick = () => locateNearest(i);
    if (state.people.length > 2) d.querySelectorAll("button")[1].onclick = () => { state.people.splice(i, 1); renderPeople(); };
    box.appendChild(d);
  });
  $("#addPerson").hidden = state.people.length >= 4;
}
function locateNearest(i) {
  if (!navigator.geolocation) return toast("この端末では現在地を使えません");
  navigator.geolocation.getCurrentPosition((pos) => {
    const { latitude: la, longitude: lo } = pos.coords;
    let best = null, bd = Infinity;
    AREAS.forEach((a) => { const d = (a.lat - la) ** 2 + ((a.lng - lo) * Math.cos(la * Math.PI / 180)) ** 2; if (d < bd) { bd = d; best = a; } });
    state.people[i] = best.name; renderPeople(); toast(`${best.name}を選びました`);
  }, () => toast("現在地を取得できませんでした"), { timeout: 8000 });
}

// ---------- まんなかを探す ----------
const withBar = () => $("#withBar").checked;
const mealShops = (area) => DATA.shops.filter((s) => s.area === area && (withBar() || s.genre !== "bar"));
function findMid(scroll) {
  const ppl = state.people.filter(Boolean);
  if (ppl.length < 2) return toast("2人以上の市町を選んでください");
  const idx = ppl.map((n) => AIDX[n]);
  state.cands = AREAS.map((a, j) => {
    const t = idx.map((i) => MIN[i][j]);
    const all = mealShops(a.name), fresh = all.filter((s) => !s.older).length;
    return { area: a, times: t, max: Math.max(...t), sum: t.reduce((x, y) => x + y, 0), shops: all.length, fresh, older: all.length - fresh };
  }).filter((c) => c.shops >= CFG.minShopsForCandidate)
    // 10分以内の差は同じとみなし、本当に新しい店（以前から営業の可能性がない店）の多い市町を上に
    .sort((a, b) => Math.floor(a.max / 10) - Math.floor(b.max / 10) || b.fresh - a.fresh || b.shops - a.shops || a.sum - b.sum)
    .slice(0, 3);
  const q = new URLSearchParams({ p: ppl.join(",") });
  if (withBar()) q.set("bar", "1");
  history.replaceState(null, "", `${location.pathname}?${q}`);
  $("#results").hidden = false;
  renderCands(ppl);
  if (state.cands.length) chooseCand(0);
  ensureMap().then(() => { drawMeet(ppl); fitTo([...ppl.map((n) => AREAS[AIDX[n]]), ...state.cands.map((c) => c.area)]); });
  if (scroll) requestAnimationFrame(() => $("#results").scrollIntoView({ behavior: "smooth", block: "start" }));
}
const hm = (m) => (m < 60 ? `${m}分` : `${Math.floor(m / 60)}時間${m % 60 ? (m % 60) + "分" : ""}`);
function renderCands(ppl) {
  const box = $("#cands");
  $("#resTitle").textContent = `${ppl.join("・")}のまんなか`;
  if (!state.cands.length) { box.innerHTML = `<p class="fine">候補が見つかりませんでした。「お酒のお店も含める」を試してください。</p>`; $("#candMeta").innerHTML = ""; $("#list").innerHTML = ""; return; }
  box.innerHTML = state.cands.map((c, i) => `<button class="tab" type="button" role="tab" data-i="${i}" aria-selected="false">
      <span class="rank">${i + 1}</span><span class="tab-name">${esc(c.area.name)}</span><span class="tab-sub">新店${c.fresh}店</span></button>`).join("");
  box.querySelectorAll(".tab").forEach((el) => (el.onclick = () => { chooseCand(+el.dataset.i); ensureMap().then(() => fitTo(shopsOf(state.cands[+el.dataset.i]).filter((s) => s.lat))); }));
}
function chooseCand(i) {
  state.cand = i; state.genre = ""; state.shown = PAGE;
  document.querySelectorAll("#cands .tab").forEach((el) => { const on = +el.dataset.i === i; el.classList.toggle("on", on); el.setAttribute("aria-selected", on); });
  const c = state.cands[i], ppl = state.people.filter(Boolean);
  $("#candMeta").innerHTML = `<div class="times">${c.times.map((t, k) => `<span class="time"><i style="background:${PERSON[k].c}"></i>${esc(ppl[k])}から <b>${t === 0 ? "地元" : hm(t)}</b></span>`).join("")}</div>
    ${c.older ? `<p class="cand-note">ほかに、以前から営業している可能性のあるお店が${c.older}店</p>` : ""}`;
  $("#cityLink").href = `${ROOT}city/${c.area.slug}/`;
  $("#cityLink").textContent = `${c.area.name}の新店をすべて見る`;
  buildChips(); renderShops(true);
}
const shopsOf = (c) => mealShops(c.area.name);

// ---------- 候補の市町のお店 ----------
function buildChips() {
  const c = state.cands[state.cand], all = shopsOf(c);
  const cnt = {};
  all.forEach((s) => (cnt[s.genre] = (cnt[s.genre] || 0) + 1));
  const box = $("#genreChips");
  box.innerHTML = "";
  [["", "すべて", "🍽", "#2C5FA8", all.length], ...DATA.genres.filter((g) => cnt[g.id]).sort((a, b) => cnt[b.id] - cnt[a.id]).map((g) => [g.id, g.label.split("・")[0], g.icon, g.color, cnt[g.id]])]
    .forEach(([id, label, icon, color, n]) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "chip" + (state.genre === id ? " on" : ""); b.style.setProperty("--g", color);
      b.setAttribute("aria-pressed", state.genre === id);
      b.innerHTML = `<span class="chip-ico" aria-hidden="true">${icon}</span>${esc(label)}<span class="chip-n">${n}</span>`;
      b.onclick = () => { state.genre = id; state.shown = PAGE; buildChips(); renderShops(true); };
      box.appendChild(b);
    });
}
const isNew = (s) => lastVisit && !s.older && s.permitDate > lastVisit.slice(0, 10);
function visible() {
  return shopsOf(state.cands[state.cand]).filter((s) => !state.genre || s.genre === state.genre)
    .sort((a, b) => (a.older ? 1 : 0) - (b.older ? 1 : 0) || (a.permitDate < b.permitDate ? 1 : -1)); // 以前から営業の可能性がある店は後ろへ
}
function renderShops(updateMap) {
  const v = visible(), list = $("#list"), c = state.cands[state.cand];
  $("#railTitle").innerHTML = `${esc(c.area.name)}の新しいお店 <span>${v.filter((s) => !s.older).length}店</span>`;
  list.innerHTML = "";
  v.slice(0, state.shown).forEach((s) => {
    const g = GENRE[s.genre];
    const has = [s.instagram && "Instagram", s.website && "公式サイト", s.tabelog && "食べログ"].filter(Boolean);
    const b = document.createElement("button");
    b.type = "button"; b.className = "card" + (s.older ? " older" : "");
    b.style.setProperty("--g", g.color);
    b.innerHTML = `<span class="card-band"><span class="g" aria-hidden="true">${g.icon}</span><span class="card-genre">${esc(g.label.split("・")[0])}</span>
        <span class="card-flags">${isNew(s) ? '<span class="badge b-new">NEW</span>' : ""}${s.older ? '<span class="badge b-older">以前から営業？</span>' : ""}${went.has(s.id) ? '<span class="badge b-went">行った</span>' : ""}</span></span>
      <span class="card-body"><span class="card-name">${esc(s.name)}</span>
      <span class="card-meta">${fmt(s.permitDate, true)} 許可${s.gyotai ? "・" + esc(s.gyotai) : ""}</span>
      ${has.length ? `<span class="has">${has.map((h) => `<span>${h}</span>`).join("")}</span>` : ""}</span>`;
    b.onclick = () => openDetail(s.id);
    list.appendChild(b);
  });
  if (v.length > state.shown) {
    const a = document.createElement("a");
    a.className = "card card-more"; a.href = `${ROOT}city/${c.area.slug}/`;
    a.innerHTML = `<span class="card-body"><span class="card-name">ほか${v.length - state.shown}店</span><span class="card-meta">${esc(c.area.name)}の一覧で見る</span></span>`;
    list.appendChild(a);
  }
  if (!v.length) list.innerHTML = `<p class="fine">条件に合うお店がありません。</p>`;
  list.scrollLeft = 0;
  if (updateMap) ensureMap().then(() => syncShops(v));
}

// ---------- 地図（検索してから読み込む：最初の表示を軽くする） ----------
function load(tag, attrs) { return new Promise((ok, ng) => { const e = document.createElement(tag); Object.assign(e, attrs); e.onload = ok; e.onerror = ng; document.head.appendChild(e); }); }
function ensureMap() {
  if (mapLoading) return mapLoading;
  mapLoading = (async () => {
    const base = "https://unpkg.com/maplibre-gl@5/dist/maplibre-gl";
    try { await Promise.all([load("link", { rel: "stylesheet", href: base + ".css" }), load("script", { src: base + ".js" })]); }
    catch { $("#mapOff").hidden = false; $("#mapOff").textContent = "地図を読み込めませんでした"; return; }
    ml = new maplibregl.Map({ container: "map", style: CFG.mapStyle, center: [CFG.center.lng, CFG.center.lat], zoom: CFG.zoom, attributionControl: { compact: true }, dragRotate: false, cooperativeGestures: true });
    ml.touchZoomRotate.disableRotation();
    ml.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    await new Promise((ok) => ml.on("load", ok));
    const color = ["match", ["get", "genre"]]; DATA.genres.forEach((g) => color.push(g.id, g.color)); color.push("#495057");
    ml.addSource("shops", { type: "geojson", data: fc([]), cluster: true, clusterRadius: 40, clusterMaxZoom: 14 });
    ml.addLayer({ id: "clusters", type: "circle", source: "shops", filter: ["has", "point_count"], paint: { "circle-color": "#14284B", "circle-opacity": 0.85, "circle-stroke-color": "#fff", "circle-stroke-width": 2, "circle-radius": ["step", ["get", "point_count"], 14, 20, 18, 100, 23] } });
    ml.addLayer({ id: "cluster-count", type: "symbol", source: "shops", filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11.5, "text-font": ["Noto Sans Bold"] }, paint: { "text-color": "#fff" } });
    ml.addLayer({ id: "points", type: "circle", source: "shops", filter: ["!", ["has", "point_count"]], layout: { "circle-sort-key": ["-", 1, ["get", "older"]] },
      paint: { "circle-color": color, "circle-radius": ["case", ["==", ["get", "older"], 1], 5, 7], "circle-opacity": ["case", ["==", ["get", "older"], 1], 0.45, 1], "circle-stroke-color": "#fff", "circle-stroke-width": ["case", ["==", ["get", "older"], 1], 1, 2] } });
    ml.addLayer({ id: "selected", type: "circle", source: "shops", filter: ["==", ["get", "id"], ""], paint: { "circle-color": "rgba(0,0,0,0)", "circle-radius": 12, "circle-stroke-color": "#2C5FA8", "circle-stroke-width": 3 } });
    ml.addSource("meet", { type: "geojson", data: fc([]) });
    ml.addLayer({ id: "meet-lines", type: "line", source: "meet", filter: ["==", ["get", "kind"], "line"], paint: { "line-color": ["get", "color"], "line-width": 2, "line-dasharray": [2, 2], "line-opacity": 0.8 } });
    ml.addLayer({ id: "meet-pts", type: "circle", source: "meet", filter: ["!=", ["get", "kind"], "line"], paint: { "circle-color": ["get", "color"], "circle-radius": ["match", ["get", "kind"], "cand", 14, 12], "circle-stroke-color": "#fff", "circle-stroke-width": 2.5 } });
    ml.addLayer({ id: "meet-labels", type: "symbol", source: "meet", filter: ["!=", ["get", "kind"], "line"], layout: { "text-field": ["get", "label"], "text-size": 12, "text-font": ["Noto Sans Bold"], "text-allow-overlap": true }, paint: { "text-color": "#fff" } });
    ml.on("click", "clusters", async (e) => { const f = e.features[0]; const z = await ml.getSource("shops").getClusterExpansionZoom(f.properties.cluster_id); ml.easeTo({ center: f.geometry.coordinates, zoom: z }); });
    ml.on("click", "points", (e) => openDetail(e.features[0].properties.id));
    ml.on("click", "meet-pts", (e) => { const i = e.features[0].properties.cand; if (i !== undefined && i !== null && i !== "") { chooseCand(+i); fitTo(shopsOf(state.cands[+i]).filter((s) => s.lat)); } });
    ["clusters", "points", "meet-pts"].forEach((id) => { ml.on("mouseenter", id, () => (ml.getCanvas().style.cursor = "pointer")); ml.on("mouseleave", id, () => (ml.getCanvas().style.cursor = "")); });
  })();
  return mapLoading;
}
const fc = (features) => ({ type: "FeatureCollection", features });
function syncShops(v) {
  if (!ml || !ml.getSource("shops")) return;
  ml.getSource("shops").setData(fc(v.filter((s) => s.lat).map((s) => ({ type: "Feature", geometry: { type: "Point", coordinates: [s.lng, s.lat] }, properties: { id: s.id, genre: s.genre, older: s.older ? 1 : 0 } }))));
}
function drawMeet(ppl) {
  if (!ml || !ml.getSource("meet")) return;
  const feats = [], top = state.cands[0]?.area;
  ppl.forEach((n, k) => {
    const a = AREAS[AIDX[n]];
    if (top) feats.push({ type: "Feature", geometry: { type: "LineString", coordinates: [[a.lng, a.lat], [top.lng, top.lat]] }, properties: { kind: "line", color: PERSON[k].c } });
    feats.push({ type: "Feature", geometry: { type: "Point", coordinates: [a.lng, a.lat] }, properties: { kind: "person", color: PERSON[k].c, label: PERSON[k].k } });
  });
  state.cands.forEach((c, i) => feats.push({ type: "Feature", geometry: { type: "Point", coordinates: [c.area.lng, c.area.lat] }, properties: { kind: "cand", cand: i, color: BRAND_COLOR, label: String(i + 1) } }));
  ml.getSource("meet").setData(fc(feats));
}
function fitTo(pts) {
  if (!ml || !pts.length) return;
  const b = new maplibregl.LngLatBounds();
  pts.forEach((p) => b.extend([p.lng, p.lat]));
  ml.fitBounds(b, { padding: 36, maxZoom: 14, duration: 600 });
}
async function share() {
  const url = location.href;
  const text = `まんなか新店 北海道：${state.people.filter(Boolean).join("・")}のまんなかは「${state.cands[0]?.area.name}」`;
  try {
    if (navigator.share) await navigator.share({ title: "まんなか新店 北海道", text, url });
    else { await navigator.clipboard.writeText(url); toast("リンクをコピーしました。LINEなどに貼って送れます"); }
  } catch {}
}

// ---------- お店の詳細（リンクは文字とURLだけ。自動で紐づけたものは確度を必ず添える） ----------
const RISK = { "確認済み": ["ok", "✓ 運営が確認済み"], "確実": ["hi", "自動照合・確度 高（電話番号や住所が一致）"], "おそらく": ["mid", "⚠ 自動照合・確度 中（別のお店の可能性があります）"] };
const fbUrl = (s) => /\/issues\/new$/.test(CFG.feedbackFormUrl)
  ? `${CFG.feedbackFormUrl}?title=${encodeURIComponent(`[訂正] ${s.name}（${s.area}）`)}&body=${encodeURIComponent(`お店のID: ${s.id}\n\n間違っている点：\n\n正しい情報（わかれば）：\n`)}`
  : CFG.feedbackFormUrl;
function openDetail(id) {
  const s = DATA.shops.find((x) => x.id === id);
  if (!s) return;
  const g = GENRE[s.genre];
  if (ml && ml.getLayer("selected")) ml.setFilter("selected", ["==", ["get", "id"], s.id]);
  if (ml && s.lat) ml.easeTo({ center: [s.lng, s.lat], zoom: Math.max(ml.getZoom(), 15) });
  const linkBtn = (href, label, conf) => {
    const [cls, note] = RISK[conf] || ["mid", "⚠ 自動照合（未確認）"];
    return `<a class="btn link risk-${cls}" href="${esc(href)}" target="_blank" rel="noopener nofollow">${label}<small class="risk">${esc(note)}</small></a>`;
  };
  const ig = s.instagram
    ? linkBtn(`https://www.instagram.com/${encodeURIComponent(s.instagram)}/`, `📷 Instagram @${esc(s.instagram)}`, s.igConf)
    : `<a class="btn" href="https://www.google.com/search?q=${encodeURIComponent(s.name + " " + s.area + " instagram")}" target="_blank" rel="noopener">📷 Instagramを探す</a>`;
  const web = /^https?:\/\//.test(s.website || "") ? linkBtn(s.website, `🌐 公式サイト <span class="dom">${esc(new URL(s.website).hostname.replace(/^www\./, ""))}</span>`, s.webConf) : "";
  const tb = /^https:\/\/tabelog\.com\//.test(s.tabelog || "") ? linkBtn(s.tabelog, "🍽 食べログ", s.tbConf) : "";
  const auto = [s.igConf, s.webConf, s.tbConf].some((c) => c && c !== "確認済み");
  const warn = s.warn ? `<div class="warn">⚠ ${esc(s.warn)}（自動判定・未確認）${s.warnReason ? `<br><small>${esc(s.warnReason)}</small>` : ""}<br><small>お出かけ前に、お店の最新情報をご確認ください。</small></div>` : "";
  const city = AREAS[AIDX[s.area]];
  $("#detail").innerHTML = `
    <span class="badge" style="background:${g.color};color:#fff">${g.icon} ${esc(g.label)}</span>${isNew(s) ? '<span class="badge b-new">NEW</span>' : ""}
    <h2 id="dName">${esc(s.name)}</h2>
    <div class="addr">${esc(s.address)}</div>
    <dl class="facts"><dt>営業許可日</dt><dd>${fmt(s.permitDate)}（開店日の目安）</dd>${s.gyotai ? `<dt>業態</dt><dd>${esc(s.gyotai)}</dd>` : ""}
      <dt>市町</dt><dd><a href="${ROOT}city/${city.slug}/">${esc(s.area)}の新店一覧</a></dd></dl>
    <div class="btns"><a class="btn area" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(s.name + " " + s.address)}" target="_blank" rel="noopener">Googleマップで開く</a></div>
    ${warn}
    ${s.older ? `<div class="older-box">🕰 以前から営業しているお店の可能性があります<br><small>${esc(s.older)}。営業許可の取り直し（経営者の交代・移転・改装など）で載っている場合があります。</small></div>` : ""}
    <div class="links">${ig}${web}${tb}</div>
    ${auto ? `<p class="note risk-note">Instagram・公式サイト・食べログのリンクは、公開情報をもとにプログラムが自動で紐づけたものを含みます。別のお店につながっている場合があります。</p>` : ""}
    <div class="btns"><button class="btn" id="wentBtn" type="button">${went.has(s.id) ? "✓ 行った（取り消す）" : "行った！"}</button></div>
    ${CFG.feedbackFormUrl ? `<p class="note"><a href="${esc(fbUrl(s))}" target="_blank" rel="noopener">リンクの誤り・情報の訂正を知らせる</a></p>` : ""}`;
  $("#wentBtn").onclick = () => {
    went.has(s.id) ? went.delete(s.id) : went.add(s.id);
    store.set("mn-went", [...went]); if ($("#list") && state.cands.length) renderShops(false); openDetail(id);
  };
  $("#sheet").classList.add("on"); $("#scrim").classList.add("on"); $("#sheet").scrollTop = 0;
}
function closeDetail() { $("#sheet").classList.remove("on"); $("#scrim").classList.remove("on"); if (ml && ml.getLayer("selected")) ml.setFilter("selected", ["==", ["get", "id"], ""]); }
function fmt(d, short) { const [y, m, dd] = d.split("-").map(Number); return short ? `${y}/${m}/${dd}` : `${y}年${m}月${dd}日`; }
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("on"), 2600); }
