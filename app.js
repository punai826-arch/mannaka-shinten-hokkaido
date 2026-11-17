// まんなか新店 北海道 — 2〜4人の中間地点で、開店3年以内のお店を探す
const CFG = window.SITE_CONFIG;
if (CFG.feedbackFormUrl) { const a = document.getElementById("pocFb"); if (a) { a.href = CFG.feedbackFormUrl; a.hidden = false; } }
const RING = Object.fromEntries(CFG.rings.map((r) => [r.id, r]));
const PERSON = [{ k: "A", c: "#1F2A33" }, { k: "B", c: "#C2410C" }, { k: "C", c: "#0F766E" }, { k: "D", c: "#7C3AED" }];
const PAGE = 40;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

let DATA, AREAS, MIN, GENRE = {}, TODAY, AIDX = {};
const lastVisit = store.get("mn-last-visit", null);
const went = new Set(store.get("mn-went", []));
const state = { ring: "", genre: "", area: "", months: 36, newOnly: false, shown: PAGE, sel: null, people: [], cands: [], cand: null };
let ml = null;

init();
async function init() {
  const [shops, areas] = await Promise.all([fetch("data/shops.json").then((r) => r.json()), fetch("data/areas.json").then((r) => r.json())]);
  DATA = shops; AREAS = areas.areas; MIN = areas.minutes;
  AREAS.forEach((a, i) => (AIDX[a.name] = i));
  TODAY = new Date(DATA.today + "T00:00:00");
  DATA.genres.forEach((g) => (GENRE[g.id] = g));
  $("#generated").textContent = `データ作成：${DATA.generatedAt.slice(0, 10)}（${DATA.cutoff} 以降に許可されたお店 ${DATA.shops.length.toLocaleString()}店）`;
  store.set("mn-last-visit", DATA.generatedAt);

  buildRings(); buildList(); buildMeet();
  initMap();
  // 共有リンク（?p=札幌市,帯広市&bar=1）
  const q = new URLSearchParams(location.search);
  if (q.get("p")) {
    state.people = q.get("p").split(",").filter((n) => n in AIDX).slice(0, 4);
    $("#withBar").checked = q.get("bar") === "1";
    renderPeople();
    if (state.people.length >= 2) findMid();
  }
}

// ---------- エリア（リング） ----------
function buildRings() {
  const nav = $("#rings");
  const mk = (id, label, color) => {
    const b = document.createElement("button");
    b.className = "ring" + (state.ring === id ? " on" : "");
    b.dataset.r = id;
    b.innerHTML = `<i style="background:${color}"></i>${esc(label)}<span class="prog" data-prog="${id}"></span>`;
    b.onclick = () => selectRing(id);
    nav.appendChild(b);
  };
  mk("", "北海道全体", "#ffffff");
  CFG.rings.forEach((r) => mk(r.id, r.label, r.color));
  paintProgress();
}
function selectRing(id) {
  state.ring = id; state.area = ""; state.shown = PAGE;
  document.querySelectorAll(".ring").forEach((b) => b.classList.toggle("on", b.dataset.r === id));
  setAreaColor(id ? RING[id].color : CFG.rings[0].color);
  fillAreaSelect(); renderList();
  if (id) fitTo(DATA.shops.filter((s) => s.ring === id && s.lat)); else ml && ml.easeTo({ center: [CFG.center.lng, CFG.center.lat], zoom: CFG.zoom });
  switchTab("list");
}
function setAreaColor(c) {
  document.documentElement.style.setProperty("--area", c);
  document.querySelector('meta[name="theme-color"]').setAttribute("content", c);
}
function paintProgress() { // 行ったお店の数（リングの制覇マップ）
  const cnt = {};
  DATA.shops.forEach((s) => { if (went.has(s.id)) cnt[s.ring] = (cnt[s.ring] || 0) + 1; });
  document.querySelectorAll("[data-prog]").forEach((el) => {
    const n = el.dataset.prog ? cnt[el.dataset.prog] : Object.values(cnt).reduce((a, b) => a + b, 0);
    el.textContent = n ? `✓${n}` : "";
  });
}

// ---------- まんなかを探す ----------
function buildMeet() {
  $("#addPerson").onclick = () => { if (state.people.length < 4) { state.people.push(""); renderPeople(); } };
  $("#findMid").onclick = findMid;
  if (!state.people.length) state.people = ["", ""];
  renderPeople();
}
function areaOptions(sel) {
  return `<option value="">住んでいる市町を選ぶ</option>` + CFG.rings.map((r) =>
    `<optgroup label="${esc(r.label)}エリア">${AREAS.filter((a) => a.ring === r.id).sort((a, b) => b.pop - a.pop)
      .map((a) => `<option ${a.name === sel ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</optgroup>`).join("");
}
function renderPeople() {
  const box = $("#people");
  box.innerHTML = "";
  state.people.forEach((p, i) => {
    const d = document.createElement("div");
    d.className = "person";
    d.innerHTML = `<span class="who" style="background:${PERSON[i].c}">${PERSON[i].k}</span>
      <select aria-label="${PERSON[i].k}さんの市町">${areaOptions(p)}</select>
      <button class="iconbtn" type="button" title="現在地から選ぶ">📍</button>
      ${state.people.length > 2 ? `<button class="iconbtn" type="button" title="この人を外す">×</button>` : "<span></span>"}`;
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
function mealShops(area, withBar) {
  return DATA.shops.filter((s) => s.area === area && (withBar || s.genre !== "bar"));
}
function findMid() {
  const ppl = state.people.filter(Boolean);
  if (ppl.length < 2) return toast("2人以上の市町を選んでください");
  const withBar = $("#withBar").checked;
  const idx = ppl.map((n) => AIDX[n]);
  const cands = AREAS.map((a, j) => {
    const t = idx.map((i) => MIN[i][j]);
    const all = mealShops(a.name, withBar), fresh = all.filter((s) => !s.older).length;
    return { area: a, times: t, max: Math.max(...t), sum: t.reduce((x, y) => x + y, 0), shops: all.length, fresh, older: all.length - fresh };
  }).filter((c) => c.shops >= CFG.minShopsForCandidate)
    // 10分以内の差は同じとみなし、本当に新しい店（以前から営業の可能性がない店）の多い市町を上に
    .sort((a, b) => Math.floor(a.max / 10) - Math.floor(b.max / 10) || b.fresh - a.fresh || b.shops - a.shops || a.sum - b.sum);
  state.cands = cands.slice(0, 3);
  // 共有用のURL
  const q = new URLSearchParams({ p: ppl.join(",") });
  if (withBar) q.set("bar", "1");
  history.replaceState(null, "", `${location.pathname}?${q}`);
  renderMid(ppl);
  drawMeetLayers(ppl);
  if (state.cands[0]) chooseCand(0, false);
  const pts = [...ppl.map((n) => AREAS[AIDX[n]]), ...state.cands.map((c) => c.area)];
  fitTo(pts);
}
const hm = (m) => (m < 60 ? `${m}分` : `${Math.floor(m / 60)}時間${m % 60 ? (m % 60) + "分" : ""}`);
function renderMid(ppl) {
  const box = $("#midResult");
  if (!state.cands.length) { box.innerHTML = `<p class="note">候補が見つかりませんでした。「お酒の店も含める」を試してください。</p>`; return; }
  box.innerHTML = state.cands.map((c, i) => {
    const r = RING[c.area.ring];
    return `<div class="cand" style="--c:${r.color}" data-i="${i}">
      <h3><span><span class="rank">${i + 1}</span>${esc(c.area.name)}</span><small>${esc(r.label)}エリア・新店${c.fresh}店${c.older ? `<span class="olderCnt">＋以前から営業の可能性${c.older}店</span>` : ""}</small></h3>
      <div class="times">${c.times.map((t, k) => `<span class="time"><b style="color:${PERSON[k].c}">${PERSON[k].k}</b> ${t === 0 ? "地元" : hm(t)}</span>`).join("")}</div>
      <p class="note">一番遠い人で ${hm(c.max)}・全員の合計 ${hm(c.sum)}</p></div>`;
  }).join("") + `<div class="btns"><button class="btn area" id="share" type="button">この結果を共有する</button></div>
    <p class="note">車の所要時間の目安です（渋滞・積雪は含みません）。候補は食事・お茶の新店が${CFG.minShopsForCandidate}店以上ある市町です。</p>`;
  box.querySelectorAll(".cand").forEach((el) => (el.onclick = () => chooseCand(+el.dataset.i, true)));
  $("#share").onclick = share;
}
function chooseCand(i, go) {
  state.cand = i;
  document.querySelectorAll(".cand").forEach((el) => el.classList.toggle("sel", +el.dataset.i === i));
  const c = state.cands[i];
  state.area = c.area.name; state.ring = ""; state.genre = $("#withBar").checked ? "" : "nobar";
  setAreaColor(RING[c.area.ring].color);
  document.querySelectorAll(".ring").forEach((b) => b.classList.toggle("on", b.dataset.r === ""));
  fillAreaSelect(); paintChips(); renderList();
  if (go) { fitTo(DATA.shops.filter((s) => s.area === c.area.name && s.lat)); switchTab("list"); }
}
async function share() {
  const url = location.href;
  const text = `まんなか新店 北海道：${state.people.filter(Boolean).join("・")}のまんなかは「${state.cands[0]?.area.name}」`;
  try {
    if (navigator.share) await navigator.share({ title: "まんなか新店 北海道", text, url });
    else { await navigator.clipboard.writeText(url); toast("リンクをコピーしました。LINEなどに貼って送れます"); }
  } catch {}
}

// ---------- 新店一覧 ----------
function buildList() {
  const chips = $("#genreChips");
  const mk = (gid, label, color) => {
    const b = document.createElement("button");
    b.className = "chip"; b.dataset.g = gid; b._color = color;
    b.innerHTML = `${esc(label)}`;
    b.onclick = () => { state.genre = gid; state.shown = PAGE; paintChips(); renderList(); };
    chips.appendChild(b);
  };
  mk("", "すべて", "#1F2A33");
  mk("nobar", "食事・お茶", "#1F2A33");
  DATA.genres.forEach((g) => mk(g.id, `${g.icon} ${g.label}`, g.color));
  paintChips();
  fillAreaSelect();
  $("#areaSel").onchange = (e) => { state.area = e.target.value; state.shown = PAGE; renderList(); fitTo(visible().filter((s) => s.lat)); };
  $("#period").onchange = (e) => { state.months = +e.target.value; state.shown = PAGE; renderList(); };
  $("#newOnly").onchange = (e) => { state.newOnly = e.target.checked; state.shown = PAGE; renderList(); };
  $("#more").onclick = () => { state.shown += PAGE; renderList(false); };
  $("#tabMeet").onclick = () => switchTab("meet");
  $("#tabList").onclick = () => switchTab("list");
  renderList();
}
function fillAreaSelect() {
  const sel = $("#areaSel");
  const list = AREAS.filter((a) => !state.ring || a.ring === state.ring).sort((a, b) => b.pop - a.pop);
  sel.innerHTML = `<option value="">${state.ring ? RING[state.ring].label + "エリアのすべて" : "すべての市町"}</option>` +
    list.map((a) => `<option ${a.name === state.area ? "selected" : ""}>${esc(a.name)}</option>`).join("");
}
function paintChips() {
  document.querySelectorAll(".chip").forEach((c) => {
    const on = c.dataset.g === state.genre;
    c.classList.toggle("on", on); c.style.background = on ? c._color : "";
  });
}
function switchTab(t) {
  $("#tabMeet").classList.toggle("on", t === "meet"); $("#tabList").classList.toggle("on", t === "list");
  $("#tabMeet").setAttribute("aria-selected", t === "meet"); $("#tabList").setAttribute("aria-selected", t === "list");
  $("#paneMeet").hidden = t !== "meet"; $("#paneList").hidden = t !== "list";
}
const months = (d) => (TODAY - new Date(d + "T00:00:00")) / 864e5 / 30.44;
const isNew = (s) => lastVisit && !s.older && s.permitDate > lastVisit.slice(0, 10);
function visible() {
  return DATA.shops.filter((s) =>
    (!state.ring || s.ring === state.ring) && (!state.area || s.area === state.area) &&
    (!state.genre || (state.genre === "nobar" ? s.genre !== "bar" : s.genre === state.genre)) &&
    months(s.permitDate) <= state.months && (!state.newOnly || isNew(s)))
    .sort((a, b) => (a.older ? 1 : 0) - (b.older ? 1 : 0)); // 以前から営業の可能性がある店は後ろへ（同じ中では許可日の新しい順のまま）
}
function renderList(updateMap = true) {
  const v = visible();
  $("#count").textContent = `${v.length.toLocaleString()}店` + (state.area ? `（${state.area}）` : state.ring ? `（${RING[state.ring].label}エリア）` : "");
  $("#listCount").textContent = v.length.toLocaleString();
  const list = $("#list");
  list.innerHTML = "";
  v.slice(0, state.shown).forEach((s) => {
    const g = GENRE[s.genre], r = RING[s.ring];
    const b = document.createElement("button");
    b.className = "item" + (s.older ? " older" : "");
    b.innerHTML = `<div class="ico" style="background:${g.color}1f">${g.icon}</div>
      <div><h3>${isNew(s) ? '<span class="badge b-new">NEW</span>' : ""}${went.has(s.id) ? '<span class="badge b-went">行った</span>' : ""}${s.older ? '<span class="badge b-older">以前から営業？</span>' : ""}${esc(s.name)}</h3>
      <div class="meta"><span class="badge b-area" style="background:${r.color}">${esc(s.area)}</span>${esc(g.label)}${s.gyotai ? "・" + esc(s.gyotai) : ""}</div></div>
      <div class="when"><b>${fmt(s.permitDate, true)}</b>許可</div>`;
    b.onclick = () => openDetail(s.id);
    list.appendChild(b);
  });
  if (!v.length) list.innerHTML = `<p class="note">条件に合うお店がありません。</p>`;
  $("#more").hidden = v.length <= state.shown;
  if (updateMap) syncShops(v);
}

// ---------- 地図（MapLibre + OpenFreeMap） ----------
function load(tag, attrs) { return new Promise((ok, ng) => { const e = document.createElement(tag); Object.assign(e, attrs); e.onload = ok; e.onerror = ng; document.head.appendChild(e); }); }
async function initMap() {
  const base = "https://unpkg.com/maplibre-gl@5/dist/maplibre-gl";
  try { await Promise.all([load("link", { rel: "stylesheet", href: base + ".css" }), load("script", { src: base + ".js" })]); }
  catch { $("#mapOff").hidden = false; $("#mapOff").textContent = "地図を読み込めませんでした"; return; }
  ml = new maplibregl.Map({ container: "map", style: CFG.mapStyle, center: [CFG.center.lng, CFG.center.lat], zoom: CFG.zoom, attributionControl: { compact: true }, dragRotate: false });
  ml.touchZoomRotate.disableRotation();
  ml.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  ml.on("load", () => {
    const color = ["match", ["get", "genre"]]; DATA.genres.forEach((g) => color.push(g.id, g.color)); color.push("#495057");
    ml.addSource("shops", { type: "geojson", data: fc([]), cluster: true, clusterRadius: 42, clusterMaxZoom: 14 });
    ml.addLayer({ id: "clusters", type: "circle", source: "shops", filter: ["has", "point_count"], paint: { "circle-color": "#1F2A33", "circle-opacity": 0.8, "circle-stroke-color": "#fff", "circle-stroke-width": 2, "circle-radius": ["step", ["get", "point_count"], 14, 20, 18, 100, 23, 500, 29] } });
    ml.addLayer({ id: "cluster-count", type: "symbol", source: "shops", filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11.5, "text-font": ["Noto Sans Bold"] }, paint: { "text-color": "#fff" } });
    ml.addLayer({ id: "points", type: "circle", source: "shops", filter: ["!", ["has", "point_count"]], layout: { "circle-sort-key": ["-", 1, ["get", "older"]] }, // 新しい店を上に描く
      paint: { "circle-color": color, "circle-radius": ["case", ["==", ["get", "older"], 1], 5, 7], "circle-opacity": ["case", ["==", ["get", "older"], 1], 0.45, 1], "circle-stroke-color": "#fff", "circle-stroke-width": ["case", ["==", ["get", "older"], 1], 1, 2] } });
    ml.addLayer({ id: "selected", type: "circle", source: "shops", filter: ["==", ["get", "id"], ""], paint: { "circle-color": "rgba(0,0,0,0)", "circle-radius": 12, "circle-stroke-color": "#1F2A33", "circle-stroke-width": 3 } });
    // まんなか候補と、各自の市町
    ml.addSource("meet", { type: "geojson", data: fc([]) });
    ml.addLayer({ id: "meet-lines", type: "line", source: "meet", filter: ["==", ["get", "kind"], "line"], paint: { "line-color": ["get", "color"], "line-width": 2, "line-dasharray": [2, 2], "line-opacity": 0.8 } });
    ml.addLayer({ id: "meet-pts", type: "circle", source: "meet", filter: ["!=", ["get", "kind"], "line"], paint: { "circle-color": ["get", "color"], "circle-radius": ["match", ["get", "kind"], "cand", 14, 12], "circle-stroke-color": "#fff", "circle-stroke-width": 2.5 } });
    ml.addLayer({ id: "meet-labels", type: "symbol", source: "meet", filter: ["!=", ["get", "kind"], "line"], layout: { "text-field": ["get", "label"], "text-size": 12, "text-font": ["Noto Sans Bold"], "text-allow-overlap": true }, paint: { "text-color": "#fff" } });

    ml.on("click", "clusters", async (e) => { const f = e.features[0]; const z = await ml.getSource("shops").getClusterExpansionZoom(f.properties.cluster_id); ml.easeTo({ center: f.geometry.coordinates, zoom: z }); });
    ml.on("click", "points", (e) => openDetail(e.features[0].properties.id));
    ml.on("click", "meet-pts", (e) => { const i = e.features[0].properties.cand; if (i !== undefined && i !== null && i !== "") chooseCand(+i, true); });
    ["clusters", "points", "meet-pts"].forEach((id) => { ml.on("mouseenter", id, () => (ml.getCanvas().style.cursor = "pointer")); ml.on("mouseleave", id, () => (ml.getCanvas().style.cursor = "")); });
    syncShops(visible());
    if (state.cands.length) drawMeetLayers(state.people.filter(Boolean));
  });
}
const fc = (features) => ({ type: "FeatureCollection", features });
function syncShops(v) {
  if (!ml || !ml.getSource("shops")) return;
  ml.getSource("shops").setData(fc(v.filter((s) => s.lat).map((s) => ({ type: "Feature", geometry: { type: "Point", coordinates: [s.lng, s.lat] }, properties: { id: s.id, genre: s.genre, older: s.older ? 1 : 0 } }))));
}
function drawMeetLayers(ppl) {
  if (!ml || !ml.getSource("meet")) return;
  const feats = [];
  const top = state.cands[0]?.area;
  ppl.forEach((n, k) => {
    const a = AREAS[AIDX[n]];
    if (top) feats.push({ type: "Feature", geometry: { type: "LineString", coordinates: [[a.lng, a.lat], [top.lng, top.lat]] }, properties: { kind: "line", color: PERSON[k].c } });
    feats.push({ type: "Feature", geometry: { type: "Point", coordinates: [a.lng, a.lat] }, properties: { kind: "person", color: PERSON[k].c, label: PERSON[k].k } });
  });
  state.cands.forEach((c, i) => feats.push({ type: "Feature", geometry: { type: "Point", coordinates: [c.area.lng, c.area.lat] }, properties: { kind: "cand", cand: i, color: RING[c.area.ring].color, label: String(i + 1) } }));
  ml.getSource("meet").setData(fc(feats));
}
function fitTo(pts) {
  if (!ml || !pts.length) return;
  const b = new maplibregl.LngLatBounds();
  pts.forEach((p) => b.extend([p.lng, p.lat]));
  ml.fitBounds(b, { padding: 50, maxZoom: 15, duration: 600 });
}

// ---------- お店の詳細 ----------
// GitHubのIssueで受け付けるときは、店名とIDを件名・本文に入れておく
const fbUrl = (s) => /\/issues\/new$/.test(CFG.feedbackFormUrl)
  ? `${CFG.feedbackFormUrl}?title=${encodeURIComponent(`[訂正] ${s.name}（${s.area}）`)}&body=${encodeURIComponent(`お店のID: ${s.id}\n\n間違っている点：\n\n正しい情報（わかれば）：\n`)}`
  : CFG.feedbackFormUrl;
function openDetail(id) {
  const s = DATA.shops.find((x) => x.id === id);
  if (!s) return;
  const g = GENRE[s.genre], r = RING[s.ring];
  setAreaColor(r.color);
  if (ml && ml.getLayer("selected")) ml.setFilter("selected", ["==", ["get", "id"], s.id]);
  if (ml && s.lat) ml.easeTo({ center: [s.lng, s.lat], zoom: Math.max(ml.getZoom(), 15) });
  // リンクは文字とURLだけ。自動で紐づけたものは確度（リスク）を必ず添える
  const RISK = {
    "確認済み": ["ok", "✓ 運営が確認済み"],
    "確実": ["hi", "自動照合・確度 高（電話番号や住所が一致）"],
    "おそらく": ["mid", "⚠ 自動照合・確度 中（別のお店の可能性があります）"],
  };
  const linkBtn = (href, label, conf) => {
    const [cls, note] = RISK[conf] || ["mid", "⚠ 自動照合（未確認）"];
    return `<a class="btn link risk-${cls}" href="${esc(href)}" target="_blank" rel="noopener nofollow">${label}<small class="risk">${esc(note)}</small></a>`;
  };
  const ig = s.instagram
    ? linkBtn(`https://www.instagram.com/${encodeURIComponent(s.instagram)}/`, `📷 Instagram @${esc(s.instagram)}`, s.igConf)
    : `<a class="btn" href="https://www.google.com/search?q=${encodeURIComponent(s.name + " " + s.area + " instagram")}" target="_blank" rel="noopener">📷 Instagramを探す</a>`;
  const web = /^https?:\/\//.test(s.website || "")
    ? linkBtn(s.website, `🌐 公式サイト <span class="dom">${esc(new URL(s.website).hostname.replace(/^www\./, ""))}</span>`, s.webConf) : "";
  const tb = /^https:\/\/tabelog\.com\//.test(s.tabelog || "")
    ? linkBtn(s.tabelog, "🍽 食べログ", s.tbConf) : "";
  const auto = [s.igConf, s.webConf, s.tbConf].some((c) => c && c !== "確認済み");
  const warn = s.warn
    ? `<div class="warn">⚠ ${esc(s.warn)}（自動判定・未確認）${s.warnReason ? `<br><small>${esc(s.warnReason)}</small>` : ""}<br><small>お出かけ前に、お店の最新情報をご確認ください。</small></div>` : "";
  $("#detail").innerHTML = `
    <span class="badge b-area" style="background:${r.color}">${esc(r.label)}エリア</span><span class="badge" style="background:${g.color};color:#fff">${g.icon} ${esc(g.label)}</span>${isNew(s) ? '<span class="badge b-new">NEW</span>' : ""}
    <h2 id="dName">${esc(s.name)}</h2>
    <div class="addr">${esc(s.address)}</div>
    <dl class="facts">
      <dt>営業許可日</dt><dd>${fmt(s.permitDate)}（開店日の目安）</dd>
      ${s.gyotai ? `<dt>業態</dt><dd>${esc(s.gyotai)}</dd>` : ""}
      <dt>市町</dt><dd>${esc(s.area)}</dd>
    </dl>
    <div class="btns"><a class="btn area" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(s.name + " " + s.address)}" target="_blank" rel="noopener">Googleマップで開く</a></div>
    ${warn}
    ${s.older ? `<div class="older-box">🕰 以前から営業しているお店の可能性があります<br><small>${esc(s.older)}。営業許可の取り直し（経営者の交代・移転・改装など）で一覧に載っている場合があります。</small></div>` : ""}
    <div class="links">${ig}${web}${tb}</div>
    ${auto ? `<p class="note risk-note">Instagram・公式サイト・食べログのリンクは、公開情報をもとにプログラムが自動で紐づけたものを含みます。別のお店につながっている場合があります。</p>` : ""}
    <div class="btns"><button class="btn" id="wentBtn" type="button">${went.has(s.id) ? "✓ 行った（取り消す）" : "行った！"}</button></div>
    ${s.lat ? "" : `<p class="note">位置情報がないため、地図にはピンを出していません。</p>`}
    ${CFG.feedbackFormUrl ? `<p class="note"><a href="${esc(fbUrl(s))}" target="_blank" rel="noopener">リンクの誤り・情報の訂正を知らせる</a></p>` : ""}`;
  $("#wentBtn").onclick = () => {
    went.has(s.id) ? went.delete(s.id) : went.add(s.id);
    store.set("mn-went", [...went]); paintProgress(); renderList(false); openDetail(id);
    if (went.has(s.id)) toast(`${r.label}エリアの記録に追加しました`);
  };
  $("#sheet").classList.add("on"); $("#scrim").classList.add("on"); $("#sheet").scrollTop = 0;
}
function closeDetail() { $("#sheet").classList.remove("on"); $("#scrim").classList.remove("on"); if (ml && ml.getLayer("selected")) ml.setFilter("selected", ["==", ["get", "id"], ""]); }
$("#close").onclick = closeDetail; $("#scrim").onclick = closeDetail;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });

function fmt(d, short) { const [y, m, dd] = d.split("-").map(Number); return short ? `${y}/${m}/${dd}` : `${y}年${m}月${dd}日`; }
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("on"), 2600); }
