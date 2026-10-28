/* Nebosvit alert map card: oblasts of Ukraine coloured by the current air raid alerts.
 * Config: type: custom:nebosvit-map-card, entity: sensor.<place>_alert_map,
 *         highlight: "15" (oblast id to outline), title: optional.
 */
// Oblast outlines are loaded on demand (87 KB), so the card elements are defined at once
// and the dashboard never has to wait for them.
// Assets live next to this file; the release version in our own URL busts the browser cache.
const asset = (name) => { const u = new URL(name, import.meta.url); u.search = new URL(import.meta.url).search; return u; };
let MAP = { w: 1198.7, h: 798.9, r: {} };
const mapReady = fetch(asset("regions/oblasts.json"))
  .then((r) => r.json())
  .then((j) => { MAP = j; })
  .catch(() => {});

// English is the base; Ukrainian and Russian are translations. Anything else falls back to English.
const langOf = (hass) => { const l = ((hass && hass.language) || "en").toLowerCase(); return l.startsWith("uk") ? "uk" : l.startsWith("ru") ? "ru" : "en"; };
const LOCALES = { en: [], uk: "uk-UA", ru: "ru-RU" };
const timeFmt = (d, hass) => new Date(d).toLocaleTimeString(LOCALES[langOf(hass)], { hour: "2-digit", minute: "2-digit" });


// "data received N ago": Home Assistant bumps last_reported on every poll, last_updated only when data changes.
const reportedAt = (st) => (st ? new Date(st.last_reported || st.last_updated).getTime() : NaN);
const agoText = (ms, u) => {
  const sec = Math.max(0, Math.round(ms / 1000));
  if (sec < 60) return `${sec} ${u.s}`;
  const min = Math.round(sec / 60);
  return min < 60 ? `${min} ${u.m}` : `${Math.round(min / 60)} ${u.h}`;
};
const AGO = {
  en: { fmt: (t) => `data received ${t} ago`, s: "s", m: "min", h: "h" },
  uk: { fmt: (t) => `дані отримано ${t} тому`, s: "с", m: "хв", h: "год" },
  ru: { fmt: (t) => `данные получены ${t} назад`, s: "с", m: "мин", h: "ч" },
};
function paintAgo(el, st, hass) {
  const at = reportedAt(st);
  if (!el) return;
  if (isNaN(at)) { el.textContent = ""; return; }
  const lang = AGO[langOf(hass)], age = Date.now() - at;
  el.textContent = lang.fmt(agoText(age, lang));
  el.classList.toggle("old", age > 3 * 60 * 1000);   // the poll runs every 30 s: three minutes means it is stuck
}
function everyTenSeconds(self, fn) {
  self._agoTimer = setInterval(fn, 10000);
}

// Small, optional "get the app" line under the cards; shown only with `promo: true` until the
// apps have public store pages (the old link pointed at a private repository).
const APP_URL = "https://github.com/symonovserhii/nebosvit-homeassistant";
const PROMO = {
  en: "Nebosvit app for iOS and Android",
  uk: "Застосунок «Небосвіт» для iOS і Android",
  ru: "Приложение «Небосвит» для iOS и Android",
};
function paintPromo(el, config, hass) {
  if (!el) return;
  if (config.promo !== true) { el.style.display = "none"; return; }
  el.style.display = "";
  el.innerHTML = "";
  const a = document.createElement("a");
  a.href = APP_URL; a.target = "_blank"; a.rel = "noopener";
  a.textContent = PROMO[langOf(hass)];
  el.appendChild(a);
}

const LABELS = {
  en: { clear: "Clear", yellow: "Threat", red: "Alert", partial: "partial", whole: "whole oblast",
        none: "No alerts", some: (n) => `Alerts in oblasts: ${n}`, someHromadas: (n) => `Alerts in hromadas: ${n}`,
        mine: "Your region", noData: "No data", updated: "updated", title: "Alert map", titleHromadas: "Ukraine by hromada" },
  uk: { clear: "Тихо", yellow: "Загроза", red: "Тривога", partial: "частково", whole: "вся область",
        none: "Тривог немає", some: (n) => `Тривога в областях: ${n}`, someHromadas: (n) => `Тривога в громадах: ${n}`,
        mine: "Ваш регіон", noData: "Немає даних", updated: "оновлено", title: "Мапа тривог", titleHromadas: "Україна за громадами" },
  ru: { clear: "Тихо", yellow: "Угроза", red: "Тревога", partial: "частично", whole: "вся область",
        none: "Тревог нет", some: (n) => `Тревога в областях: ${n}`, someHromadas: (n) => `Тревога в громадах: ${n}`,
        mine: "Ваш регион", noData: "Нет данных", updated: "обновлено", title: "Карта тревог", titleHromadas: "Украина по громадам" },
};

class NebosvitMapCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("entity is required");
    this._config = config;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `
        <style>
          ha-card { display: block; overflow: hidden; }
          .head { display: flex; justify-content: space-between; align-items: baseline; padding: 14px 16px 0; }
          .title { font-size: 1.1rem; font-weight: 500; }
          .sum { font-size: 0.9rem; opacity: 0.85; }
          .sum.alert { color: var(--nb-red); font-weight: 600; }
          svg { display: block; width: 100%; height: auto; padding: 8px 8px 0; box-sizing: border-box; }
          .oblast { stroke: var(--card-background-color, #1c1c1c); stroke-width: 1.6; stroke-linejoin: round;
                    transition: fill .4s ease; cursor: default; }
          .oblast:hover { stroke: var(--primary-text-color); stroke-width: 2.2; }
          .clear { fill: var(--nb-clear); }
          .yellow { fill: var(--nb-yellow); }
          .red { fill: var(--nb-red); }
          .partial.yellow { fill: url(#hatch-yellow); }
          .partial.red { fill: url(#hatch-red); }
          .red.whole { animation: pulse 2.2s ease-in-out infinite; }
          .mine { stroke: var(--primary-text-color); stroke-width: 3; }
          .raion { fill: none; stroke: color-mix(in srgb, var(--primary-text-color) 45%, transparent); stroke-width: 2.4; stroke-linejoin: round; }
          .zoom { stroke-width: 0.5; }
          .oblast-border { stroke-width: 1.8; }
          .lbl { font-size: 15px; fill: var(--primary-text-color); opacity: .0; pointer-events: none; text-anchor: middle; }
          svg:hover .lbl { opacity: .0; }
          .oblast:hover + .lbl { opacity: .95; }
          .legend { display: flex; gap: 14px; flex-wrap: wrap; padding: 6px 16px 14px; font-size: .8rem; opacity: .9; }
          .legend span { display: inline-flex; align-items: center; gap: 6px; }
          .sw { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
          .stale { padding: 0 16px 10px; font-size: .75rem; opacity: .6; }
          .stale.old { color: var(--nb-yellow); opacity: 1; }
          .promo { padding: 0 16px 12px; font-size: .72rem; opacity: .55; }
          .promo a { color: inherit; text-decoration: none; border-bottom: 1px dotted currentColor; }
          @keyframes pulse { 0%,100% { filter: brightness(1); } 50% { filter: brightness(1.35); } }
          :host { --nb-clear: color-mix(in srgb, var(--primary-text-color) 12%, var(--card-background-color, #1c1c1c));
                  --nb-yellow: #f2b705; --nb-red: #e5383b; }
        </style>
        <ha-card>
          <div class="head"><div class="title"></div><div class="sum"></div></div>
          <svg viewBox="0 0 ${MAP.w} ${MAP.h}" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <pattern id="hatch-red" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="9" height="9" fill="var(--nb-clear)"/><rect width="4.5" height="9" fill="var(--nb-red)"/></pattern>
              <pattern id="hatch-yellow" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="9" height="9" fill="var(--nb-clear)"/><rect width="4.5" height="9" fill="var(--nb-yellow)"/></pattern>
            </defs>
            <g class="regions"></g>
          </svg>
          <div class="legend"></div>
          <div class="stale"></div>
          <div class="promo"></div>
        </ha-card>`;
      this._zoomMap = null;
      const g = this._root.querySelector(".regions");
      if (config.detail === "hromada") { this._loadZoom("ua"); }
      else if (config.zoom) { this._loadZoom(config.zoom); }
      else mapReady.then(() => {
        for (const [id, r] of Object.entries(MAP.r)) {
          const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
          p.setAttribute("d", r.d); p.setAttribute("class", "oblast clear"); p.dataset.id = id;
          const t = document.createElementNS("http://www.w3.org/2000/svg", "title");
          p.appendChild(t); g.appendChild(p);
        }
        if (this._hass) this.hass = this._hass;
      });
    }
  }

  set hass(hass) {
    this._hass = hass;
    const L = LABELS[langOf(hass)];
    const st = hass.states[this._config.entity];
    const root = this._root;
    root.querySelector(".title").textContent = this._config.title || this._defaultTitle(L);
    const levels = (st && st.attributes && st.attributes.oblasts) || {};
    const known = st && st.state !== "unavailable" && st.state !== "unknown";
    let alerted = [];
    this._st = st;
    paintAgo(root.querySelector(".stale"), st, hass);
    paintPromo(root.querySelector(".promo"), this._config, hass);
    if (this._config.zoom || this._config.detail === "hromada") { this._paintZoom(st, known, L, root); return; }
    root.querySelectorAll(".oblast").forEach((p) => {
      const id = p.dataset.id, info = levels[id], name = MAP.r[id].n;
      const level = known && info ? info.level : "clear";
      const whole = !!(info && info.whole);
      p.setAttribute("class", `oblast ${level}${level !== "clear" ? (whole ? " whole" : " partial") : ""}${id === String(this._config.highlight) ? " mine" : ""}`);
      let text = `${name}: ${L[level]}`;
      if (level !== "clear") { text += ` (${whole ? L.whole : L.partial})`; alerted.push(name); }
      if (id === String(this._config.highlight)) text += `\n★ ${L.mine}`;
      p.querySelector("title").textContent = text;
    });
    const sum = root.querySelector(".sum");
    if (!known) { sum.textContent = L.noData; sum.className = "sum"; }
    else if (alerted.length) { sum.textContent = L.some(alerted.length); sum.className = "sum alert"; }
    else { sum.textContent = L.none; sum.className = "sum"; }
    root.querySelector(".legend").innerHTML =
      `<span><i class="sw" style="background:var(--nb-clear)"></i>${L.clear}</span>` +
      `<span><i class="sw" style="background:var(--nb-yellow)"></i>${L.yellow}</span>` +
      `<span><i class="sw" style="background:var(--nb-red)"></i>${L.red}</span>` +
      `<span><i class="sw" style="background:repeating-linear-gradient(45deg,var(--nb-red) 0 3px,var(--nb-clear) 3px 6px)"></i>${L.partial}</span>`;
  }

  async _loadZoom(oblastId) {
    await mapReady;
    try {
      const res = await fetch(asset(`regions/${oblastId}.json`));
      this._zoomMap = await res.json();
    } catch (e) { return; }
    const svg = this._root.querySelector("svg"), g = this._root.querySelector(".regions");
    svg.setAttribute("viewBox", `0 0 ${this._zoomMap.w} ${this._zoomMap.h}`);
    g.innerHTML = "";
    const national = oblastId === "ua";
    const mk = (cls, id, r) => {
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", r.d); p.setAttribute("class", cls); p.dataset.id = id;
      const t = document.createElementNS("http://www.w3.org/2000/svg", "title"); p.appendChild(t); g.appendChild(p); return p;
    };
    // Hromadas are the coloured cells; raion borders are drawn over them.
    for (const [id, r] of Object.entries(this._zoomMap.r)) if (national || r.k === 3) mk("oblast clear zoom", id, r);
    if (national) for (const [id, r] of Object.entries(MAP.r)) mk("raion oblast-border", "b" + id, r).style.pointerEvents = "none";
    else for (const [id, r] of Object.entries(this._zoomMap.r)) if (r.k === 2) mk("raion", id, r).style.pointerEvents = "none";
    if (this._hass) this.hass = this._hass;
  }

  _paintZoom(st, known, L, root) {
    if (!this._zoomMap) return;
    const attrs = (st && st.attributes) || {}, regions = attrs.regions || {}, oblasts = attrs.oblasts || {};
    root.querySelectorAll(".oblast.zoom").forEach((p) => {
      const id = p.dataset.id, r = this._zoomMap.r[id];
      const own = oblasts[String(r.o || this._config.zoom)];
      const whole = own && own.whole ? own.level : null;
      const level = !known ? "clear" : (regions[id] && regions[id].level) || (regions[r.p] && regions[r.p].level) || whole || "clear";
      p.setAttribute("class", `oblast zoom ${level}${id === String(this._config.highlight) ? " mine" : ""}`);
      let text = `${r.n}: ${L[level]}`;
      if (id === String(this._config.highlight)) text += `\n★ ${L.mine}`;
      p.querySelector("title").textContent = text;
    });
    const sum = root.querySelector(".sum");
    if (!known) { sum.textContent = L.noData; sum.className = "sum"; }
    else { sum.textContent = ""; sum.className = "sum"; }
    root.querySelector(".legend").innerHTML =
      `<span><i class="sw" style="background:var(--nb-clear)"></i>${L.clear}</span>` +
      `<span><i class="sw" style="background:var(--nb-yellow)"></i>${L.yellow}</span>` +
      `<span><i class="sw" style="background:var(--nb-red)"></i>${L.red}</span>`;
  }

  connectedCallback() { everyTenSeconds(this, () => this._hass && paintAgo(this._root.querySelector(".stale"), this._st, this._hass)); }
  disconnectedCallback() { clearInterval(this._agoTimer); }

  _defaultTitle(L) {
    const c = this._config;
    if (c.detail === "hromada") return L.titleHromadas;
    if (c.zoom && MAP.r[String(c.zoom)]) return MAP.r[String(c.zoom)].n;
    return L.title;
  }

  getCardSize() { return 7; }
}

customElements.define("nebosvit-map-card", NebosvitMapCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "nebosvit-map-card", name: "Nebosvit alert map", description: "Ukraine oblasts coloured by air raid alerts" });

/* ---------- Status card with a 24 h timeline ---------- */
const S_LABELS = {
  en: { clear: "Clear", yellow: "Threat", red: "Alert", since: "since", last: "Last alert", ago: "ago",
        none24: "No alerts in the last 24 h", count: (n) => `Alerts in 24 h: ${n}`, total: "Total", h: "h", m: "min",
        types: { none: "None", air: "Air raid", artillery: "Artillery threat", urban_fights: "Street fighting",
                 chemical: "Chemical hazard", nuclear: "Radiation hazard", unknown: "Danger" },
        history: "Last 24 hours", noData: "No data", now: "now" },
  uk: { clear: "Тихо", yellow: "Загроза", red: "Тривога", since: "з", last: "Остання тривога", ago: "тому",
        none24: "За добу тривог не було", count: (n) => `Тривог за добу: ${n}`, total: "Загалом", h: "год", m: "хв",
        types: { none: "Немає", air: "Повітряна тривога", artillery: "Загроза артобстрілу", urban_fights: "Вуличні бої",
                 chemical: "Хімічна небезпека", nuclear: "Радіаційна небезпека", unknown: "Небезпека" },
        history: "Остання доба", noData: "Немає даних", now: "зараз" },
  ru: { clear: "Тихо", yellow: "Угроза", red: "Тревога", since: "с", last: "Последняя тревога", ago: "назад",
        none24: "За сутки тревог не было", count: (n) => `Тревог за сутки: ${n}`, total: "Всего", h: "ч", m: "мин",
        types: { none: "Нет", air: "Воздушная тревога", artillery: "Угроза артобстрела", urban_fights: "Уличные бои",
                 chemical: "Химическая опасность", nuclear: "Радиационная опасность", unknown: "Опасность" },
        history: "Последние сутки", noData: "Нет данных", now: "сейчас" },
};
const ICONS = { clear: "mdi:shield-check", yellow: "mdi:alert", red: "mdi:alarm-light", unknown: "mdi:help-circle-outline" };

class NebosvitStatusCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("entity (alert level sensor) is required");
    this._config = config;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `
        <style>
          :host { --nb-clear: #2e9d57; --nb-yellow: #f2b705; --nb-red: #e5383b;
                  --nb-track: color-mix(in srgb, var(--primary-text-color) 10%, var(--card-background-color, #1c1c1c)); }
          ha-card { display: block; padding: 16px; overflow: hidden; position: relative; }
          .tint { position: absolute; inset: 0; opacity: .10; background: var(--nb-c); pointer-events: none; transition: background .4s; }
          .row { display: flex; align-items: center; gap: 16px; position: relative; }
          .badge { width: 60px; height: 60px; border-radius: 50%; flex: none; display: grid; place-items: center;
                   background: color-mix(in srgb, var(--nb-c) 22%, transparent); color: var(--nb-c); transition: all .4s; }
          .badge ha-icon { --mdc-icon-size: 34px; }
          .badge.red { animation: ring 1.8s ease-out infinite; }
          .place { font-size: .8rem; letter-spacing: .06em; text-transform: uppercase; opacity: .65; }
          .state { font-size: 1.9rem; font-weight: 600; line-height: 1.15; color: var(--nb-c); }
          .sub { font-size: .92rem; opacity: .85; margin-top: 2px; }
          .tl { margin-top: 18px; position: relative; }
          .tl-head { display: flex; justify-content: space-between; font-size: .75rem; opacity: .65; margin-bottom: 6px; }
          .bar { position: relative; height: 22px; border-radius: 8px; background: var(--nb-track); overflow: hidden; }
          .seg { position: absolute; top: 0; bottom: 0; min-width: 2px; }
          .seg.yellow { background: var(--nb-yellow); } .seg.red { background: var(--nb-red); }
          .grid { position: absolute; top: 0; bottom: 0; width: 1px; background: color-mix(in srgb, var(--primary-text-color) 18%, transparent); }
          .ticks { position: relative; height: 16px; margin-top: 4px; font-size: .7rem; opacity: .6; }
          .ticks span { position: absolute; transform: translateX(-50%); }
          .stale { margin-top: 10px; font-size: .75rem; opacity: .6; }
          .promo { margin-top: 4px; font-size: .72rem; opacity: .55; }
          .promo a { color: inherit; text-decoration: none; border-bottom: 1px dotted currentColor; }
          .stale.old { color: var(--nb-yellow); opacity: 1; }
          .stats { margin-top: 8px; font-size: .82rem; opacity: .85; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
          @keyframes ring { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--nb-red) 55%, transparent); }
                            100% { box-shadow: 0 0 0 16px transparent; } }
        </style>
        <ha-card><div class="tint"></div>
          <div class="row"><div class="badge"><ha-icon></ha-icon></div>
            <div><div class="place"></div><div class="state"></div><div class="sub"></div></div></div>
          <div class="tl"><div class="tl-head"><span class="tl-title"></span><span class="tl-count"></span></div>
            <div class="bar"></div><div class="ticks"></div><div class="stats"></div></div>
          <div class="stale"></div>
          <div class="promo"></div>
        </ha-card>`;
    }
  }

  set hass(hass) {
    this._hass = hass;
    const L = S_LABELS[langOf(hass)];
    this._L = L;
    const c = this._config, root = this._root;
    const lvl = hass.states[c.entity];
    const level = lvl && ["clear", "yellow", "red"].includes(lvl.state) ? lvl.state : "unknown";
    const type = c.type_entity && hass.states[c.type_entity] ? hass.states[c.type_entity].state : "none";
    const since = c.since_entity && hass.states[c.since_entity] ? hass.states[c.since_entity].state : null;
    const color = { clear: "var(--nb-clear)", yellow: "var(--nb-yellow)", red: "var(--nb-red)", unknown: "var(--secondary-text-color)" }[level];
    root.host.style.setProperty("--nb-c", color);
    root.querySelector(".badge").className = `badge ${level}`;
    root.querySelector("ha-icon").setAttribute("icon", ICONS[level]);
    root.querySelector(".place").textContent = c.title || (lvl && (lvl.attributes.region || lvl.attributes.friendly_name)) || "";
    root.querySelector(".state").textContent = level === "unknown" ? L.noData : L[level];
    let sub = "";
    if (level !== "clear" && level !== "unknown") {
      sub = L.types[type] || L.types.unknown;
      const t = since ? new Date(since) : null;
      if (t && !isNaN(t)) sub += ` · ${L.since} ${timeFmt(t, this._hass)} (${this._dur(Date.now() - t)})`;
    }
    root.querySelector(".sub").textContent = sub;
    this._st = lvl;
    paintAgo(root.querySelector(".stale"), lvl, hass);
    paintPromo(root.querySelector(".promo"), c, hass);
    // History is refetched at most once a minute, or when the level changes.
    const key = `${level}`;
    if (!this._lastFetch || Date.now() - this._lastFetch > 60000 || this._lastKey !== key) {
      this._lastFetch = Date.now(); this._lastKey = key;
      this._loadHistory();
    }
  }

  _dur(ms) {
    const L = this._L, min = Math.max(0, Math.round(ms / 60000)), h = Math.floor(min / 60), m = min % 60;
    return h ? `${h} ${L.h} ${m} ${L.m}` : `${m} ${L.m}`;
  }

  async _loadHistory() {
    const hass = this._hass, id = this._config.entity, L = this._L;
    const end = new Date(), start = new Date(end.getTime() - 24 * 3600 * 1000);
    let rows = [];
    try {
      const res = await hass.callWS({ type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(),
        entity_ids: [id], include_start_time_state: true, significant_changes_only: false, minimal_response: true, no_attributes: true });
      rows = res[id] || [];
    } catch (e) { /* the card still shows the current state */ }
    const segs = [];
    rows.forEach((r, i) => {
      const t0 = Math.max(start.getTime(), (r.lu || r.last_updated_ts || 0) * 1000);
      const next = rows[i + 1];
      const t1 = next ? (next.lu || next.last_updated_ts) * 1000 : end.getTime();
      const s = r.s || r.state;
      if ((s === "yellow" || s === "red") && t1 > t0) segs.push({ s, t0, t1 });
    });
    const span = end - start, bar = this._root.querySelector(".bar");
    bar.innerHTML = "";
    for (let h = 6; h < 24; h += 6) { const g = document.createElement("i"); g.className = "grid"; g.style.left = `${(h / 24) * 100}%`; bar.appendChild(g); }
    const fmt = (t) => timeFmt(t, hass);
    segs.forEach((g) => {
      const d = document.createElement("div"); d.className = `seg ${g.s}`;
      d.style.left = `${((g.t0 - start) / span) * 100}%`; d.style.width = `${((g.t1 - g.t0) / span) * 100}%`;
      d.title = `${L[g.s]}: ${fmt(g.t0)}–${fmt(g.t1)} (${this._dur(g.t1 - g.t0)})`; bar.appendChild(d);
    });
    // Hour ticks: every 6 h counted back from now.
    const ticks = this._root.querySelector(".ticks"); ticks.innerHTML = "";
    for (let back = 24; back >= 0; back -= 6) {
      const t = end.getTime() - back * 3600 * 1000, sp = document.createElement("span");
      sp.style.left = `${100 - (back / 24) * 100}%`;
      sp.textContent = back === 0 ? L.now : timeFmt(t, hass);
      if (back === 24) sp.style.transform = "none"; if (back === 0) sp.style.transform = "translateX(-100%)";
      ticks.appendChild(sp);
    }
    const alerts = segs.filter((g) => g.s === "red" || g.s === "yellow");
    const total = alerts.reduce((a, g) => a + (g.t1 - g.t0), 0);
    const root = this._root;
    root.querySelector(".tl-title").textContent = L.history;
    root.querySelector(".tl-count").textContent = alerts.length ? L.count(this._episodes(segs)) : "";
    const stats = root.querySelector(".stats");
    if (!alerts.length) stats.innerHTML = `<span>${L.none24}</span>`;
    else {
      const last = alerts[alerts.length - 1];
      const lastTxt = this._lastKey === "clear" ? `${L.last}: ${this._dur(end - last.t1)} ${L.ago}` : "";
      stats.innerHTML = `<span>${L.total}: ${this._dur(total)}</span><span>${lastTxt}</span>`;
    }
  }

  // Adjacent yellow/red segments belong to one alert episode.
  _episodes(segs) {
    let n = 0, prevEnd = -Infinity;
    segs.forEach((g) => { if (g.t0 - prevEnd > 60000) n += 1; prevEnd = g.t1; });
    return n;
  }

  connectedCallback() { everyTenSeconds(this, () => this._hass && paintAgo(this._root.querySelector(".stale"), this._st, this._hass)); }
  disconnectedCallback() { clearInterval(this._agoTimer); }

  getCardSize() { return 4; }
}
customElements.define("nebosvit-status-card", NebosvitStatusCard);
window.customCards.push({ type: "nebosvit-status-card", name: "Nebosvit status", description: "Alert level with 24 h timeline" });
