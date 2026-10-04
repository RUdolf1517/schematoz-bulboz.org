/* schematoz-bulboz.org — клиент. Без фреймворков: страница = функция в PAGES.
   Весь пользовательский текст выводится через esc() / textContent. */
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const plural = (n, one, few, many) => { const m10 = n % 10, m100 = n % 100; return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? few : many; };
const fmtDate = (iso) => new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const initial = (name) => esc((name || "?")[0].toUpperCase());
const here = () => location.pathname + location.search;

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3500);
}

function modal(html) {
  const m = $("#modal");
  m.innerHTML = `<div class="box">${html}</div>`;
  m.hidden = false;
  const close = () => { m.hidden = true; m.innerHTML = ""; };
  m.onclick = (e) => { if (e.target === m || e.target.closest("[data-close]")) close(); };
  return { el: m, close };
}

class ApiError extends Error {
  constructor(status, data) { super(data.message || "Ошибка"); this.status = status; this.data = data; }
}

/** Вызов API. Сам обрабатывает: 401 → на вход, captcha_required → на капчу, banned → баннер. */
async function api(method, url, body, { quiet = false } = {}) {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* пусто */ }
  if (res.ok) return data;
  const err = new ApiError(res.status, data);
  if (quiet) throw err;
  if (res.status === 401) {
    location.href = `/login?next=${encodeURIComponent(here())}`;
  } else if (data.error === "captcha_required") {
    toast("Подозрительная активность — реши капчу и повтори действие");
    setTimeout(() => (location.href = `/captcha?next=${encodeURIComponent(here())}`), 900);
  } else if (data.error === "banned") {
    location.href = "/banned";
  } else {
    toast(data.message || `Ошибка ${res.status}`, true);
  }
  throw err;
}

// ---------------------------------------------------------------- header / session
let ME = null;
let HALLOWEEN_ACTIVE = false;
const isHalloweenAdmin = () => !!ME?.permissions?.includes("role.assign");
const REDUCED_MOTION = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false;

async function applyEventTheme() {
  let d;
  try { d = await api("GET", "/api/events/state", undefined, { quiet: true }); } catch (_) { d = { active: false }; }
  HALLOWEEN_ACTIVE = !!d.active;
  document.body.classList.toggle("halloween", HALLOWEEN_ACTIVE);
  document.body.dataset.halloween = HALLOWEEN_ACTIVE ? "1" : "0";
  startHauntedButtons();
  if (HALLOWEEN_ACTIVE) startSpookyMusic();
  else stopSpookyMusic();
  const mark = $(".logo-mark");
  if (mark) mark.textContent = HALLOWEEN_ACTIVE ? "🎃" : "🍄";
  const nav = $("#events-nav");
  if (nav) nav.hidden = false;
  const theme = $("meta[name=theme-color]");
  if (theme) theme.content = HALLOWEEN_ACTIVE ? "#100b12" : "#0e0e12";
  return d;
}

const HALLOWEEN_SCREAMER_CHANCE = 0.35;
const HALLOWEEN_SCREAMER_COOLDOWN_MS = 15000;
const HALLOWEEN_SCREAMERS = [
  { id: "ghost", face: "👻", caption: "Я УЖЕ ЗДЕСЬ", sound: { type: "sawtooth", from: 280, to: 72, duration: 0.28, gain: 0.07, filter: 900 } },
  { id: "demon", face: "👹", caption: "НЕ ОБОРАЧИВАЙСЯ", sound: { type: "square", from: 110, to: 42, duration: 0.44, gain: 0.055, filter: 380 } },
  { id: "skull", face: "💀", caption: "ТЫ СЛЕДУЮЩИЙ", sound: { type: "sawtooth", from: 690, to: 86, duration: 0.32, gain: 0.065, filter: 1500 } },
  { id: "eyes", face: "👁️　👁️", caption: "МЫ СМОТРИМ", sound: { type: "triangle", from: 145, to: 390, duration: 0.38, gain: 0.06, filter: 760 } },
  { id: "spider", face: "🕷️", caption: "ПАУТИНА УЖЕ РЯДОМ", sound: { type: "square", from: 980, to: 180, duration: 0.24, gain: 0.045, filter: 2200 } },
  { id: "mold", face: "🦠", caption: "ПЛЕСЕНЬ ПРОСНУЛАСЬ", sound: { type: "sawtooth", from: 210, to: 48, duration: 0.5, gain: 0.05, filter: 520 } },
];
let halloweenScreamerTimer = null, halloweenScreamerScene = null, lastScreamerVariant = "";

function halloweenScreamerOverlay() {
  let overlay = $("#halloween-screamer-overlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.id = "halloween-screamer-overlay";
  overlay.className = "halloween-screamer-overlay";
  overlay.setAttribute("aria-hidden", "true");
  const face = document.createElement("span");
  face.className = "screamer-face";
  const caption = document.createElement("strong");
  caption.className = "screamer-caption";
  overlay.append(face, caption);
  document.body.append(overlay);
  return overlay;
}

function playHalloweenScreamerSound(profile) {
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    const ctx = new Audio();
    const osc = ctx.createOscillator(), filter = ctx.createBiquadFilter(), gain = ctx.createGain();
    const duration = profile.duration;
    filter.type = profile.type === "triangle" ? "bandpass" : "lowpass";
    filter.frequency.value = profile.filter;
    osc.type = profile.type;
    osc.frequency.setValueAtTime(profile.from, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(profile.to, ctx.currentTime + duration * 0.72);
    gain.gain.setValueAtTime(profile.gain, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(filter).connect(gain).connect(ctx.destination);
    ctx.resume().catch(() => {});
    osc.start();
    osc.stop(ctx.currentTime + duration + 0.02);
    osc.onended = () => ctx.close().catch(() => {});
  } catch (_) {}
}

function maybeHalloweenScreamer(force = false, ignoreCooldown = false) {
  if ((!HALLOWEEN_ACTIVE && !force) || REDUCED_MOTION) return false;
  const now = Date.now(), last = Number(localStorage.getItem("halloween-scream-at") || 0);
  if (!ignoreCooldown && now - last < HALLOWEEN_SCREAMER_COOLDOWN_MS) {
    if (force) toast("Скример уже был. Дай нервам передышку ещё немного 👻");
    return false;
  }
  if (!force && Math.random() >= HALLOWEEN_SCREAMER_CHANCE) return false;
  localStorage.setItem("halloween-scream-at", String(now));
  const choices = HALLOWEEN_SCREAMERS.filter((variant) => variant.id !== lastScreamerVariant);
  const variant = choices[Math.floor(Math.random() * choices.length)] || HALLOWEEN_SCREAMERS[0];
  lastScreamerVariant = variant.id;
  const scene = $(".kb-scene .kb-svg") || $(".halloween-boss") || $(".profile-skin .kb-svg") || $(".kb-svg");
  const overlay = halloweenScreamerOverlay();
  clearTimeout(halloweenScreamerTimer);
  halloweenScreamerScene?.classList.remove("kb-screamer");
  document.body.classList.remove("halloween-scream-flash");
  overlay.classList.remove("active");
  void overlay.offsetWidth;
  overlay.dataset.variant = variant.id;
  $(".screamer-face", overlay).textContent = variant.face;
  $(".screamer-caption", overlay).textContent = variant.caption;
  scene?.classList.remove("kb-screamer");
  void document.body.offsetWidth;
  scene?.classList.add("kb-screamer");
  halloweenScreamerScene = scene;
  overlay.classList.add("active");
  document.body.classList.add("halloween-scream-flash");
  playHalloweenScreamerSound(variant.sound);
  halloweenScreamerTimer = setTimeout(() => {
    overlay.classList.remove("active");
    document.body.classList.remove("halloween-scream-flash");
    halloweenScreamerScene?.classList.remove("kb-screamer");
    halloweenScreamerScene = null;
  }, 1050);
  return true;
}

let spookyMusic = null;
let spookyMusicEnabled = localStorage.getItem("halloween-music-enabled") !== "0";
function refreshSpookyMusicButtons() {
  $$('[data-spooky-music]').forEach((button) => {
    button.textContent = spookyMusicEnabled ? "🔇 Выключить музыку" : "🕯️ Включить музыку";
    button.setAttribute("aria-pressed", spookyMusicEnabled ? "true" : "false");
  });
}
function stopSpookyMusic() {
  if (!spookyMusic) return;
  const sound = spookyMusic; spookyMusic = null;
  clearInterval(sound.bellTimer);
  if (sound.resumeHandler) {
    document.removeEventListener("pointerdown", sound.resumeHandler);
    document.removeEventListener("keydown", sound.resumeHandler);
  }
  try { sound.master.gain.setTargetAtTime(0.0001, sound.ctx.currentTime, 0.18); } catch (_) {}
  setTimeout(() => sound.ctx.close().catch(() => {}), 700);
  refreshSpookyMusicButtons();
}
function startSpookyMusic() {
  if (!HALLOWEEN_ACTIVE || !spookyMusicEnabled || spookyMusic) return;
  const Audio = window.AudioContext || window.webkitAudioContext;
  if (!Audio) return;
  let ctx = null;
  try {
    ctx = new Audio();
    const master = ctx.createGain(), filter = ctx.createBiquadFilter();
    filter.type = "lowpass"; filter.frequency.value = 380; filter.Q.value = 1.3;
    master.gain.value = 0.055; filter.connect(master).connect(ctx.destination);
    [[55, "sine", 0.38], [82.41, "triangle", 0.16], [110, "sine", 0.08], [41.2, "sine", 0.12]].forEach(([hz, type, vol]) => {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.type = type; osc.frequency.value = hz; gain.gain.value = vol;
      osc.connect(gain).connect(filter); osc.start();
    });
    const lfo = ctx.createOscillator(), lfoGain = ctx.createGain();
    lfo.frequency.value = 0.075; lfoGain.gain.value = 115; lfo.connect(lfoGain).connect(filter.frequency); lfo.start();
    const state = { ctx, master, filter, bellTimer: null, resumeHandler: null };
    const resume = () => {
      if (spookyMusic !== state || ctx.state === "closed") return;
      ctx.resume().then(() => {
        if (ctx.state === "running") {
          document.removeEventListener("pointerdown", resume);
          document.removeEventListener("keydown", resume);
          state.resumeHandler = null;
        }
      }).catch(() => {});
    };
    state.resumeHandler = resume;
    spookyMusic = state;
    const bell = () => {
      if (spookyMusic !== state || ctx.state !== "running") return;
      const osc = ctx.createOscillator(), gain = ctx.createGain(), t = ctx.currentTime;
      osc.type = "sine"; osc.frequency.value = [164.81, 196, 246.94, 293.66][Math.floor(Math.random() * 4)];
      gain.gain.setValueAtTime(0.0001, t); gain.gain.exponentialRampToValueAtTime(0.11, t + 0.06);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 2.6); osc.connect(gain).connect(filter);
      osc.start(t); osc.stop(t + 2.7);
    };
    state.bellTimer = setInterval(bell, 6500 + Math.random() * 5000);
    document.addEventListener("pointerdown", resume, { passive: true });
    document.addEventListener("keydown", resume);
    resume();
    refreshSpookyMusicButtons();
  } catch (_) {
    ctx?.close().catch(() => {});
    spookyMusic = null;
    refreshSpookyMusicButtons();
  }
}
function toggleSpookyMusic() {
  if (!HALLOWEEN_ACTIVE) return;
  spookyMusicEnabled = !spookyMusicEnabled;
  localStorage.setItem("halloween-music-enabled", spookyMusicEnabled ? "1" : "0");
  if (spookyMusicEnabled) startSpookyMusic();
  else stopSpookyMusic();
  refreshSpookyMusicButtons();
}

let hauntedButtonTimer = null, hauntedPointerBound = false;
function hauntButton(button) {
  if (!HALLOWEEN_ACTIVE || REDUCED_MOTION || !button?.isConnected) return;
  const effects = ["haunt-run", "haunt-hide", "haunt-blink", "haunt-color"];
  effects.forEach((name) => button.classList.remove(name));
  const effect = effects[Math.floor(Math.random() * effects.length)];
  button.style.setProperty("--haunt-x", `${Math.round(Math.random() * 76 - 38)}px`);
  button.style.setProperty("--haunt-y", `${Math.round(Math.random() * 42 - 21)}px`);
  button.style.setProperty("--haunt-r", `${Math.round(Math.random() * 18 - 9)}deg`);
  void button.offsetWidth;
  button.classList.add(effect);
  setTimeout(() => {
    button.classList.remove(effect);
    button.style.removeProperty("--haunt-x"); button.style.removeProperty("--haunt-y"); button.style.removeProperty("--haunt-r");
  }, 1100);
}
function startHauntedButtons() {
  clearInterval(hauntedButtonTimer); hauntedButtonTimer = null;
  if (!HALLOWEEN_ACTIVE || REDUCED_MOTION) return;
  if (!hauntedPointerBound) {
    document.addEventListener("pointerover", (event) => {
      const button = event.target.closest(".kb-actions button, .kb-talk, .kb-daily, .halloween-event-card button");
      if (button && Math.random() < 0.22) hauntButton(button);
    }, { passive: true });
    hauntedPointerBound = true;
  }
  hauntedButtonTimer = setInterval(() => {
    const buttons = $$(".kb-actions button:not(:disabled), .kb-talk:not(:disabled), .kb-daily:not(:disabled), .halloween-event-card button:not(:disabled)");
    if (buttons.length) hauntButton(buttons[Math.floor(Math.random() * buttons.length)]);
  }, 2800);
}

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-spooky-music]")) toggleSpookyMusic();
  if (event.target.closest("[data-screamer-test]") && isHalloweenAdmin()) {
    if (REDUCED_MOTION) toast("Скример отключён системной настройкой reduced motion");
    else maybeHalloweenScreamer(true, true);
  }
});
document.addEventListener("pointerdown", (e) => {
  if (e.target.closest("[data-screamer-test]")) return;
  if (e.target.closest("button, a, [role=button]")) maybeHalloweenScreamer();
}, { passive: true });

// «Деревянные» ($₽) в шапке
function setWood(n) {
  const chip = $("#wood-chip");
  if (!chip || n == null) return;
  chip.hidden = false;
  const el = $("#wood-balance");
  if (el.textContent !== String(n) && el.textContent !== "0") { chip.classList.remove("bump"); void chip.offsetWidth; chip.classList.add("bump"); }
  el.textContent = n;
}

async function loadMe() {
  if (document.body.dataset.loggedIn !== "1") return null;
  try {
    ME = await api("GET", "/api/auth/me", undefined, { quiet: true });
  } catch (e) {
    return null;
  }
  $("#me-name").textContent = ME.user.username;
  $("#me-avatar").textContent = ME.user.username[0].toUpperCase();
  $("#me-profile").href = `/u/${encodeURIComponent(ME.user.username)}`;
  $("#me-admin").hidden = !ME.permissions.includes("analytics.read");
  setBell(ME.unread_notifications || 0);
  setWood(ME.wood);
  if (ME.wood_daily > 0) setTimeout(() => toast(`+${ME.wood_daily} $₽ за заход сегодня 🪵`), 600);
  if (ME.ban && document.body.dataset.page !== "banned") {
    const b = $("#ban-banner");
    b.innerHTML = `Аккаунт заблокирован${ME.ban.ends_at ? " до " + esc(fmtDate(ME.ban.ends_at)) : " навсегда"}. <a href="/banned">Подробнее и апелляция →</a>`;
    b.hidden = false;
  }
  return ME;
}

function setBell(n) {
  const el = $("#bell-count");
  if (!el) return;
  el.textContent = n > 99 ? "99+" : String(n);
  el.hidden = !n;
}

function initHeader() {
  const btn = $("#user-menu-btn");
  if (btn) {
    const dd = $("#user-dropdown");
    btn.onclick = (e) => { e.stopPropagation(); dd.hidden = !dd.hidden; btn.setAttribute("aria-expanded", String(!dd.hidden)); };
    document.addEventListener("click", () => (dd.hidden = true));
    $("#logout-btn").onclick = async () => { await api("POST", "/api/auth/logout"); location.href = "/"; };
  }
}

const perm = (p) => !!ME && ME.permissions.includes(p);
const requireLogin = () => { if (!ME) { location.href = `/login?next=${encodeURIComponent(here())}`; return false; } return true; };

// ---------------------------------------------------------------- shared UI pieces
function userLink(u) {
  if (!u) return "";
  return `<a href="/u/${encodeURIComponent(u.username)}">${avatarHTML(u)}@${esc(u.username)}${u.status_emoji ? ` <span class="status-emoji sm">${esc(u.status_emoji)}</span>` : ""}</a>`;
}

// ---------------------------------------------------------------- картинки и markdown
async function uploadImage(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/uploads", { method: "POST", body: fd, credentials: "same-origin" });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { toast(data.message || "Не удалось загрузить картинку", true); throw new ApiError(res.status, data); }
  return data;
}

function insertAtCursor(ta, text) {
  const start = ta.selectionStart ?? ta.value.length, end = ta.selectionEnd ?? ta.value.length;
  ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
  ta.selectionStart = ta.selectionEnd = start + text.length;
  ta.dispatchEvent(new Event("input"));
  ta.focus();
}

function wrapSelection(ta, before, after = before) {
  const s0 = ta.selectionStart ?? 0, e0 = ta.selectionEnd ?? 0;
  const sel = ta.value.slice(s0, e0) || "текст";
  insertAtCursor(ta, before + sel + after);
}

function newBadgesToast(codes) {
  if (codes && codes.length) toast(`🏅 Новый бейдж! Загляни в профиль`);
}

// ---------------------------------------------------------------- profile
function avatarHTML(u, size = "") {
  const inner = u.avatar_url ? `<img src="${esc(u.avatar_url)}" alt="">` : initial(u.username);
  const frame = u.avatar_frame && u.avatar_frame !== "none" ? ` frame-${esc(u.avatar_frame)}` : "";
  return `<span class="avatar ${size}${frame}">${inner}</span>`;
}

// классы/переменные темы профиля — только из белых списков (сервер валидирует тоже)
// «с октября 2026» — родительный падеж (toLocaleDateString с month:"long" без дня даёт «октябрь 2026 г.»)
const MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
function sinceRu(iso) { const d = new Date(iso); return `${MONTHS_GEN[d.getMonth()]} ${d.getFullYear()}`; }

function profileSkin(c) {
  const cls = [`theme-${c.theme}`, `font-${c.font}`, `cards-${c.card_style}`, `layout-${c.layout}`].map((x) => x.replace(/[^\w-]/g, "")).join(" ");
  const style = c.accent && /^#[0-9a-f]{6}$/i.test(c.accent) ? `--accent:${c.accent};--accent2:${c.accent};` : "";
  return { cls, style };
}

function profileHTML(d, { preview = false } = {}) {
  const u = d.user, c = d.custom, st = d.stats || {};
  const hidden = new Set(d.is_owner || preview ? [] : c.hidden_sections);
  const ownHidden = new Set(c.hidden_sections || []);
  const tag = (sec) => (d.is_owner || preview) && ownHidden.has(sec) ? ` <span class="hidden-tag" title="Этот раздел видишь только ты">🙈 скрыто</span>` : "";
  const statsParts = [];
  if (u.streak_days != null && !hidden.has("streak")) statsParts.push(`<div class="stat"><b>🔥 ${u.streak_days}</b><span>дней ухода подряд</span></div>`);
  if (st.codex != null) {
    statsParts.push(`<div class="stat"><b>🧬 ${st.codex}/${st.codex_total}</b><span>мутаций в коллекции</span></div>`);
    statsParts.push(`<div class="stat"><b>🍄 ${st.alive}</b><span>живых · 🧊 ${st.frozen} на полке</span></div>`);
    statsParts.push(`<div class="stat" title="${esc(st.best_stage)}"><b>${st.best_xp}</b><span>рекорд XP</span></div>`);
    if (st.sprouts) statsParts.push(`<div class="stat"><b>🌱 ${st.sprouts}</b><span>отростков</span></div>`);
  }
  const lvl = u.role === "admin" ? `Уровень ∞ · Главный гриб` : `Уровень ${u.level} · ${esc(u.level_name)}`;
  const role = u.role === "admin" ? ` <span class="urating tier-admin">админ</span>` : "";
  const showcase = (d.badges || []).filter((b) => b.showcase);
  const meta = [c.pronouns && esc(c.pronouns), c.city && `📍 ${esc(c.city)}`, u.created_at && `грибовод с ${sinceRu(u.created_at)}`].filter(Boolean);
  const pk = d.pinned_kombucha;
  return `<div class="profile-skin ${profileSkin(c).cls}" style="${profileSkin(c).style}">
    <div class="panel profile-card">
      ${c.banner_url ? `<div class="profile-banner" style="background-image:url('${esc(c.banner_url)}')"></div>` : `<div class="profile-banner empty"></div>`}
      <div class="profile-head">${avatarHTML(u, "lg")}
        <div class="ph-main"><h1>${esc(u.display_name || u.username)} ${c.status_emoji ? `<span class="status-emoji">${esc(c.status_emoji)}</span>` : ""}${role}</h1>
          <div class="muted">@${esc(u.username)}${meta.length ? " · " + meta.join(" · ") : ""}</div>
          <div class="level">${lvl}</div>
          ${c.status_text ? `<div class="status-line">${esc(c.status_text)}</div>` : ""}
          ${showcase.length ? `<div class="showcase">${showcase.map((b) => `<span class="sc-badge" title="${esc(b.title)}: ${esc(b.description)}">${esc(b.emoji)} ${esc(b.title)}</span>`).join("")}</div>` : ""}
        </div></div>
      ${u.bio ? `<p class="bio">${esc(u.bio)}</p>` : ""}
      ${c.interests.length ? `<div class="interests">${c.interests.map((t) => `<span class="chip">#${esc(t)}</span>`).join("")}</div>` : ""}
      ${c.links.length ? `<div class="plinks">${c.links.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="nofollow noopener ugc">🔗 ${esc(l.title)}</a>`).join("")}</div>` : ""}
      <div class="stats">${statsParts.join("")}${tag("stats")}</div>
      ${u.streak_freeze_available && !hidden.has("streak") ? `<div class="freeze">❄️ Заморозка стрика доступна: пропустишь один день ухода на этой неделе — 🔥 не сгорит</div>` : ""}
      ${preview || !d.is_owner ? "" : `<a class="btn btn-sm btn-accent" href="/settings">🎨 Настроить профиль</a>`}
    </div>
    ${d.about_html ? `<div class="panel"><h2 style="margin-top:0">О себе</h2><div class="md">${d.about_html}</div></div>` : ""}
    ${pk ? `<div class="panel pinned-kb"><div class="kind">📌 Любимый гриб</div><div class="pinned-kb-row"><div class="pinned-kb-art">${kombuchaSVG({ ...pk, id: "pin" + pk.id }, { small: true })}</div>
      <div><b>«${esc(pk.name)}»</b><div class="muted">${esc(pk.stage.title)} · ${pk.xp} XP · поколение ${pk.generation}${pk.alive ? "" : " · 🪦 закис"}${pk.frozen ? " · 🧊" : ""}</div>
      ${pk.mutations.length ? `<div class="kb-card-muts">${pk.mutations.slice(0, 6).map(mutChip).join("")}</div>` : ""}
      ${preview ? "" : `<a class="btn btn-sm btn-ghost" href="/g/${pk.id}">📖 Дневник</a>`}</div></div></div>` : ""}
    ${hidden.has("garden") || !(d.garden || []).length ? "" : `<div class="panel"><h2 style="margin-top:0">🫙 Банки на подоконнике${tag("garden")}</h2>
      <div class="kb-shelf">${d.garden.map((k) => kombuchaCard(k, preview ? "" : `<div class="kb-card-foot"><a href="/g/${k.id}">📖 Дневник</a>${k.alive ? "" : "<small>🪦</small>"}</div>`)).join("")}</div></div>`}
    ${hidden.has("badges") ? "" : `<div class="panel"><h2 style="margin-top:0">Бейджи${tag("badges")}</h2>
      ${d.badges.length ? `<div class="badges">${d.badges.map((b) => `<div class="badge${b.showcase ? " on-show" : ""}"><div class="e">${esc(b.emoji)}</div><b>${esc(b.title)}</b><span>${esc(b.description)}</span></div>`).join("")}</div>` : `<p class="muted">Пока нет. Поухаживай за грибом 😉</p>`}</div>`}
  </div>`;
}

async function pageProfile() {
  const root = $("#profile");
  const username = root.dataset.username;
  let d;
  try { d = await api("GET", `/api/users/${encodeURIComponent(username)}`, undefined, { quiet: true }); }
  catch (_) { root.innerHTML = `<div class="panel"><h1>Грибовод не найден</h1></div>`; return; }
  const u = d.user;
  document.title = `${u.display_name || "@" + u.username} — schematoz-bulboz.org`;
  root.innerHTML = profileHTML(d) + `<div id="profile-extras"></div>`;
  profileExtras(d);
}

// ---------------------------------------------------------------- настройки профиля
async function pageSettings() {
  const form = $("#settings-form");
  let d;
  try { d = await api("GET", "/api/me/profile"); } catch (_) { return; }
  const O = d.options, L = O.limits;
  const s = { ...d.settings, display_name: d.user.display_name || d.user.username, bio: d.user.bio || "" };
  // для превью тянем свой публичный профиль (статы, бейджи), а оформление подставляем из формы
  let base;
  try { base = await api("GET", `/api/users/${encodeURIComponent(d.user.username)}`); } catch (_) { return; }
  const opts = (obj, cur) => Object.entries(obj).map(([k, v]) => `<option value="${esc(k)}"${k === cur ? " selected" : ""}>${esc(v)}</option>`).join("");
  const field = (label, control, hint = "") => `<div class="st-field"><span class="st-label">${label}</span>${control}${hint ? `<small class="st-hint">${hint}</small>` : ""}</div>`;
  const text = (name, val, max, ph = "") => `<input class="input" name="${name}" maxlength="${max}" placeholder="${esc(ph)}" value="${esc(val)}">`;
  const lvl = d.user.level, unlimited = d.user.role !== "user";
  const SECTIONS_UI = [["basic", "👤", "Основное"], ["media", "🖼", "Аватар"], ["look", "🎨", "Оформление"], ["links", "🏷", "Интересы"], ["show", "🏆", "Витрина"], ["privacy", "🙈", "Приватность"], ["push", "🔔", "Уведомления"], ["password", "🔐", "Пароль"]];
  $("#st-nav").innerHTML = SECTIONS_UI.map(([id, e, t]) => `<a href="#${id === "push" ? "push-settings" : "st-" + id}">${e} ${t}</a>`).join("");
  form.innerHTML = `
    <section class="st-card" id="st-basic"><h2>👤 Основное</h2>
      <div class="st-grid">
        ${field("Отображаемое имя", text("display_name", s.display_name, L.display_name))}
        ${field("Местоимения", text("pronouns", s.pronouns, L.pronouns, "он/его"))}
        ${field("Статус-эмодзи", text("status_emoji", s.status_emoji, 8, "😎"), "Только эмодзи")}
        ${field("Город", text("city", s.city, L.city, "Казань"))}
      </div>
      ${field("Статус", text("status_text", s.status_text, L.status_text, "ращу легенду банки 🍄"))}
      ${field("Короткое био", `<textarea class="input" name="bio" rows="2" maxlength="${L.bio}">${esc(s.bio)}</textarea>`, `До ${L.bio} символов, видно под именем`)}
      ${field("О себе", `<textarea class="input" name="about" rows="5" maxlength="${L.about}">${esc(s.about)}</textarea>`, `Markdown, до ${L.about} символов. Отдельный блок на профиле`)}
    </section>

    <section class="st-card" id="st-media"><h2>🖼 Аватар и обложка</h2>
      <div class="st-media">
        <div class="st-media-item">
          <div id="av-prev" class="st-av-prev"></div>
          <div class="st-btns"><label class="btn btn-sm btn-ghost st-file">Загрузить аватар<input type="file" accept="image/*" id="av-file"></label>
            <button type="button" class="btn btn-sm btn-ghost" id="av-clear">Убрать</button></div>
        </div>
        <div class="st-media-item st-media-wide">
          <div id="bn-prev" class="st-bn-prev"></div>
          <div class="st-btns"><label class="btn btn-sm btn-ghost st-file">Загрузить обложку<input type="file" accept="image/*" id="bn-file"></label>
            <button type="button" class="btn btn-sm btn-ghost" id="bn-clear">Убрать</button></div>
        </div>
      </div>
      <h3>Рамка аватара</h3>
      <div class="st-options">${Object.entries(O.frames).map(([k, f]) => { const locked = !unlimited && lvl < f.min_level;
        return `<label class="st-opt${locked ? " is-locked" : ""}" title="${locked ? `Откроется на ${f.min_level} уровне` : ""}"><input type="radio" name="avatar_frame" value="${esc(k)}"${k === s.avatar_frame ? " checked" : ""}${locked ? " disabled" : ""}>
          <span class="st-opt-body"><span class="avatar frame-${esc(k)}">${initial(d.user.username)}</span><span>${esc(f.title)}</span>${locked ? `<small>🔒 ур. ${f.min_level}</small>` : ""}</span></label>`; }).join("")}</div>
    </section>

    <section class="st-card" id="st-look"><h2>🎨 Оформление</h2>
      <h3>Тема</h3>
      <div class="st-options st-themes">${Object.entries(O.themes).map(([k, v]) => `<label class="st-opt"><input type="radio" name="theme" value="${esc(k)}"${k === s.theme ? " checked" : ""}>
        <span class="st-opt-body"><span class="st-swatch sw-${esc(k)}"></span><span>${esc(v)}</span></span></label>`).join("")}</div>
      <div class="st-grid">
        <div class="st-field"><span class="st-label">Акцентный цвет</span>
          <div class="st-accent"><input type="color" name="accent" value="${esc(s.accent || "#ff5a36")}">
            <label class="st-check"><input type="checkbox" name="accent_on"${s.accent ? " checked" : ""}> свой цвет вместо цвета темы</label></div></div>
        ${field("Шрифт", `<select class="input" name="font">${opts(O.fonts, s.font)}</select>`)}
        ${field("Карточки", `<select class="input" name="card_style">${opts(O.card_styles, s.card_style)}</select>`)}
        ${field("Шапка профиля", `<select class="input" name="layout">${opts(O.layouts, s.layout)}</select>`)}
      </div>
    </section>

    <section class="st-card" id="st-links"><h2>🏷 Интересы и ссылки</h2>
      ${field("Интересы", text("interests", s.interests.join(", "), 400, "аниме, физика, cs2"), `Через запятую, до ${L.interests}`)}
      <div class="st-field"><span class="st-label">Ссылки</span><div id="links" class="st-links"></div>
        <button type="button" class="btn btn-sm btn-ghost" id="add-link">+ Добавить ссылку</button>
        <small class="st-hint">До ${L.links} ссылок, только https://</small></div>
    </section>

    <section class="st-card" id="st-show"><h2>🏆 Витрина и закреп</h2>
      <div class="st-field"><span class="st-label">Бейджи в шапке профиля</span>
        <div class="st-options">${d.badges.length ? d.badges.map((b) => `<label class="st-opt"><input type="checkbox" name="showcase" value="${esc(b.code)}"${s.showcase_badges.includes(b.code) ? " checked" : ""}>
          <span class="st-opt-body"><span class="st-emoji">${esc(b.emoji)}</span><span>${esc(b.title)}</span></span></label>`).join("") : `<span class="muted">Бейджей пока нет: поухаживай за грибом</span>`}</div>
        <small class="st-hint">До ${L.showcase_badges} штук</small></div>
      ${field("Любимый гриб", `<select class="input" name="pinned_kombucha_id"><option value="">— не закреплять —</option>${d.kombuchas.map((k) => `<option value="${k.id}"${k.id === s.pinned_kombucha_id ? " selected" : ""}>«${esc(k.name)}» · ${esc(k.stage)}</option>`).join("")}</select>`, "Покажется большой карточкой в профиле")}
    </section>

    <section class="st-card" id="st-privacy"><h2>🙈 Приватность</h2>
      <p class="muted st-lead">Отмеченные разделы видишь только ты. Сервер не отдаёт их даже через API.</p>
      <div class="st-toggles">${Object.entries(O.sections).map(([k, v]) => `<label class="st-check st-toggle"><input type="checkbox" name="hidden" value="${esc(k)}"${s.hidden_sections.includes(k) ? " checked" : ""}> Скрыть: ${esc(v)}</label>`).join("")}</div>
    </section>

    <div class="st-save"><button class="btn btn-accent">💾 Сохранить</button><a class="btn btn-ghost" href="/u/${encodeURIComponent(d.user.username)}">Открыть профиль</a><span class="st-dirty muted" id="st-dirty" hidden>Есть несохранённые изменения</span></div>`;

  let links = [...s.links];
  let avatar = s.avatar_url, banner = s.banner_url;
  const renderLinks = () => {
    $("#links").innerHTML = links.map((l, i) => `<div class="st-link"><input class="input" data-i="${i}" data-k="title" placeholder="Название" maxlength="30" value="${esc(l.title)}"><input class="input" data-i="${i}" data-k="url" placeholder="https://…" value="${esc(l.url)}"><button type="button" class="btn btn-sm btn-ghost" data-del="${i}" aria-label="Удалить">✕</button></div>`).join("");
    $("#add-link").hidden = links.length >= L.links;
  };
  $("#links").addEventListener("input", (e) => { const t = e.target; if (t.dataset.i) { links[+t.dataset.i][t.dataset.k] = t.value; preview(); } });
  $("#links").addEventListener("click", (e) => { const b = e.target.closest("[data-del]"); if (b) { links.splice(+b.dataset.del, 1); renderLinks(); preview(); } });
  $("#add-link").onclick = () => { links.push({ title: "", url: "" }); renderLinks(); };
  renderLinks();

  const collect = () => {
    const f = form.elements, all = (n) => [...form.querySelectorAll(`[name=${n}]:checked`)].map((x) => x.value);
    return {
      display_name: f.display_name.value, bio: f.bio.value, status_emoji: f.status_emoji.value, status_text: f.status_text.value,
      city: f.city.value, pronouns: f.pronouns.value, about: f.about.value,
      theme: form.querySelector("[name=theme]:checked")?.value || "default",
      avatar_frame: form.querySelector("[name=avatar_frame]:checked")?.value || "none",
      accent: f.accent_on.checked ? f.accent.value : null, font: f.font.value, card_style: f.card_style.value, layout: f.layout.value,
      interests: f.interests.value.split(",").map((x) => x.trim()).filter(Boolean),
      links: links.filter((l) => l.url.trim()),
      showcase_badges: all("showcase"), hidden_sections: all("hidden"),
      pinned_kombucha_id: f.pinned_kombucha_id.value ? Number(f.pinned_kombucha_id.value) : null,
      avatar_url: avatar || null, banner_url: banner || null,
    };
  };
  const preview = () => {
    const v = collect();
    const user = { ...base.user, display_name: v.display_name, bio: v.bio, avatar_url: v.avatar_url, avatar_frame: v.avatar_frame };
    const custom = { ...base.custom, ...v, links: v.links.map((l) => ({ ...l, title: l.title || l.url })), interests: v.interests.slice(0, L.interests) };
    const badges = base.badges.map((b) => ({ ...b, showcase: v.showcase_badges.includes(b.code) }))
      .sort((a, b) => (v.showcase_badges.indexOf(a.code) + 1 || 99) - (v.showcase_badges.indexOf(b.code) + 1 || 99));
    const pin = v.pinned_kombucha_id ? (base.pinned_kombucha?.id === v.pinned_kombucha_id ? base.pinned_kombucha
      : (base.garden || []).find((k) => k.id === v.pinned_kombucha_id) || null) : null;
    $("#preview").innerHTML = profileHTML({ ...base, user, custom, badges, pinned_kombucha: pin,
      about_html: v.about ? `<p>${esc(v.about).replace(/\n/g, "<br>")}</p>` : "" }, { preview: true });
    $("#av-prev").innerHTML = avatarHTML(user, "lg");
    $("#bn-prev").style.backgroundImage = banner ? `url('${banner}')` : "";
  };
  const dirty = () => { $("#st-dirty").hidden = false; };
  form.addEventListener("input", () => { preview(); dirty(); });
  form.addEventListener("change", () => { preview(); dirty(); });
  const hook = (inputId, set) => {
    $(inputId).onchange = async (e) => {
      const file = e.target.files[0]; e.target.value = "";
      if (!file) return;
      try { const r = await uploadImage(file); set(r.url); preview(); dirty(); toast("Загружено, не забудь сохранить"); } catch (_) {}
    };
  };
  hook("#av-file", (u) => (avatar = u)); hook("#bn-file", (u) => (banner = u));
  $("#av-clear").onclick = () => { avatar = null; preview(); dirty(); };
  $("#bn-clear").onclick = () => { banner = null; preview(); dirty(); };
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("PATCH", "/api/me/profile", collect());
      base.user = { ...base.user, ...r.user }; base.custom = { ...base.custom, ...r.settings };
      toast("Профиль сохранён ✨"); preview(); $("#st-dirty").hidden = true;
    } catch (_) {}
  };
  preview();
  passwordForm($("#pwd-form"), d.user.username);
  loginKeysPanel($("#login-keys"));
  pushSettingsPanel($("#push-settings"));
}

function base64UrlBytes(value) {
  const pad = "=".repeat((4 - value.length % 4) % 4);
  const raw = atob((value + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function pushSettingsPanel(root) {
  if (!root) return;
  let d;
  try { d = await api("GET", "/api/push/settings"); }
  catch (_) { root.innerHTML = `<p class="muted">Не удалось загрузить настройки push.</p>`; return; }
  const status = () => {
    if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) return "Этот браузер не поддерживает PWA push. Уведомления на сайте останутся включены.";
    if (!d.configured) return "На сервере ещё не настроены VAPID-ключи. Администратору нужно добавить VAPID_PUBLIC_KEY и VAPID_PRIVATE_KEY.";
    if (Notification.permission === "denied") return "Разрешение запрещено в настройках браузера. Сначала разреши уведомления для сайта.";
    return d.subscribed ? "Устройство подключено к push." : "Устройство ещё не подключено.";
  };
  const render = () => {
    root.innerHTML = `<h2>🔔 Push-уведомления</h2>
      <p class="muted">${esc(status())} Сайт продолжит показывать уведомления без push. В тихие часы push откладываются, лимит — не больше ${d.daily_cap} в сутки.</p>
      <div class="row push-controls"><button class="btn ${d.enabled ? "btn-ghost" : "btn-accent"}" id="push-toggle" ${!d.configured ? "disabled" : ""}>${d.enabled ? "⏸ Выключить push" : d.subscribed ? "▶ Включить push" : "🔔 Подключить это устройство"}</button>
        ${d.subscribed ? `<button class="btn btn-ghost" id="push-unsubscribe">Удалить устройство</button>` : ""}</div>
      <form id="push-pref-form" class="push-pref-form">
        <h3>Что присылать</h3><div class="push-types">${Object.entries(d.types).map(([key, label]) => `<label class="push-type"><input type="checkbox" name="type" value="${esc(key)}" ${d.categories[key] ? "checked" : ""}> <span>${esc(label)}</span></label>`).join("")}</div>
        <h3>Тихие часы</h3><div class="push-hours"><label>С <input class="input" type="time" name="quiet_start" value="${esc(d.quiet_start)}"></label><label>До <input class="input" type="time" name="quiet_end" value="${esc(d.quiet_end)}"></label></div>
        <small class="muted">По умолчанию 23:00–09:00 по Москве; при сохранении используется часовой пояс браузера. Если одинаковые границы — тихие часы отключены.</small>
        <div><button class="btn btn-accent" type="submit">Сохранить настройки</button></div>
      </form>`;
    const f = $("#push-pref-form", root);
    f.onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(f), categories = {};
      Object.keys(d.types).forEach((key) => { categories[key] = fd.getAll("type").includes(key); });
      try {
        d = await api("PUT", "/api/push/settings", {
          categories, quiet_start: fd.get("quiet_start"), quiet_end: fd.get("quiet_end"),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || d.timezone,
        });
        render(); toast("Настройки push сохранены");
      } catch (_) {}
    };
    $("#push-toggle", root).onclick = async () => {
      if (d.enabled) {
        try { d = await api("PUT", "/api/push/settings", { enabled: false }); render(); toast("Push временно выключены"); } catch (_) {}
        return;
      }
      try {
        if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error("Браузер не поддерживает Web Push");
        const permission = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
        if (permission !== "granted") throw new Error("Разреши уведомления в браузере");
        if (!d.configured) throw new Error("Сервер не настроил Web Push (VAPID)");
        const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
        let subscription = await registration.pushManager.getSubscription();
        if (!subscription) subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlBytes(d.vapid_public_key) });
        await api("POST", "/api/push/subscriptions", subscription.toJSON());
        d = await api("GET", "/api/push/settings"); render(); toast("Устройство подключено 🔔");
      } catch (err) { toast(err.message || "Не удалось подключить push", true); }
    };
    $("#push-unsubscribe", root)?.addEventListener("click", async () => {
      try {
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        await api("DELETE", "/api/push/subscriptions", { endpoint: subscription?.endpoint });
        await subscription?.unsubscribe();
        d = await api("GET", "/api/push/settings"); render(); toast("Устройство отключено");
      } catch (_) {}
    });
  };
  render();
}

function passwordForm(f, username) {
  if (!f) return;
  f.elements.username.value = username;     // для менеджеров паролей
  f.onsubmit = async (e) => {
    e.preventDefault();
    const cur = f.elements.current_password.value, n1 = f.elements.new_password.value, n2 = f.elements.new_password2.value;
    if (n1 !== n2) return toast("Новые пароли не совпадают", true);
    if (n1.length < 8) return toast("Новый пароль — от 8 символов", true);
    const btn = f.querySelector("button"); btn.disabled = true;
    try {
      await api("POST", "/api/auth/password", { current_password: cur, new_password: n1 });
      f.reset(); f.elements.username.value = username;
      toast("Пароль изменён 🔐 Другие устройства вышли из аккаунта");
    } catch (_) {} finally { btn.disabled = false; }
  };
}

// ---------------------------------------------------------------- auth
async function pageAuth() {
  const root = $("#auth");
  const mode = root.dataset.mode, next = root.dataset.next || "/";
  const form = $("#auth-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const body = Object.fromEntries(f.entries());
    if (mode === "register") { body.birth_year = Number(body.birth_year); body.accept_terms = f.get("accept_terms") === "on"; }
    const btn = $("button", form); btn.disabled = true;
    try {
      const r = await api("POST", `/api/auth/${mode}`, body, { quiet: true });
      location.href = r.banned ? "/banned" : next;
    } catch (err) {
      btn.disabled = false;
      if (err.data?.error === "captcha_required") {
        // капча только при подозрительной активности (например, много неудачных входов)
        toast("Слишком много попыток — реши задачку из ЕГЭ и попробуй снова", true);
        setTimeout(() => (location.href = `/captcha?next=${encodeURIComponent(here())}`), 1200);
      } else {
        toast(err.data?.message || "Ошибка", true);
      }
    }
  };
  if (mode === "login") initFileLogin(next);
}

async function loginWithKeyFile(file, next) {
  let parsed;
  try {
    if (file.size > 4096) throw new Error("big");
    const text = (await file.text()).trim();
    parsed = text.startsWith("{") ? JSON.parse(text) : { key: text };
  } catch (_) { toast("Это не файл входа schematoz-bulboz", true); return; }
  try {
    const r = await api("POST", "/api/auth/login-file", { key: parsed.key }, { quiet: true });
    toast(`Привет, @${r.user.username}!`);
    location.href = r.banned ? "/banned" : next;
  } catch (err) {
    if (err.data?.error === "captcha_required") {
      toast("Слишком много попыток — реши задачку из ЕГЭ и попробуй снова", true);
      setTimeout(() => (location.href = `/captcha?next=${encodeURIComponent(here())}`), 1200);
    } else toast(err.data?.message || "Не получилось войти", true);
  }
}

function initFileLogin(next) {
  const input = $("#keyfile"), drop = $("#file-drop");
  if (!input) return;
  input.onchange = () => { if (input.files[0]) loginWithKeyFile(input.files[0], next); input.value = ""; };
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files[0]) loginWithKeyFile(e.dataTransfer.files[0], next);
  });
}

async function loginKeysPanel(root) {
  async function render() {
    const d = await api("GET", "/api/auth/login-keys");
    root.innerHTML = `<h2 style="margin-top:0">🔑 Файлы входа</h2>
      <p class="muted" style="font-size:13px">Скачай файл — и входи им на странице входа без логина и пароля. Храни его как пароль: кто получил файл, тот вошёл. Потерял — отзови.</p>
      ${d.items.length ? `<table class="list">${d.items.map((k) => `<tr><td>${esc(k.label)}</td><td class="muted">создан ${esc(fmtDate(k.created_at))}<br>${k.last_used_at ? "вход " + esc(fmtDate(k.last_used_at)) : "ещё не использовался"}</td><td><button class="btn btn-sm btn-ghost" data-revoke="${k.id}">Отозвать</button></td></tr>`).join("")}</table>` : ""}
      <button class="btn btn-accent btn-sm" id="new-key" ${d.items.length >= d.max ? "disabled" : ""}>Скачать новый файл входа</button>`;
    $("#new-key", root).onclick = async () => {
      const label = prompt("Название (например, «Ноутбук» или «Телефон»)", "Файл входа");
      if (label === null) return;
      try {
        const r = await api("POST", "/api/auth/login-keys", { label });
        const blob = new Blob([JSON.stringify(r.file, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = r.filename;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        toast("Файл скачан. Второй раз его не скачать — храни надёжно");
        render();
      } catch (_) {}
    };
    $$("[data-revoke]", root).forEach((b) => (b.onclick = async () => {
      if (!confirm("Отозвать ключ? Войти этим файлом больше не получится.")) return;
      try { await api("DELETE", `/api/auth/login-keys/${b.dataset.revoke}`); toast("Ключ отозван"); render(); } catch (_) {}
    }));
  }
  await render();
}

// ---------------------------------------------------------------- banned / appeal
async function pageBanned() {
  const root = $("#banned");
  if (!ME) { root.innerHTML = `<p>Войди в аккаунт, чтобы посмотреть статус.</p><a class="btn btn-accent" href="/login">Войти</a>`; return; }
  const { ban } = await api("GET", "/api/me/ban");
  if (!ban) { root.innerHTML = `<h1>Всё чисто ✅</h1><p>Активных блокировок нет.</p><a class="btn" href="/">В ленту</a>`; return; }
  const STATUS = { none: "", pending: "⏳ Апелляция на рассмотрении — её разбирает администратор.", accepted: "✅ Апелляция принята.", rejected: "❌ Апелляция отклонена." };
  root.innerHTML = `<h1>Аккаунт заблокирован</h1>
    <p><b>Причина:</b> ${esc(ban.reason)}</p>
    <p><b>Срок:</b> ${ban.ends_at ? "до " + esc(fmtDate(ban.ends_at)) : "навсегда"}</p>
    <p class="muted">Подробнее — в <a href="/rules">правилах сообщества</a>.</p>
    ${ban.appeal_status !== "none" ? `<p>${STATUS[ban.appeal_status]}</p>${ban.appeal_comment ? `<p class="muted">Комментарий администратора: ${esc(ban.appeal_comment)}</p>` : ""}` : `
    <form class="form" id="appeal-form"><label>Не согласен? Напиши апелляцию (от 10 символов)
      <textarea name="text" rows="5" minlength="10" maxlength="2000" required></textarea></label>
      <button class="btn btn-accent">Отправить апелляцию</button></form>`}`;
  const form = $("#appeal-form");
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    try { await api("POST", `/api/bans/${ban.id}/appeal`, { text: form.elements.text.value }); toast("Апелляция отправлена"); pageBanned(); } catch (_) {}
  };
}

// ---------------------------------------------------------------- panels (mod / admin)
function initPanel(tabs) {
  const panel = $("#panel");
  const show = async (name) => {
    $$("#panel-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    panel.innerHTML = `<p class="muted">Загружаем…</p>`;
    try { await tabs[name](panel); } catch (e) { panel.innerHTML = `<p class="muted">Не удалось загрузить: ${esc(e.message)}</p>`; }
  };
  $$("#panel-tabs button").forEach((b) => (b.onclick = () => show(b.dataset.tab)));
  const requested = new URLSearchParams(location.search).get("tab") || location.hash.slice(1);
  const initial = tabs[requested] ? requested : $("#panel-tabs button.active")?.dataset.tab;
  if (initial) show(initial);
  return show;
}

function denied(perm_) {
  if (!ME) { location.href = `/login?next=${encodeURIComponent(here())}`; return true; }
  if (!perm(perm_)) { $("main").innerHTML = `<div class="panel"><h1>Нет доступа</h1><p class="muted">Этот раздел только для админов.</p></div>`; return true; }
  return false;
}

function modlogTable(items) {
  if (!items.length) return `<p class="muted">Записей нет.</p>`;
  return `<table class="list"><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Цель</th><th>Детали</th></tr>
    ${items.map((a) => `<tr><td>${esc(fmtDate(a.created_at))}</td><td>#${a.actor_id}</td><td><code>${esc(a.action)}</code></td><td>${esc(a.target_type)} ${a.target_id ?? ""}</td><td><small class="muted">${esc(JSON.stringify(a.payload || {}))}</small></td></tr>`).join("")}</table>`;
}

async function banDialog(userId, username) {
  const canPerm = perm("ban.permanent");
  const m = modal(`<h2>Бан @${esc(username)}</h2><form class="form" id="ban-form">
    <label>Срок<select name="days"><option value="1">1 день</option><option value="7" selected>7 дней</option><option value="30">30 дней</option>${canPerm ? `<option value="perm">Навсегда</option>` : ""}</select></label>
    <label>Причина (увидит пользователь)<input name="reason" required placeholder="Автокликер в мини-играх (п. 2 Правил)"></label>
    <div class="row"><button type="button" class="btn btn-ghost" data-close>Отмена</button><button class="btn btn-danger">Забанить</button></div></form>`);
  return new Promise((resolve) => {
    $("#ban-form", m.el).onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const days = f.get("days") === "perm" ? null : Number(f.get("days"));
      try {
        await api("POST", "/mod/bans", { user_id: userId, reason: f.get("reason"), days });
        m.close(); toast("Бан выдан"); resolve(true);
      } catch (_) {}
    };
  });
}

// вкладки «Игроки и баны» и «Апелляции» админки (модераторов больше нет)
function adminBanTabs(show) {
  return {
    async bans(panel) {
      panel.innerHTML = `<input class="input" id="mod-q" placeholder="Ник игрока (от 2 букв)"><div id="mod-users" style="margin-top:10px"></div>`;
      const q = $("#mod-q", panel), box = $("#mod-users", panel);
      let tm;
      const run = async () => {
        const { items } = await api("GET", `/mod/users?q=${encodeURIComponent(q.value.trim())}`);
        box.innerHTML = items.length ? items.map((u) => `<div class="item"><div class="head"><a href="/u/${encodeURIComponent(u.username)}" target="_blank"><b>@${esc(u.username)}</b></a>${u.bot_flags ? `<span class="pill p0" title="Подозрительных партий в мини-играх за сутки">🤖 ${u.bot_flags}</span>` : ""}
          ${u.ban ? `<span class="pill p0">бан ${u.ban.ends_at ? "до " + esc(fmtDate(u.ban.ends_at)) : "навсегда"}</span><span class="muted">${esc(u.ban.reason)}</span>` : ""}</div>
          <div class="btns" style="margin-top:8px">${u.ban ? `<button class="btn btn-sm btn-ghost" data-lift="${u.ban.id}">Снять бан</button>`
            : `<button class="btn btn-sm btn-danger" data-ban="${u.id}" data-uname="${esc(u.username)}">Бан…</button>`}</div></div>`).join("")
          : `<p class="muted">${q.value.trim().length < 2 ? "Введи хотя бы 2 буквы" : "Никого не нашли"}</p>`;
        $$("[data-ban]", box).forEach((b) => (b.onclick = async () => { if (await banDialog(Number(b.dataset.ban), b.dataset.uname)) run(); }));
        $$("[data-lift]", box).forEach((b) => (b.onclick = async () => { try { await api("POST", `/mod/bans/${b.dataset.lift}/lift`, {}); toast("Бан снят"); run(); } catch (_) {} }));
      };
      q.oninput = () => { clearTimeout(tm); tm = setTimeout(run, 300); };
      run();
    },
    async appeals(panel) {
      const { items } = await api("GET", "/mod/appeals");
      if (!items.length) { panel.innerHTML = `<p class="muted">Апелляций нет 🕊</p>`; return; }
      panel.innerHTML = items.map((a) => `<div class="item" data-bid="${a.ban_id}">
        <div class="head"><b>@${esc(a.username)}</b>${a.own ? `<span class="pill">твой бан</span>` : ""}<span class="muted">бан ${a.ends_at ? "до " + esc(fmtDate(a.ends_at)) : "навсегда"} · выдал #${a.issued_by}</span></div>
        <p style="font-size:14px"><b>Причина бана:</b> ${esc(a.reason)}</p>
        <div class="quote">${esc(a.text)}</div>
        <input class="input" placeholder="Комментарий для пользователя" data-comment>
        <div class="btns" style="margin-top:10px"><button class="btn btn-sm btn-good" data-dec="accept">Принять (снять бан)</button><button class="btn btn-sm btn-danger" data-dec="reject">Отклонить</button></div>
      </div>`).join("");
      $$("[data-dec]", panel).forEach((b) => (b.onclick = async () => {
        const item = b.closest(".item");
        try {
          await api("POST", `/mod/appeals/${item.dataset.bid}/decide`, { decision: b.dataset.dec, comment: $("[data-comment]", item).value });
          toast("Решение сохранено"); show()("appeals");
        } catch (_) {}
      }));
    },
  };
}

// ---------------------------------------------------------------- админ: цитаты гриба
async function adminQuotes(panel, kind = "") {
  const d = await api("GET", `/admin/quotes${kind ? `?kind=${kind}` : ""}`);
  const K = d.kinds;
  panel.innerHTML = `<form class="panel form" id="q-form"><h3 style="margin-top:0">Новая цитата</h3>
      <p class="muted" style="font-size:13px">Гриб говорит её сам, от первого лица — без «как говорил…». Только на русском. Автор и источник видны при наведении на облачко.
        Встроенных цитат: спорных ${d.builtin.dubious}, философских ${d.builtin.philo}; свои добавляются в общий пул.</p>
      <label>Куда<select name="kind">${Object.entries(K).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
      <label>Цитата<textarea name="text" rows="3" maxlength="400" required placeholder="Я — гриб. Этим и интересен."></textarea></label>
      <div class="row"><label style="flex:1">Автор<input name="author" maxlength="80" placeholder="Владимир Маяковский"></label>
        <label style="flex:1">Источник<input name="source" maxlength="120" placeholder="«Я сам», 1922"></label></div>
      <button class="btn btn-accent">Добавить</button></form>
    <div class="tabs" id="q-kinds"><button data-k="" class="${kind ? "" : "active"}">Все (${kind ? "…" : d.items.length})</button>${Object.entries(K).map(([k, v]) => `<button data-k="${k}" class="${kind === k ? "active" : ""}">${esc(v.split(" (")[0])}</button>`).join("")}</div>
    <div id="q-list">${d.items.length ? d.items.map((q) => `<div class="item q-item${q.enabled ? "" : " q-off"}" data-qid="${q.id}">
        <div class="head"><span class="pill">${esc(K[q.kind].split(" (")[0])}</span><span class="muted">${esc(q.author || "без автора")}${q.source ? ` · ${esc(q.source)}` : ""}</span></div>
        <div class="quote">${esc(q.text)}</div>
        <div class="btns" style="margin-top:8px"><button class="btn btn-sm btn-ghost" data-toggle>${q.enabled ? "🙈 Выключить" : "👁 Включить"}</button>
          <button class="btn btn-sm btn-ghost" data-edit>✏️ Изменить</button><button class="btn btn-sm btn-danger" data-del>Удалить</button></div></div>`).join("")
      : `<p class="muted">Своих цитат пока нет — гриб говорит встроенными.</p>`}</div>`;
  const reload = () => adminQuotes(panel, kind);
  $("#q-form", panel).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try { await api("POST", "/admin/quotes", { kind: f.get("kind"), text: f.get("text"), author: f.get("author"), source: f.get("source") }); toast("Цитата добавлена 🍄"); reload(); } catch (_) {}
  };
  $$("#q-kinds [data-k]", panel).forEach((b) => (b.onclick = () => adminQuotes(panel, b.dataset.k)));
  const byId = new Map(d.items.map((q) => [q.id, q]));
  $$(".q-item", panel).forEach((el) => {
    const q = byId.get(Number(el.dataset.qid));
    $("[data-toggle]", el).onclick = async () => { try { await api("PATCH", `/admin/quotes/${q.id}`, { enabled: !q.enabled }); reload(); } catch (_) {} };
    $("[data-del]", el).onclick = async () => { if (!confirm("Удалить цитату?")) return; try { await api("DELETE", `/admin/quotes/${q.id}`); reload(); } catch (_) {} };
    $("[data-edit]", el).onclick = async () => {
      const text = prompt("Текст цитаты:", q.text);
      if (text == null || text.trim() === q.text) return;
      try { await api("PATCH", `/admin/quotes/${q.id}`, { text }); toast("Сохранено"); reload(); } catch (_) {}
    };
  });
}

// ---------------------------------------------------------------- админ: дебаг грибов
async function kbDebugPanel(panel, login = "", selId = null) {
  const D = await api("GET", `/admin/kombucha${login ? `?user=${encodeURIComponent(login)}` : ""}`);
  const RAR = { common: "обычная", rare: "редкая", epic: "эпическая", legendary: "легендарная" };
  let k = D.items.find((x) => x.id === selId) || D.items[0];
  const save = async (patch) => {
    try { const r = await api("PATCH", `/admin/kombucha/${k.id}`, patch); k = r.kombucha; D.items = D.items.map((x) => (x.id === k.id ? k : x)); draw(); }
    catch (_) {}
  };
  const draw = () => {
    if (!k) { panel.innerHTML = `${head()}<p class="muted">У @${esc(D.user)} нет грибов.</p>`; bindHead(); return; }
    const on = new Set(k.mutations.map((m) => m.code));
    const q = ($("#kbd-q")?.value || "").toLowerCase();
    const onlyOn = $("#kbd-on")?.checked;
    const byStage = {};
    D.catalog.forEach((m) => (byStage[m.stage] ||= []).push(m));
    panel.innerHTML = `${head()}
      <div class="kbd">
        <div class="kbd-left">
          <div class="kbd-prev">${kombuchaSVG(k)}</div>
          <p class="muted" style="text-align:center">«${esc(k.name)}» · ${esc(k.stage.title)} · xp ${k.xp} · настроение: ${esc(KB_MOOD[k.mood]?.[1] || k.mood)} · мутаций: ${on.size}</p>
          <div class="kbd-row"><b>Стадия:</b> ${D.stages.map((st) => `<button class="btn btn-sm ${st.size === k.stage.size ? "btn-accent" : ""}" data-stage="${st.size}" title="${esc(st.title)} (от ${st.xp} xp)">${st.size}</button>`).join("")}</div>
          ${["sweet", "tea", "clean", "happy"].map((st) => `<label class="kbd-row"><span>${{ sweet: "🍬 сахар", tea: "🫖 заварка", clean: "🧽 чистота", happy: "💛 счастье" }[st]}</span>
            <input type="range" min="0" max="100" value="${k.stats[st]}" data-stat="${st}"><b>${k.stats[st]}</b></label>`).join("")}
          <div class="kbd-row">
            <label><input type="checkbox" data-flag="alive" ${k.alive ? "checked" : ""}> живой</label>
            <label><input type="checkbox" data-flag="mold" ${k.mold ? "checked" : ""}> плесень</label>
            <label><input type="checkbox" data-flag="frozen" ${k.frozen ? "checked" : ""}> заморожен</label>
          </div>
          <div class="kbd-row">
            <button class="btn btn-sm" data-bulk="clear">Снять все мутации</button>
            <button class="btn btn-sm" data-bulk="stage3">По 3 на каждую стадию (случайно)</button>
            <button class="btn btn-sm" data-bulk="all-stage">Все мутации текущей стадии</button>
          </div>
          <p class="muted small">Изменения сразу сохраняются на гриб. Мутации из панели ставятся без лимитов, с номером #0 и не попадают в тиражи и коллекции.</p>
        </div>
        <div class="kbd-right">
          <div class="kbd-row"><input class="input" id="kbd-q" placeholder="Поиск мутации: название, код, эмодзи" value="${esc(q)}">
            <label><input type="checkbox" id="kbd-on" ${onlyOn ? "checked" : ""}> только включённые</label></div>
          ${Object.entries(byStage).map(([st, list]) => {
            const vis = list.filter((m) => (!q || (m.title + m.code + m.emoji).toLowerCase().includes(q)) && (!onlyOn || on.has(m.code)));
            if (!vis.length) return "";
            return `<details class="kbd-stage" ${localStorage.getItem("fold:kbd-" + st) === "0" ? "" : "open"} data-fold="kbd-${st}">
              <summary>Стадия ${st}: ${esc(list[0].stage_title)} <span class="muted">${list.filter((m) => on.has(m.code)).length}/${list.length} вкл.</span></summary>
              <div class="kbd-muts">${vis.map((m) => `<label class="kbd-mut r-${m.rarity} ${on.has(m.code) ? "on" : ""}" title="${esc(m.code)} · ${RAR[m.rarity]} · ${esc(m.hint)}">
                <input type="checkbox" data-mut="${esc(m.code)}" ${on.has(m.code) ? "checked" : ""}>
                <span class="kbd-dot" style="background:${m.color}"></span>${esc(m.emoji)} ${esc(m.title)}</label>`).join("")}</div></details>`;
          }).join("")}
        </div>
      </div>`;
    bindHead();
    const codes = () => k.mutations.map((m) => m.code);
    $$("[data-stage]", panel).forEach((b) => (b.onclick = () => save({ stage: +b.dataset.stage })));
    $$("[data-stat]", panel).forEach((r) => {
      r.oninput = () => (r.nextElementSibling.textContent = r.value);
      r.onchange = () => save({ stats: { [r.dataset.stat]: +r.value } });
    });
    $$("[data-flag]", panel).forEach((c) => (c.onchange = () => save({ [c.dataset.flag]: c.checked })));
    $$("[data-mut]", panel).forEach((c) => (c.onchange = () => {
      const cur = codes().filter((x) => x !== c.dataset.mut);
      save({ mutations: c.checked ? [...cur, c.dataset.mut] : cur });
    }));
    $$("[data-bulk]", panel).forEach((b) => (b.onclick = () => {
      const mode = b.dataset.bulk;
      if (mode === "clear") return save({ mutations: [] });
      if (mode === "all-stage") return save({ mutations: [...new Set([...codes(), ...D.catalog.filter((m) => m.stage === k.stage.size).map((m) => m.code)])] });
      const pick = [];
      for (let st = 1; st <= 6; st++) {
        const pool = D.catalog.filter((m) => m.stage === st).sort(() => Math.random() - 0.5);
        pick.push(...pool.slice(0, 3).map((m) => m.code));
      }
      save({ mutations: pick });
    }));
    const qi = $("#kbd-q"), oi = $("#kbd-on");
    qi.oninput = () => { const pos = qi.selectionStart; draw(); const n = $("#kbd-q"); n.focus(); n.setSelectionRange(pos, pos); };
    oi.onchange = draw;
  };
  const head = () => `<div class="kbd-row kbd-head">
      <form id="kbd-user" class="kbd-row"><input class="input" name="u" placeholder="ник владельца (пусто — мои)" value="${esc(login)}"><button class="btn btn-sm">Открыть</button></form>
      ${D.items.length ? `<select class="input" id="kbd-sel">${D.items.map((x) => `<option value="${x.id}" ${k && x.id === k.id ? "selected" : ""}>#${x.id} ${esc(x.name)} — ${esc(x.stage.title)}${x.alive ? "" : " 💀"}${x.frozen ? " ❄️" : ""}</option>`).join("")}</select>` : ""}
      <span class="muted">@${esc(D.user)}</span></div>`;
  const bindHead = () => {
    $("#kbd-user").onsubmit = (e) => { e.preventDefault(); kbDebugPanel(panel, e.target.elements.u.value.trim()); };
    const sel = $("#kbd-sel");
    if (sel) sel.onchange = () => { k = D.items.find((x) => x.id === +sel.value); draw(); };
  };
  draw();
}

async function adminHalloween(panel) {
  const data = await api("GET", "/admin/events/halloween");
  const localInput = (value) => {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? "" : new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  };
  const raid = data.raid || { boss_name: "Тыквенная плесень", regen_per_minute: 6,
    stages: [{ title: "Первая волна", max_hp: 10000, description: "" }], gifts: [] };
  const makeGiftId = () => `gift-${Math.random().toString(36).slice(2, 10)}`;
  const stageRow = (stage = {}) => `<div class="raid-admin-row" data-stage-row>
    <div class="raid-admin-row-head"><b>Стадия</b><button type="button" class="btn btn-ghost btn-sm" data-remove-stage>Удалить</button></div>
    <label>Название<input class="input" data-stage-title maxlength="80" required value="${esc(stage.title || "")}"></label>
    <label>Здоровье босса (HP)<input class="input" data-stage-hp type="number" min="1" max="1000000" required value="${Number(stage.max_hp) || 10000}"></label>
    <label>Описание<input class="input" data-stage-description maxlength="280" value="${esc(stage.description || "")}"></label>
  </div>`;
  const giftRow = (gift = {}) => `<div class="raid-admin-row" data-gift-row>
    <div class="raid-admin-row-head"><b>Подарок</b><button type="button" class="btn btn-ghost btn-sm" data-remove-gift>Удалить</button></div>
    <input type="hidden" data-gift-id value="${esc(gift.id || makeGiftId())}">
    <label>Стадия №<input class="input" data-gift-stage type="number" min="1" max="20" required value="${Number(gift.stage) || 1}"></label>
    <label>Нанести урона на этой стадии<input class="input" data-gift-damage type="number" min="1" max="1000000" required value="${Number(gift.required_damage) || 1}"></label>
    <label>Эмодзи<input class="input" data-gift-emoji maxlength="12" required value="${esc(gift.emoji || "🎁")}"></label>
    <label>Название<input class="input" data-gift-title maxlength="80" required value="${esc(gift.title || "")}" placeholder="Например, тыквенный значок"></label>
    <label>Описание<input class="input" data-gift-description maxlength="240" value="${esc(gift.description || "")}" placeholder="Что получит игрок"></label>
  </div>`;
  panel.innerHTML = `<form class="panel form" id="halloween-admin-form">
    <h2 style="margin-top:0">🎃 Хэллоуинский ивент</h2>
    <p class="muted">Ивент активен только между датами. Даты вводятся в часовом поясе браузера. Рейд общий для всех игроков сайта.</p>
    <label class="check"><input type="checkbox" name="enabled" ${data.enabled ? "checked" : ""}> Разрешить событие</label>
    <label>Начало<input class="input" type="datetime-local" name="start_at" required value="${esc(localInput(data.start_at))}"></label>
    <label>Конец<input class="input" type="datetime-local" name="end_at" required value="${esc(localInput(data.end_at))}"></label>
    <p class="event-admin-status">Сейчас: <b>${data.active ? "🟢 активно" : data.enabled ? "🕒 включено, но вне дат" : "⚫ выключено"}</b></p>
    <hr>
    <h3>Общий босс</h3>
    <label>Имя босса<input class="input" name="boss_name" maxlength="80" required value="${esc(raid.boss_name)}"></label>
    <label>Регенерация HP в минуту<input class="input" name="regen_per_minute" type="number" min="0" max="60" required value="${Number(raid.regen_per_minute) || 0}"></label>
    <h3>Стадии</h3><p class="muted">Здоровье задаётся отдельно для каждой стадии. Когда текущая стадия побеждена, рейд переходит к следующей; после последней босс продолжает появляться с её параметрами.</p>
    <div class="raid-admin-rows" id="raid-admin-stages">${(raid.stages || []).map(stageRow).join("")}</div>
    <button class="btn btn-ghost btn-sm" id="raid-add-stage" type="button">＋ Добавить стадию</button>
    <h3>Подарки за участие</h3><p class="muted">Подарок приходит игрокам после победы над указанной стадией, если каждый игрок лично нанёс на ней не меньше заданного урона. Один подарок выдаётся каждому игроку один раз.</p>
    <div class="raid-admin-rows" id="raid-admin-gifts">${(raid.gifts || []).map(giftRow).join("")}</div>
    <button class="btn btn-ghost btn-sm" id="raid-add-gift" type="button">＋ Создать подарок</button>
    <hr><button class="btn btn-accent">Сохранить настройки</button>
  </form>
  <div class="panel"><h3>Эффекты события</h3><p class="muted">Скример срабатывает примерно на каждом третьем действии, не чаще одного раза за 15 секунд. Музыка включена по умолчанию. Чистота и счастье грибов во время ивента убывают вдвое быстрее; в рейде каждый выставленный гриб наносит 1 урон, получает +1 чистоты и счастья, но теряет по 1 сахару и заварки.</p>
  <p class="muted">Также доступны хэллоуинские цитаты, временные мутации, «Сладость или гадость» и исчезновения грибов.</p></div>`;
  const stagesBox = $("#raid-admin-stages", panel), giftsBox = $("#raid-admin-gifts", panel);
  $("#raid-add-stage", panel).onclick = () => {
    if (stagesBox.querySelectorAll("[data-stage-row]").length >= 20) return toast("Максимум 20 стадий", true);
    stagesBox.insertAdjacentHTML("beforeend", stageRow({ title: `Стадия ${stagesBox.querySelectorAll("[data-stage-row]").length + 1}`, max_hp: 10000 }));
  };
  $("#raid-add-gift", panel).onclick = () => {
    if (giftsBox.querySelectorAll("[data-gift-row]").length >= 100) return toast("Максимум 100 подарков", true);
    giftsBox.insertAdjacentHTML("beforeend", giftRow());
  };
  stagesBox.addEventListener("click", (event) => {
    if (!event.target.closest("[data-remove-stage]")) return;
    if (stagesBox.querySelectorAll("[data-stage-row]").length <= 1) return toast("У рейда должна остаться хотя бы одна стадия", true);
    event.target.closest("[data-stage-row]").remove();
  });
  giftsBox.addEventListener("click", (event) => {
    if (event.target.closest("[data-remove-gift]")) event.target.closest("[data-gift-row]").remove();
  });
  $("#halloween-admin-form", panel).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const start = new Date(f.get("start_at")), end = new Date(f.get("end_at"));
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return toast("Укажи начало и конец события", true);
    const stages = [...stagesBox.querySelectorAll("[data-stage-row]")].map((row) => ({
      title: $("[data-stage-title]", row).value.trim(),
      max_hp: Number($("[data-stage-hp]", row).value),
      description: $("[data-stage-description]", row).value.trim(),
    }));
    const gifts = [...giftsBox.querySelectorAll("[data-gift-row]")].map((row) => ({
      id: $("[data-gift-id]", row).value,
      stage: Number($("[data-gift-stage]", row).value),
      required_damage: Number($("[data-gift-damage]", row).value),
      emoji: $("[data-gift-emoji]", row).value.trim(),
      title: $("[data-gift-title]", row).value.trim(),
      description: $("[data-gift-description]", row).value.trim(),
    }));
    try {
      const r = await api("PUT", "/admin/events/halloween", {
        enabled: f.has("enabled"), start_at: start.toISOString(), end_at: end.toISOString(),
        raid: { boss_name: f.get("boss_name").trim(), regen_per_minute: Number(f.get("regen_per_minute")), stages, gifts },
      });
      toast(r.active ? "🎃 Хэллоуин включён" : "Настройки ивента сохранены");
      await adminHalloween(panel);
    } catch (_) {}
  };
}

async function pageAdmin() {
  if (denied("analytics.read")) return;
  let show;
  show = initPanel({
    ...adminBanTabs(() => show),
    async quotes(panel) { await adminQuotes(panel); },
    async events(panel) { await adminHalloween(panel); },
    async kombucha(panel) { await kbDebugPanel(panel); },
    async analytics(panel) {
      const a = await api("GET", "/admin/analytics");
      const L = { users_total: "Всего грибоводов", users_24h: "Новых за 24 ч", dau: "DAU", kombuchas_alive: "Живых грибов", kombuchas_born_24h: "Посажено за 24 ч", games_24h: "Игр за 24 ч", wood_earned_24h: "$₽ начислено за 24 ч" };
      panel.innerHTML = `<div class="kv">${Object.entries(L).map(([k, v]) => `<div class="stat"><b>${a[k]}</b><span>${v}</span></div>`).join("")}</div>`;
    },
    async users(panel) {
      panel.innerHTML = `<input class="input" id="user-q" placeholder="Поиск по нику или email"><div id="user-list" style="margin-top:12px"></div>`;
      const ROLES = ["user", "admin"];
      const load = async () => {
        const { items } = await api("GET", `/admin/users?q=${encodeURIComponent($("#user-q").value)}`);
        $("#user-list").innerHTML = `<table class="list"><tr><th>Ник</th><th>Email</th><th>Роли</th><th></th></tr>${items.map((u) => `<tr data-uid="${u.id}">
          <td><a href="/u/${encodeURIComponent(u.username)}">@${esc(u.username)}</a></td><td>${esc(u.email)}</td>
          <td>${ROLES.map((r) => `<label style="margin-right:8px;white-space:nowrap"><input type="checkbox" value="${r}" ${u.roles.includes(r) ? "checked" : ""} ${r === "user" ? "disabled" : ""}> ${r}</label>`).join("")}</td>
          <td><button class="btn btn-sm" data-save>Сохранить</button></td></tr>`).join("")}</table>`;
        $$("[data-save]").forEach((b) => (b.onclick = async () => {
          const tr = b.closest("tr");
          const roles = $$("input:checked", tr).map((i) => i.value);
          if (!roles.includes("user")) roles.push("user");
          try { await api("PUT", `/admin/users/${tr.dataset.uid}/roles`, { roles }); toast("Роли обновлены"); } catch (_) {}
        }));
      };
      let t; $("#user-q").oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
      await load();
    },
    async captcha(panel) {
      const { value: v } = await api("GET", "/admin/settings/captcha");
      const CATS = { math: "Математика", physics: "Физика", russian: "Русский", literature: "Литература" };
      panel.innerHTML = `<form class="panel form" id="cap-form"><p class="muted">Капча kremle-detect: задания ЕГЭ. Включается только при подозрительной активности: 5+ неудачных входов, частые регистрации или спам.</p>
        <b>Предметы</b>${Object.entries(CATS).map(([k, n]) => `<label class="check"><input type="checkbox" name="cat" value="${k}" ${v.categories.includes(k) ? "checked" : ""}> ${n}</label>`).join("")}
        <label>Вопросов в капче<input type="number" name="question_count" min="1" max="15" value="${v.question_count}"></label>
        <label>Допустимо ошибок<input type="number" name="max_errors" min="0" max="14" value="${v.max_errors}"></label>
        <button class="btn btn-accent">Сохранить</button></form>`;
      $("#cap-form").onsubmit = async (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        try {
          await api("PUT", "/admin/settings/captcha", { value: { categories: f.getAll("cat"), question_count: Number(f.get("question_count")), max_errors: Number(f.get("max_errors")) } });
          toast("Настройки капчи сохранены");
        } catch (_) {}
      };
    },
    async legal(panel) {
      const PAGES = { faq: "FAQ — частые вопросы", rules: "Правила сообщества", terms: "Пользовательское соглашение", privacy: "Политика конфиденциальности", requisites: "Реквизиты" };
      panel.innerHTML = `<select class="input" id="legal-slug">${Object.entries(PAGES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
        <div id="legal-editor" style="margin-top:12px"></div>`;
      const load = async () => {
        const slug = $("#legal-slug").value;
        const [page, versions] = await Promise.all([api("GET", `/api/legal/${slug}`), api("GET", `/admin/legal/${slug}/versions`)]);
        $("#legal-editor").innerHTML = `<form class="form" id="legal-form">
          <label>Заголовок<input name="title" value="${esc(page.title)}"></label>
          ${slug === "faq" ? `<p class="muted" style="font-size:13px">FAQ: каждый вопрос начинай строкой <code>## Вопрос?</code>, ниже — ответ (markdown). Текст до первого <code>##</code> — вступление. На сайте вопросы станут раскрывающимися пунктами с поиском.</p>` : ""}
          <label>Текст (Markdown) · редакция №${page.version}<textarea name="body_md" rows="16">${esc(page.body_md)}</textarea></label>
          <button class="btn btn-accent">Опубликовать новую редакцию</button> <a class="btn btn-ghost" href="/${slug}" target="_blank">Открыть страницу</a></form>
          <h3>История (${versions.items.length})</h3>
          <table class="list">${versions.items.map((v) => `<tr><td>№${v.version}</td><td>${esc(fmtDate(v.created_at))}</td><td>${v.edited_by ? "#" + v.edited_by : "seed"}</td></tr>`).join("")}</table>`;
        $("#legal-form").onsubmit = async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          try { const r = await api("PUT", `/admin/legal/${slug}`, { title: f.get("title"), body_md: f.get("body_md") }); toast(`Опубликована редакция №${r.version}`); load(); } catch (_) {}
        };
      };
      $("#legal-slug").onchange = load;
      await load();
    },
    async modlog(panel) {
      const { items } = await api("GET", "/admin/modlog");
      panel.innerHTML = modlogTable(items);
    },
  });
}

// ---------------------------------------------------------------- notifications
const NOTIF = {
  badge: (p) => [esc(p.emoji || "🏅"), `Новый бейдж: ${esc(p.title)}`, ME ? `/u/${encodeURIComponent(ME.user.username)}` : "#"],
  ban: (p) => ["⛔", `Аккаунт заблокирован. Причина: ${esc(p.reason || "—")}`, "/banned"],
  trade: (p) => [p.accepted ? "🤝" : p.gift ? "🎁" : "🔄", p.accepted ? `@${esc(p.username)} принял(а) твоё предложение обмена` : p.gift ? `@${esc(p.username)} дарит тебе чайный гриб` : `@${esc(p.username)} предлагает обмен грибами`, "/market#trades"],
  kombucha: (p) => ["🍄", esc(p.text || p.message || "Новости с подоконника"), p.kombucha_id ? `/g/${p.kombucha_id}` : "/"],
  sale: (p) => ["💰", `@${esc(p.username)} купил(а) твой гриб «${esc(p.kombucha_name)}» — +${p.amount} $₽`, "/wallet"],
  halloween: (p) => ["🎃", esc(p.text || "На подоконнике случилось что-то странное"), p.kombucha_id ? `/g/${p.kombucha_id}` : "/events"],
  appeal: (p) => ["⚖️", p.decision === "accept" || p.decision === "approve" ? "Апелляцию приняли — блокировка снята" : `Апелляцию отклонили${p.comment ? ": " + esc(p.comment) : ""}`, "/banned"],
};

async function pageNotifications() {
  const root = $("#notifications");
  const d = await api("GET", "/api/notifications");
  root.innerHTML = d.items.length ? d.items.map((n) => {
    const [e, text, href] = (NOTIF[n.kind] || (() => ["🔔", esc(n.kind), "#"]))(n.payload || {});
    return `<a class="notif ${n.is_read ? "" : "unread"}" href="${href}"><span class="e">${e}</span><span>${text}<small>${esc(fmtDate(n.created_at))}</small></span></a>`;
  }).join("") : `<p class="muted">Пока тихо. Гриб растёт, рынок молчит 🍄</p>`;
  $("#read-all").onclick = async () => {
    const r = await api("POST", "/api/notifications/read", {});
    setBell(r.unread);
    $$(".notif.unread", root).forEach((x) => x.classList.remove("unread"));
  };
}

// ---------------------------------------------------------------- мини-игра «Чайный гриб»
const HALLOWEEN_HAT_UI = {
  pumpkin: { emoji: "🎃", title: "Тыква" }, witch: { emoji: "🧙‍♀️", title: "Ведьмина шляпа" },
  horns: { emoji: "😈", title: "Рога" }, ghost_halo: { emoji: "👻", title: "Нимб-призрак" },
  foil: { emoji: "🛸", title: "Шапочка из фольги" },
};
const KB_DISC = [ // [мутация, заливка, обводка] — первая подходящая по приоритету
  ["crystal", "#aef4ff", "#4fc3dc"], ["golden", "#ffd54a", "#b8860b"], ["spotted", "#e0442f", "#9c2414"],
  ["night", "#51639e", "#2c3866"], ["sweet_tooth", "#ffc2e0", "#e58db1"],
];

function shade(hex, f = 0.6) {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => Math.round(v * f));
  return `rgb(${c.join(",")})`;
}
const RAR = { legendary: "Легендарная", epic: "Эпическая", rare: "Редкая", common: "Обычная", event: "Временная хэллоуинская" };
function mutChip(m) {
  return `<span class="kb-mut r-${m.rarity}" title="${esc(RAR[m.rarity] || "")}: ${esc(m.title)}${m.expires_at ? ` · временно до ${esc(fmtDate(m.expires_at))}` : ""}${m.inherited ? " (унаследована)" : ""}">${esc(m.emoji)} ${esc(m.title)}${m.serial ? ` <b class="kb-serial">#${m.serial}</b>` : ""}${m.inherited ? " 🧬" : ""}</span>`;
}
async function kombuchaCardModal(id) {
  let d;
  try { d = (await api("GET", `/api/kombucha/${id}/card`, undefined, { quiet: true })).kombucha; } catch (_) { return; }
  const HOW = { grown: "вырастил(а)", gift: "получил(а) в подарок", trade: "выменял(а)", sale: "купил(а)" };
  modal(`<div class="kb-cardm"><div class="kb-cardm-svg">${kombuchaSVG(d)}</div>
    <h2>${esc(d.name)} ${d.frozen ? "🧊" : ""}</h2>
    <div class="muted">${esc(d.stage.title)} · ${d.xp} XP · поколение ${d.generation} · владелец <a href="/u/${encodeURIComponent(d.owner)}">@${esc(d.owner)}</a>${d.price != null ? ` · 🏷 ${d.price} $₽` : ""}</div>
    <h3>Мутации</h3>${d.mutations.length ? `<table class="kb-cardm-t">${d.mutations.map((m) => `<tr><td>${esc(m.emoji)} ${esc(m.title)}</td><td>${esc(RAR[m.rarity] || "")}</td><td>${m.serial != null ? `<b>#${m.serial}</b> из ${m.issued}` : "временно"}</td></tr>`).join("")}</table>` : `<p class="muted">Без мутаций</p>`}
    <h3>История владельцев</h3>${d.owners.length ? `<ol class="kb-owners">${d.owners.map((o) => `<li>@${esc(o.username || "?")} — ${HOW[o.how] || esc(o.how)}${o.price ? ` за ${o.price} $₽` : ""} <small class="muted">${esc(fmtDate(o.at))}</small></li>`).join("")}</ol>` : `<p class="muted">Всю жизнь у одного хозяина — @${esc(d.owner)}</p>`}
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Закрыть</button></div></div>`);
}
document.addEventListener("toggle", (e) => {
  const d = e.target;
  if (!d.dataset?.fold) return;
  localStorage.setItem(`fold:${d.dataset.fold}`, d.open ? "1" : "0");
  if (d.dataset.fold === "kb-muts") { const sm = d.querySelector("summary"); sm.textContent = sm.textContent.replace(/развернуть|свернуть/, d.open ? "свернуть" : "развернуть"); }
  const hint = d.querySelector(".kb-fold-hint");
  if (hint) hint.textContent = d.open ? "свернуть" : "развернуть";
}, true);
document.addEventListener("click", (e) => {
  const c = e.target.closest("[data-kcard]");
  if (c && !e.target.closest("button, a, .kb-pick")) kombuchaCardModal(c.dataset.kcard);
});

function kombuchaCard(k, extra = "") {
  return `<div class="kb-card r-${k.mutations?.[0]?.rarity || "none"}" data-kcard="${k.id}" title="Открыть карточку гриба"><div class="kb-card-svg">${kombuchaSVG(k, { small: true })}</div>
    <b>${esc(k.name)}</b><small class="muted">${esc(k.stage.title)} · ${k.xp} XP${k.generation > 1 ? ` · пок. ${k.generation}` : ""}</small>
    ${k.mutations.length ? `<div class="kb-card-muts">${k.mutations.slice(0, 3).map(mutChip).join("")}${k.mutations.length > 3 ? `<details class="kb-card-more"><summary>ещё ${k.mutations.length - 3}</summary>${k.mutations.slice(3).map(mutChip).join("")}</details>` : ""}</div>` : `<small class="muted">без мутаций</small>`}
    ${extra}</div>`;
}

const KB_MOOD = {
  happy: ["😊", "Доволен жизнью"], hungry: ["🥺", "Голодный — хочет сахара"], thirsty: ["🥵", "Хочет заварки"],
  dirty: ["🤢", "Банка грязная"], sad: ["😢", "Грустит — погладь или поговори"], sticky: ["🥴", "Сахарная кома"],
  moldy: ["🦠", "Заплесневел — нужна уксусная ванна"], dead: ["💀", "Закис"],
};

// ---- косметика мутаций: у КАЖДОЙ мутации свой видимый слой, слои складываются.
// Место действия (гриб / комбуча / банка), вид эффекта и расположение выводятся из кода мутации,
// цвет и эмодзи — из самой мутации, редкость усиливает эффект.
const kbHash = (s) => { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.codePointAt(0), 16777619); return h >>> 0; };
const KB_OWN_FX = new Set(["crown", "scholar", "survivor", "phoenix", "chatty", "holivar", "sparkle", "spotted", "striped", "crystal", "cosmic", "bubbly", "early", "clean_freak", "glow", "jelly", "rainbow"]);
function kbMutFx(k, w, h, top, level) {
  const L = { disc: [], edge: [], liquid: [], jar: [], lid: [], outside: [], glow: [], glass: [], lidColor: null, discColors: [] };
  const R = { common: 1, rare: 1.3, epic: 1.7, legendary: 2.2 };
  // мордочка — в центре диска: запретная зона ±faceR по X (формула масштаба — как в kombuchaSVG)
  const faceK = Math.min(1.25, Math.max(0.75, h / 16)), faceR = 22 * faceK;
  const offFace = (x, pad = 0) => (Math.abs(x) < faceR + pad ? Math.sign(x || 1) * (faceR + pad) : x);
  let side = 0;                                                    // стикеры — по бокам, поочерёдно слева/справа
  const sideSlot = (fs) => {
    const i = side++, sign = i % 2 ? 1 : -1, row = Math.floor(i / 2);
    const room = Math.max(w * 0.92 - faceR - fs / 2, fs);         // сколько места между мордочкой и краем
    const x = sign * (faceR + fs / 2 + 2 + ((row * fs * 0.9) % room));
    const y = (row % 2 ? 0.35 : -0.25) * h;
    return [x, y];
  };
  (k.mutations || []).forEach((m, idx) => {
    const hs = kbHash(m.code), col = m.color || "#fff", dk = shade(col), r = R[m.rarity] || 1;
    const rnd = (n) => (kbHash(m.code + n) % 1000) / 1000;          // стабильные «случайные» числа мутации
    if (idx < 3) L.discColors.push(col);
    if (m.rarity === "legendary" || m.rarity === "epic") L.glow.push(`drop-shadow(0 0 ${m.rarity === "legendary" ? 7 : 4}px ${col})`);
    if (KB_OWN_FX.has(m.code) || m.code.startsWith("halloween_")) return; // у этих — ручная отрисовка ниже
    const place = hs % 3, kind = (hs >> 3) % 4;
    if (place === 0) {                                                // ГРИБ
      if (kind === 0) for (let i = 0; i < 2 + Math.round(r * 1.5); i++)
        L.disc.push(`<ellipse cx="${offFace((rnd("x" + i) - 0.5) * 1.5 * w, w * 0.08 * r).toFixed(1)}" cy="${((rnd("y" + i) - 0.5) * 1.2 * h).toFixed(1)}" rx="${(w * 0.08 * r).toFixed(1)}" ry="${(h * 0.2 * r).toFixed(1)}" style="fill:${dk}" opacity=".8"/>`);
      else if (kind === 1) L.disc.push(`<ellipse rx="${(w * (0.35 + rnd("r") * 0.5)).toFixed(1)}" ry="${(h * (0.35 + rnd("r") * 0.5)).toFixed(1)}" style="fill:none;stroke:${dk}" stroke-width="${(2 * r).toFixed(1)}" stroke-dasharray="${rnd("d") > 0.5 ? "4 3" : "none"}" opacity=".85"/>`);
      else if (kind === 2) { const n = 3 + Math.round(r * 2);           // выросты по краю
        for (let i = 0; i < n; i++) { const a = Math.PI * (1.1 + 0.8 * (i + 0.5) / n + (rnd("a") - 0.5) * 0.1);
          L.edge.push(`<circle cx="${(Math.cos(a) * w * 0.92).toFixed(1)}" cy="${(Math.sin(a) * h * 0.95).toFixed(1)}" r="${(3 + r * 1.5).toFixed(1)}" style="fill:${col};stroke:${dk}" stroke-width="1"/>`); } }
      else { const fs = Math.min(11 * r, h * 1.4 + 6), [sx, sy] = sideSlot(fs);
        L.disc.push(`<text x="${sx.toFixed(1)}" y="${sy.toFixed(1)}" font-size="${fs.toFixed(0)}" text-anchor="middle" class="kb-sticker">${esc(m.emoji)}</text>`); }
    } else if (place === 1) {                                         // КОМБУЧА (жидкость)
      if (kind === 0) for (let i = 0; i < 3 + Math.round(r * 2); i++)  // цветные пузырьки-частицы
        L.liquid.push(`<circle class="kb-bubble" cx="${(44 + rnd("p" + i) * 132).toFixed(0)}" cy="196" r="${(2 + rnd("s" + i) * 2.5 * r).toFixed(1)}" style="fill:${col};stroke:${dk};stroke-width:.6;animation-delay:${(rnd("t" + i) * 4).toFixed(2)}s"/>`);
      else if (kind === 1) L.liquid.push(`<path d="M30,${(top + level * (0.35 + rnd("h") * 0.5)).toFixed(0)} Q70,${(top + level * 0.4).toFixed(0)} 110,${(top + level * (0.35 + rnd("h") * 0.5)).toFixed(0)} T190,${(top + level * 0.6).toFixed(0)} L190,230 L30,230 Z" style="fill:${col}" opacity="${Math.min(0.45, 0.22 * r).toFixed(2)}"/>`);
      else if (kind === 2) L.liquid.push(`<text x="${(50 + rnd("x") * 120).toFixed(0)}" y="${(top + h + 26 + rnd("y") * Math.max(level - h - 40, 10)).toFixed(0)}" font-size="${(13 * r).toFixed(0)}" class="kb-drift" style="animation-delay:${(rnd("t") * 3).toFixed(1)}s">${esc(m.emoji)}</text>`);
      else for (let i = 0; i < 4; i++)                                // искорки в чае
        L.liquid.push(`<circle cx="${(44 + rnd("x" + i) * 132).toFixed(0)}" cy="${(top + 10 + rnd("y" + i) * Math.max(level - 16, 10)).toFixed(0)}" r="${(1.4 * r).toFixed(1)}" class="kb-star" style="fill:${col};animation-delay:${(i * 0.4).toFixed(1)}s"/>`);
    } else {                                                          // БАНКА
      if (kind === 0) L.jar.push(`<text x="${(62 + rnd("x") * 96).toFixed(0)}" y="${(120 + rnd("y") * 70).toFixed(0)}" font-size="${(15 * r).toFixed(0)}" text-anchor="middle" class="kb-jar-sticker">${esc(m.emoji)}</text>`);
      else if (kind === 1) L.glass.push(col);                         // тонировка стекла
      else if (kind === 2) { L.lidColor = L.lidColor || col; L.lid.push(`<circle cx="${(70 + rnd("x") * 80).toFixed(0)}" cy="17" r="${(3 * r).toFixed(1)}" style="fill:${dk}"/>`); }
      else L.outside.push(`<text x="${rnd("s") > 0.5 ? 16 + rnd("x") * 10 : 196 + rnd("x") * 10}" y="${(40 + rnd("y") * 170).toFixed(0)}" font-size="${(12 * r).toFixed(0)}" class="kb-acc kb-orbit ${m.rarity}" style="animation-delay:${(rnd("t") * 2).toFixed(1)}s">${esc(m.emoji)}</text>`);
    }
  });
  return L;
}

// ---- Звуки бульков (Web Audio, без файлов). Бульк = синус со взлётом высоты и быстрым затуханием —
// так звучит лопающийся пузырь. Звук можно выключить (кнопка 🔊 в игре), выбор запоминается.
const kbSnd = {
  ctx: null,
  get muted() { return localStorage.getItem("kb-mute") === "1"; },
  set muted(v) { localStorage.setItem("kb-mute", v ? "1" : "0"); },
  ac() {
    if (!this.ctx) { const C = window.AudioContext || window.webkitAudioContext; if (!C) return null; this.ctx = new C(); }
    if (this.ctx.state === "suspended") this.ctx.resume?.();
    return this.ctx;
  },
  // один пузырь: f0 → f1 за sweep секунд, громкость vol, длина dur
  blip(at, f0, f1, sweep, dur, vol, type = "sine") {
    const c = this.ctx, o = c.createOscillator(), g = c.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, at);
    o.frequency.exponentialRampToValueAtTime(f1, at + sweep);
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(vol, at + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    o.connect(g).connect(this.out());
    o.start(at); o.stop(at + dur + 0.02);
  },
  out() {                                                 // общий выход с мягким фильтром (убирает «компьютерность»)
    if (!this._out) { const f = this.ctx.createBiquadFilter(); f.type = "lowpass"; f.frequency.value = 2400; f.connect(this.ctx.destination); this._out = f; }
    return this._out;
  },
  // короткий бульк «Памяти»: у каждой из 4 банок своя высота (до-ми-соль-до — легко запомнить на слух)
  short(pad, at) {
    if (this.muted || !this.ac()) return;
    const c = this.ctx, t = at ?? c.currentTime, base = [262, 330, 392, 523][pad] || 330;
    this.blip(t, base * 0.7, base * 1.6, 0.06, 0.14, 0.35);
    this.blip(t + 0.03, base * 1.2, base * 2.2, 0.04, 0.08, 0.12);   // «капелька» сверху
  },
  // протяжный бульк медитации: низкий пузырь с долгим хвостом и россыпью мелких пузырьков
  long(at) {
    if (this.muted || !this.ac()) return;
    const c = this.ctx, t = at ?? c.currentTime;
    this.blip(t, 110, 240, 0.35, 1.1, 0.4);
    this.blip(t, 220, 330, 0.5, 0.9, 0.12, "triangle");
    for (let i = 0; i < 4; i++) { const d = 0.12 + i * 0.13 + Math.random() * 0.05, f = 380 + Math.random() * 260;
      this.blip(t + d, f, f * 1.8, 0.05, 0.12, 0.07 - i * 0.012); }
  },
};
function kbMuteBtn(el) {
  const b = document.createElement("button");
  b.className = "kb-med-snd"; b.title = "Звук вкл/выкл";
  const upd = () => (b.textContent = kbSnd.muted ? "🔇" : "🔊");
  upd();
  b.onpointerdown = (e) => e.stopPropagation();
  b.onclick = (e) => { e.stopPropagation(); kbSnd.muted = !kbSnd.muted; upd(); if (!kbSnd.muted) kbSnd.short(2); };
  el.appendChild(b);
}

// ---- Меню и мини-игры гриба. Всё считает сервер: клиент только показывает и собирает действия.
async function kbGamesMenu(k, onDone) {
  let items;
  try { ({ items } = await api("GET", "/api/kombucha/games")); } catch (_) { return; }
  const m = modal(`<h2>🎮 Игры гриба</h2><p class="muted">Награда — по точности: $₽, счастье, опыт, шанс мутации (с 75%). Каждую игру можно повторить через несколько минут.</p>
    <div class="kb-games">${items.map((g) => `<button class="kb-game-card" data-game="${g.code}"><span class="e">${g.emoji}</span><b>${esc(g.title)}</b><small>${esc(g.about)}</small></button>`).join("")}</div>`);
  m.el.querySelectorAll("[data-game]").forEach((b) => (b.onclick = () => {
    kbSnd.ac();                                                   // включить звук внутри жеста (иначе iOS промолчит)
    m.close();
    const g = b.dataset.game;
    if (g === "meditation") return kbMeditate(k, onDone);
    ({ pour: kbPour, memory: kbMemory, sugar: kbSugar, flies: kbFlies })[g](k, onDone);
  }));
}

// общая полноэкранная оболочка игры
function kbGameShell(title, help) {
  const el = document.createElement("div");
  el.className = "kb-med kb-game";
  el.innerHTML = `<button class="kb-med-x" title="Прервать">✕</button><div class="kb-med-top"><b>${esc(title)}</b> <span class="kb-game-hud"></span></div>
    <div class="kb-game-area"></div><div class="kb-med-judge" aria-live="polite"></div><p class="kb-med-help muted">${esc(help)}</p>`;
  document.body.appendChild(el);
  document.body.classList.add("kb-med-on");
  const judge = el.querySelector(".kb-med-judge");
  const sh = {
    el, area: el.querySelector(".kb-game-area"), hud: el.querySelector(".kb-game-hud"), over: false,
    say(text, cls = "") { judge.textContent = text; judge.className = `kb-med-judge ${cls}`; void judge.offsetWidth; judge.classList.add("pop"); },
    close() { sh.over = true; sh.timers.forEach(clearTimeout); cancelAnimationFrame(sh.raf); el.remove(); document.body.classList.remove("kb-med-on"); document.removeEventListener("keydown", sh.key); },
    timers: [], raf: 0,
    later(fn, ms) { sh.timers.push(setTimeout(fn, ms)); },
    key: (e) => { if (e.key === "Escape") { sh.close(); toast("Игра прервана"); } },
    async finish(k, game, body, onDone) {
      if (sh.finishing) return; sh.finishing = true;
      sh.timers.forEach(clearTimeout); cancelAnimationFrame(sh.raf);
      sh.say("Гриб считает…", "count");
      let r;
      try { r = await api("POST", `/api/kombucha/${k.id}/game/${game}/finish`, { ...body, meta: kbMeta() }); } catch (_) { sh.close(); return; }
      sh.over = true;
      const R = r.result, ST = { tea: "🫖 заварка", sweet: "🍬 сахар", clean: "🧽 чистота" };
      const extra = { pour: `налито точно: ${R.rounds?.filter((x) => x.points >= 0.5).length || 0}/${R.rounds?.length || 6}${R.rounds?.some((x) => x.spilled) ? " · пролито: " + R.rounds.filter((x) => x.spilled).length : ""}`,
        memory: `цепочка: ${R.reached}/${R.total}`, sugar: `сахар ${R.caught} · ошибок ${R.wrong} · пропущено ${R.missed}`,
        flies: `отогнано мушек: ${R.swatted}` }[game] || "";
      sh.area.innerHTML = `<div class="kb-med-result"><h2>${esc(R.grade)}</h2><p class="kb-med-acc">Точность: <b>${Math.round(R.accuracy * 100)}%</b></p>${kbBotNote(R)}
        <p class="muted">${esc(extra)}</p>
        ${R.practice ? `<p class="kb-practice">🏋️ Тренировка — играй сколько хочешь. Следующая награда через ${fmtLeft(R.reward_in)}.</p>` : `<p>${R.wood ? `+${R.wood} $₽ · ` : `<span class="muted">$₽ за игры сегодня уже собраны · </span>`}💛 +${R.happy}${R.boost ? ` · ${ST[R.stat]} +${R.boost}` : ""}${R.xp ? ` · +${R.xp} опыта` : ""}</p>`}
        ${R.mutation ? `<p class="kb-med-mut">🧬 ${esc(R.mutation.rarity_title)} мутация: ${esc(R.mutation.emoji)} «${esc(R.mutation.title)}» #${R.mutation.serial}</p>`
          : `<p class="muted">${{ limit: "На этой стадии у гриба уже 3 мутации.", luck: "Мутация не пришла — чем точнее, тем выше шанс.", low: "С 75% точности появляется шанс мутации." }[R.mut_why] || ""}</p>`}
        <button class="btn btn-accent" data-close>Готово</button></div>`;
      el.querySelectorAll(".kb-med-help, .kb-med-judge").forEach((x) => x.remove());
      sh.area.querySelector("[data-close]").onclick = () => sh.close();
      onDone?.(r);
    },
  };
  el.querySelector(".kb-med-x").onclick = () => { sh.close(); toast("Игра прервана"); };
  document.addEventListener("keydown", sh.key);
  return sh;
}

// антиавтокликер: считаем синтетические (не от пользователя) события во время игры
let kbSynthetic = 0;
["pointerdown", "mousedown", "touchstart", "keydown", "click"].forEach((ev) =>
  document.addEventListener(ev, (e) => { if (!e.isTrusted) kbSynthetic++; }, true));
const kbMeta = () => ({ synthetic: kbSynthetic });
const kbBotNote = (R) => R.suspect ? `<p class="kb-bot-note">🤖 Похоже на автокликер — за эту партию награды нет.${R.bot_flags >= 3 ? " Следующая игра — после капчи." : ""}</p>` : "";

async function kbStart(k, game) {
  kbSynthetic = 0;
  try { return await api("POST", `/api/kombucha/${k.id}/game/${game}/start`); } catch (_) { return null; }
}

// 🫖 Налей и не пролей: держишь — льётся, отпускаешь — стоп. 6 раундов, помех всё больше.
// Формулы — зеркало app/services/minigames.py (pour_level / pour_final / pour_target): считает всё равно сервер.
const KB_POUR_MOD = { shake: "📳 банка трясётся", pulse: "💦 струя дёргается", foam: "🫧 пенится", dark: "💡 свет мигает", hide: "🙈 метка спрячется", tiny: "🎯 узкая метка" };
async function kbPour(k, onDone) {
  const G = await kbStart(k, "pour"); if (!G) return;
  const N = G.rounds.length;
  const sh = kbGameShell("🫖 Налей и не пролей", "Зажми палец (или пробел) — льётся чай. Отпусти, когда уровень дойдёт до метки. Банка трясётся — метка ездит; пена поднимется уже после; в темноте считай в уме.");
  const holds = []; let round = 0, t0 = 0, pouring = false, flick = 0;
  const lvlAt = (rd, ms) => {
    const t = Math.max(0, ms) / 1000; let l = rd.rate * t + rd.accel * t * t;
    if (rd.pulse) { const w = rd.pulse.w; l += rd.rate * rd.pulse.p * (Math.sin(w * t - Math.PI / 2) + 1) / w; }
    return l;
  };
  const finalAt = (rd, ms) => lvlAt(rd, ms) * (1 + (rd.foam?.f || 0));
  const targetAt = (rd, ms) => rd.shake ? rd.target + rd.shake.amp * Math.sin(2 * Math.PI * Math.max(0, ms) / rd.shake.period + rd.shake.phase) : rd.target;
  sh.area.innerHTML = `<div class="kb-pour"><div class="kb-pour-mods"></div><div class="kb-pour-stage"><div class="kb-pour-jar"><div class="kb-pour-tea"></div><div class="kb-pour-foam"></div>
    <div class="kb-pour-mark"><span>метка</span></div><div class="kb-pour-stream"></div></div><div class="kb-pour-dark"></div></div><div class="kb-pour-name muted"></div></div>`;
  const $p = (s) => sh.area.querySelector(s);
  const jar = $p(".kb-pour-jar"), tea = $p(".kb-pour-tea"), foam = $p(".kb-pour-foam"), mark = $p(".kb-pour-mark"),
    stream = $p(".kb-pour-stream"), dark = $p(".kb-pour-dark");
  const setup = () => {
    const rd = G.rounds[round];
    jar.className = `kb-pour-jar ${rd.jar}${rd.shake ? " shaking" : ""}`;
    if (rd.shake) jar.style.animationDuration = `${rd.shake.period}ms`;
    mark.classList.toggle("tiny", rd.mods.includes("tiny"));
    mark.style.display = ""; foam.style.height = "0"; dark.classList.remove("on");
    $p(".kb-pour-mods").innerHTML = rd.mods.map((m) => `<span class="kb-pour-mod">${KB_POUR_MOD[m]}</span>`).join("");
    $p(".kb-pour-name").textContent = rd.jar;
    sh.hud.textContent = `раунд ${round + 1}/${N}`;
    draw(0, 0);
  };
  const draw = (lvl, ms, foamLvl = 0) => {
    const rd = G.rounds[round];
    tea.style.height = `${Math.min(100, lvl * 100)}%`;
    foam.style.bottom = `${Math.min(100, lvl * 100)}%`; foam.style.height = foamLvl ? `${Math.max(0, Math.min(110, foamLvl * 100) - Math.min(100, lvl * 100))}%` : "0";
    mark.style.bottom = `${targetAt(rd, ms) * 100}%`;
    stream.style.display = pouring ? "" : "none";
    if (pouring && rd.pulse) stream.style.width = `${4 + 8 * (1 - Math.cos(rd.pulse.w * ms / 1000)) / 2}px`;
    if (pouring && rd.mods.includes("hide") && ms > 150) mark.style.display = "none";
    if (rd.dark) {
      const inDark = pouring && ms >= rd.dark.at && ms < rd.dark.at + rd.dark.dur;
      if (inDark && Math.random() < 0.04) flick = 3;             // лампочка иногда моргает — подсказка на долю секунды
      dark.classList.toggle("on", inDark && flick-- <= 0);
    }
  };
  // до налива метка тоже «плавает» в трясущейся банке — чтобы было видно, куда целиться
  const idle = () => { if (sh.over || pouring || round >= N) return; const rd = G.rounds[round]; if (rd.shake) mark.style.bottom = `${targetAt(rd, 0) * 100}%`; };
  const tick = () => {
    if (!pouring) return;
    const rd = G.rounds[round], ms = performance.now() - t0, lvl = lvlAt(rd, ms);
    draw(lvl, ms);
    if (lvl >= 1.05) up(); else sh.raf = requestAnimationFrame(tick);
  };
  const down = (e) => { if (sh.over || pouring || round >= N || busy || e.target.closest?.(".kb-med-x, .kb-med-snd")) return; e.preventDefault?.(); pouring = true; t0 = performance.now(); tick(); };
  let busy = false;
  const up = () => {
    if (!pouring) return; pouring = false; cancelAnimationFrame(sh.raf); busy = true;
    const ms = Math.round(performance.now() - t0), rd = G.rounds[round], lvl = lvlAt(rd, ms), fin = finalAt(rd, ms), tg = targetAt(rd, ms);
    holds.push(ms);
    dark.classList.remove("on"); mark.style.display = "";
    draw(lvl, ms);
    const show = () => {
      draw(lvl, ms, rd.foam ? fin : 0);
      const err = Math.abs(fin - tg), spilled = lvl >= 1 || fin >= 1;
      sh.say(spilled ? (lvl < 1 ? "Пена полезла через край! 🫧" : "Пролил! 💦") : err <= rd.tol * 0.3 ? "Идеально ✨" : err <= rd.tol ? "Неплохо 👍" : "Мимо метки",
        spilled ? "miss" : err <= rd.tol ? "perfect" : "miss");
      round++;
      if (round >= N) sh.later(() => sh.finish(k, "pour", { token: G.token, holds }, onDone), 900);
      else sh.later(() => { busy = false; setup(); }, 900);
    };
    if (rd.foam) { sh.say("Пенится… 🫧", "count"); sh.later(show, 450); } else show();
  };
  const idleT = setInterval(idle, 50);
  sh.el.addEventListener("pointerdown", down); sh.el.addEventListener("pointerup", up); sh.el.addEventListener("pointerleave", up);
  const kd = (e) => { if (e.code === "Space" && !e.repeat) down(e); }, ku = (e) => { if (e.code === "Space") up(); };
  document.addEventListener("keydown", kd); document.addEventListener("keyup", ku);
  const close0 = sh.close; sh.close = () => { clearInterval(idleT); document.removeEventListener("keydown", kd); document.removeEventListener("keyup", ku); close0(); };
  setup();
}

// 🧠 Память гриба: Simon Says на 4 банках, цепочку раскрывает сервер по шагу.
async function kbMemory(k, onDone) {
  const G = await kbStart(k, "memory"); if (!G) return;
  const sh = kbGameShell("🧠 Память гриба", "Смотри, в каких банках булькает гриб, и повтори цепочку тапами.");
  const PADS = [["🟢", "g"], ["🔵", "b"], ["🟡", "y"], ["🔴", "r"]];
  sh.area.innerHTML = `<div class="kb-mem">${PADS.map(([e, c], i) => `<button class="kb-mem-pad ${c}" data-pad="${i}">${e}</button>`).join("")}</div>`;
  const pads = [...sh.area.querySelectorAll("[data-pad]")];
  let seq = G.seq, input = [], listening = false;
  kbMuteBtn(sh.el); kbSnd.ac();                                  // клик по карточке игры — жест, разблокирует звук
  const flash = (i) => { kbSnd.short(i); pads[i].classList.add("lit"); sh.later(() => pads[i].classList.remove("lit"), 380); };
  const play = () => {
    listening = false; input = []; sh.hud.textContent = `цепочка ${seq.length}/${G.total}`; sh.say("Смотри…", "count");
    seq.forEach((p, i) => sh.later(() => flash(p), 700 + i * 600));
    sh.later(() => { listening = true; sh.say("Повтори!", "good"); }, 700 + seq.length * 600);
  };
  pads.forEach((b) => (b.onclick = async () => {
    if (!listening || sh.over) return;
    const i = +b.dataset.pad; flash(i); input.push(i);
    if (input[input.length - 1] !== seq[input.length - 1] || input.length === seq.length) {
      listening = false;
      let r; try { r = await api("POST", `/api/kombucha/${k.id}/game/memory/step`, { token: G.token, input }); } catch (_) { sh.close(); return; }
      if (r.done) { sh.say(r.ok ? "Вся цепочка! 🏆" : "Ошибка 😵", r.ok ? "perfect" : "miss"); sh.later(() => sh.finish(k, "memory", { token: G.token }, onDone), 800); }
      else { seq = r.seq; sh.say("Верно ✨", "perfect"); sh.later(play, 600); }
    }
  }));
  play();
}

// общий «дождь» предметов для «Сахар или соль» и «Отгони мушек»
// 🍬 Сахар или соль
async function kbSugar(k, onDone) {
  const G = await kbStart(k, "sugar"); if (!G) return;
  const sh = kbGameShell("🍬 Сахар или соль", "Тапай только кубики сахара 🍬. Соль, перец, чеснок и лук не трогай!");
  sh.area.innerHTML = `<div class="kb-rain"><div class="kb-rain-grib">${kombuchaSVG({ ...k, id: "sg" + k.id }, { small: true })}</div></div>`;
  const box = sh.area.firstChild, taps = [], t0 = performance.now();
  let good = 0, bad = 0;
  G.items.forEach((it) => sh.later(() => {
    const d = document.createElement("button");
    d.className = "kb-drop"; d.textContent = it.kind === "sugar" ? "🍬" : G.bad[it.kind];
    d.style.left = `${6 + it.lane * 19}%`; d.style.animationDuration = `${it.fall}ms`;
    d.onpointerdown = (e) => {
      e.stopPropagation(); taps.push({ id: it.id, t: Math.round(performance.now() - t0) }); d.remove();
      if (it.kind === "sugar") { good++; sh.say("Сахарок ✨", "perfect"); } else { bad++; sh.say("Фу! 🤢", "miss"); }
      sh.hud.textContent = `🍬 ${good} · ошибок ${bad}`;
    };
    box.appendChild(d); sh.later(() => d.remove(), it.fall + 50);
  }, it.t));
  sh.later(() => sh.finish(k, "sugar", { token: G.token, taps }, onDone), G.length + 200);
}

// 🪰 Отгони мушек
async function kbFlies(k, onDone) {
  const G = await kbStart(k, "flies"); if (!G) return;
  const sh = kbGameShell(HALLOWEEN_ACTIVE ? "🦇 Прогони ночной рой" : "🪰 Отгони мушек", HALLOWEEN_ACTIVE ? "Летучие мыши и ночные мушки слетаются к банке — отгони их!" : "Мушки летят к банке — тапни каждую, пока не села. Три севшие — конец.");
  sh.area.innerHTML = `<div class="kb-flies"><div class="kb-flies-jar">${kombuchaSVG({ ...k, id: "fl" + k.id }, { small: true })}</div></div>`;
  const box = sh.area.firstChild, taps = [], t0 = performance.now();
  let lives = G.lives, swat = 0, ended = false;
  const hud = () => (sh.hud.textContent = `${"❤️".repeat(Math.max(lives, 0))}${"🖤".repeat(G.lives - Math.max(lives, 0))} · отогнано ${swat}`);
  hud();
  const end = () => { if (ended) return; ended = true; sh.later(() => sh.finish(k, "flies", { token: G.token, taps }, onDone), 400); };
  G.flies.forEach((f) => sh.later(() => {
    if (ended) return;
    const d = document.createElement("button");
    const a = (f.angle * Math.PI) / 180;
    d.className = "kb-fly halloween-fly"; d.textContent = HALLOWEEN_ACTIVE ? (Math.random() < 0.5 ? "🦇" : "🪰") : "🪰";
    d.style.setProperty("--fx", `${Math.cos(a) * 48}vmin`); d.style.setProperty("--fy", `${Math.sin(a) * 48}vmin`);
    d.style.animationDuration = `${f.dur}ms`;
    let gone = false;
    d.onpointerdown = (e) => {
      e.stopPropagation(); if (gone || ended) return; gone = true;
      taps.push({ id: f.id, t: Math.round(performance.now() - t0) }); swat++; hud();
      d.classList.add("swat"); sh.later(() => d.remove(), 250); sh.say("Шлёп! 👋", "perfect");
    };
    box.appendChild(d);
    sh.later(() => { if (gone) return; gone = true; d.remove(); if (ended) return; lives--; hud(); sh.say("Села! 😖", "miss"); if (lives <= 0) end(); }, f.dur);
  }, f.t));
  sh.later(end, G.length + 200);
}

// ---- «Медитация гриба»: ритм-тапалка. Ритм и подсчёт — на сервере; здесь только показ и сбор тапов.
async function kbMeditate(k, onDone) {
  let T;
  kbSynthetic = 0;
  try { T = await api("POST", `/api/kombucha/${k.id}/meditate/start`); } catch (_) { return; }
  const el = document.createElement("div");
  el.className = "kb-med";
  el.innerHTML = `<button class="kb-med-x" title="Прервать">✕</button>
    <div class="kb-med-top"><b>🧘 ${esc(T.title)}</b> <span class="muted">${T.bpm} уд/мин</span></div>
    <div class="kb-med-stage">
      <div class="kb-med-grib">${kombuchaSVG({ ...k, id: "med" + k.id }, { small: true })}</div>
      <div class="kb-med-target"></div><div class="kb-med-rings"></div>
    </div>
    <div class="kb-med-judge" aria-live="polite"></div>
    <div class="kb-med-combo"></div>
    <div class="kb-med-bar"><i></i></div>
    <p class="kb-med-help muted">Тапай по экрану (или жми пробел), когда кольцо сойдётся с кругом — в такт бульканью гриба.</p>`;
  document.body.appendChild(el);
  document.body.classList.add("kb-med-on");
  kbMuteBtn(el);
  const $m = (q) => el.querySelector(q);
  const rings = $m(".kb-med-rings"), judge = $m(".kb-med-judge"), combo = $m(".kb-med-combo"), grib = $m(".kb-med-grib"), bar = $m(".kb-med-bar i");
  const APPROACH = 1300;
  const taps = [], hit = new Set();
  let t0 = performance.now(), raf = 0, done = false, streak = 0, spawned = 0;
  const ac = kbSnd.ac(), aBase = ac ? ac.currentTime : 0;          // аудио-время, соответствующее t0
  const now = () => performance.now() - t0;
  const show = (text, cls) => { if (cls === "count" && judge.textContent === text) return; judge.textContent = text; judge.className = `kb-med-judge ${cls}`; void judge.offsetWidth; judge.classList.add("pop"); };
  const tap = (e) => {
    if (done || e.target.closest(".kb-med-x")) return;
    e.preventDefault?.();
    const t = Math.round(now());
    taps.push(t);
    // локальная подсказка (итог всё равно считает сервер)
    let best = -1, bd = 1e9;
    T.beats.forEach((b, i) => { if (!hit.has(i) && Math.abs(t - b) < bd) { bd = Math.abs(t - b); best = i; } });
    if (best >= 0 && bd <= T.good_ms + 40) {
      hit.add(best); streak++;
      show(bd <= T.perfect_ms + 30 ? "Идеально ✨" : "Хорошо 👍", bd <= T.perfect_ms + 30 ? "perfect" : "good");
    } else { streak = 0; show("Мимо", "miss"); }
    combo.textContent = streak >= 3 ? `комбо ×${streak}` : "";
  };
  const key = (e) => { if (e.code === "Space" || e.key === "Enter") tap(e); if (e.key === "Escape") abort(); };
  const cleanup = () => {
    cancelAnimationFrame(raf);
    document.removeEventListener("keydown", key);
    el.remove(); document.body.classList.remove("kb-med-on");
  };
  const abort = () => { done = true; cleanup(); toast("Медитация прервана — гриб слегка обиделся"); };
  const loop = () => {
    const t = now();
    // отсчёт
    if (t < T.beats[0] - APPROACH) show(String(Math.ceil((T.beats[0] - APPROACH - t) / 1000) || "…"), "count");
    // новые кольца
    while (spawned < T.beats.length && T.beats[spawned] - APPROACH <= t) {
      const r = document.createElement("div");
      r.className = "kb-med-ring";
      r.style.animationDuration = `${APPROACH}ms`;
      rings.appendChild(r);
      setTimeout(() => r.remove(), APPROACH + 250);
      const bt = T.beats[spawned];
      if (ac) kbSnd.long(Math.max(ac.currentTime, aBase + bt / 1000));   // звук ставим в очередь аудио — ровно в такт
      setTimeout(() => { grib.classList.remove("beat"); void grib.offsetWidth; grib.classList.add("beat"); }, Math.max(0, bt - t));
      spawned++;
    }
    // пропущенные удары
    T.beats.forEach((b, i) => { if (!hit.has(i) && t - b > T.good_ms + 60 && !hit.has("m" + i)) { hit.add("m" + i); streak = 0; combo.textContent = ""; show("Мимо", "miss"); } });
    bar.style.width = `${Math.min(100, (t / T.length) * 100)}%`;
    if (t >= T.length) return finish();
    raf = requestAnimationFrame(loop);
  };
  const finish = async () => {
    done = true;
    cancelAnimationFrame(raf);
    judge.textContent = "Гриб осмысляет…"; judge.className = "kb-med-judge count";
    let r;
    try { r = await api("POST", `/api/kombucha/${k.id}/meditate/finish`, { token: T.token, taps, meta: kbMeta() }); }
    catch (_) { cleanup(); return; }
    const R = r.result;
    el.querySelector(".kb-med-stage").insertAdjacentHTML("afterend", `<div class="kb-med-result">
      <h2>${esc(R.grade)}</h2>
      <p class="kb-med-acc">Точность: <b>${Math.round(R.accuracy * 100)}%</b></p>${kbBotNote(R)}
      <p class="muted">✨ идеально ${R.perfect} · 👍 хорошо ${R.good} · мимо ${R.miss}${R.extra ? ` · лишних тапов ${R.extra}` : ""}</p>
      ${R.practice ? `<p class="kb-practice">🏋️ Тренировка — играй сколько хочешь. Следующая награда через ${fmtLeft(R.reward_in)}.</p>` : `<p>${R.wood ? `+${R.wood} $₽ · ` : `<span class="muted">$₽ за сегодня уже собраны · </span>`}💛 +${R.happy} счастья${R.xp ? ` · +${R.xp} опыта` : ""}</p>`}
      ${R.mutation ? `<p class="kb-med-mut">🧬 ${esc(R.mutation.rarity_title)} мутация: ${esc(R.mutation.emoji)} «${esc(R.mutation.title)}» #${R.mutation.serial}</p>` : `<p class="muted">${{ limit: "На этой стадии у гриба уже 3 мутации — новые откроются на следующей стадии.", luck: "Мутация в этот раз не пришла — чем точнее, тем выше шанс (до 15%).", low: "С 75% точности появляется шанс мутации." }[R.mut_why] || ""}</p>`}
      <button class="btn btn-accent" data-close>Готово</button></div>`);
    el.querySelectorAll(".kb-med-help, .kb-med-combo, .kb-med-judge, .kb-med-bar").forEach((x) => x.remove());
    el.querySelector("[data-close]").onclick = cleanup;
    onDone?.(r);
  };
  el.addEventListener("pointerdown", tap);
  document.addEventListener("keydown", key);
  $m(".kb-med-x").onclick = abort;
  raf = requestAnimationFrame(loop);
}

// Полноэкранный просмотр гриба: только банка, весь интерфейс сайта скрыт. Выход — Esc, клик/тап или кнопка.
function kbFullscreen(getK) {
  if ($(".kb-fs")) return;
  const k = getK();
  if (!k) return;
  const el = document.createElement("div");
  el.className = "kb-fs";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", `Гриб ${k.name} во весь экран`);
  el.innerHTML = `<div class="kb-fs-art">${kombuchaSVG({ ...k, id: "fs" + k.id })}</div><div class="kb-fs-hint">Esc или тап — выйти</div>`;
  document.body.appendChild(el);
  document.body.classList.add("kb-fs-on");
  const close = () => {
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("fullscreenchange", onFs);
    el.remove();
    document.body.classList.remove("kb-fs-on");
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const onFs = () => { if (!document.fullscreenElement) close(); };
  el.onclick = close;
  document.addEventListener("keydown", onKey);
  el.requestFullscreen?.().then(() => document.addEventListener("fullscreenchange", onFs)).catch(() => {});
  setTimeout(() => el.classList.add("hint-off"), 2500);
}

function kombuchaSVG(k, { small = false } = {}) {
  const st = k.stats, size = k.stage.size;
  const muts = new Set((k.mutations || []).map((m) => m.code));
  const has = (c) => muts.has(c);
  const level = k.alive ? 40 + st.tea * 0.9 : 60;
  const top = 200 - level;
  let tint = k.alive ? `hsl(${28 + (100 - st.tea) * 0.15}, ${45 + st.tea * 0.4}%, ${62 - st.tea * 0.22}%)` : "#6b6b4a";
  if (has("cosmic") && k.alive) tint = "#2a1a4a";
  if (has("halloween_zombie") && k.alive) tint = "#426b3d";
  const w = 34 + size * 11, h = 8 + size * 2.2;
  const cx = 110, cy = top + 4;
  const dirt = k.alive ? (100 - st.clean) / 100 : 0.8;
  const faces = {
    happy: ["M-10,-2 a3,3 0 1,0 0.1,0", "M10,-2 a3,3 0 1,0 0.1,0", "M-8,5 Q0,12 8,5"],
    hungry: ["M-10,-2 a3,3 0 1,0 0.1,0", "M10,-2 a3,3 0 1,0 0.1,0", "M-5,7 a5,4 0 1,0 10,0 a5,4 0 1,0 -10,0"],
    thirsty: ["M-13,-3 L-7,-1", "M13,-3 L7,-1", "M-7,8 Q0,4 7,8"],
    dirty: ["M-13,-2 L-7,-2", "M7,-2 L13,-2", "M-6,7 L6,7"],
    sad: ["M-10,-2 a3,3 0 1,0 0.1,0", "M10,-2 a3,3 0 1,0 0.1,0", "M-8,9 Q0,3 8,9"],
    sticky: ["M-13,-4 L-7,0 M-13,0 L-7,-4", "M7,-4 L13,0 M7,0 L13,-4", "M-8,6 Q-4,10 0,6 Q4,10 8,6"],
    dead: ["M-13,-4 L-7,0 M-13,0 L-7,-4", "M7,-4 L13,0 M7,0 L13,-4", "M-7,8 L7,8"],
  };
  const f = faces[k.mood] || faces.happy;
  const old = KB_DISC.find(([c]) => has(c));
  const top1 = (k.mutations || []).find((m) => m.color);   // сервер сортирует от самой редкой
  const disc = old || (top1 ? [top1.code, top1.color, shade(top1.color)] : null);
  const nb = has("bubbly") ? 12 : 6;
  const bubbles = k.alive ? Array.from({ length: nb }, (_, i) =>
    `<circle class="kb-bubble" cx="${50 + ((i * 23) % 120)}" cy="196" r="${2 + (i % 3)}" style="animation-delay:${(i * 0.53).toFixed(2)}s"/>`).join("") : "";
  const stars = has("cosmic") ? Array.from({ length: 14 }, (_, i) =>
    `<circle cx="${45 + ((i * 41) % 130)}" cy="${top + 12 + ((i * 29) % Math.max(level - 16, 10))}" r="${i % 3 ? 0.9 : 1.6}" fill="#fff" class="kb-star" style="animation-delay:${i * 0.3}s"/>`).join("") : "";
  const spots = Array.from({ length: 7 }, (_, i) =>
    `<ellipse cx="${55 + ((i * 37) % 110)}" cy="${70 + ((i * 53) % 120)}" rx="${6 + (i % 3) * 3}" ry="${4 + (i % 2) * 3}" fill="#4a3b1c"/>`).join("");
  const dots = has("spotted") ? [[-0.72, -0.15], [-0.5, 0.35], [0.5, -0.35], [0.72, 0.1], [0.45, 0.4]].map(([x, y]) =>
    `<ellipse cx="${(Math.sign(x) * Math.max(Math.abs(x * w), 22 * Math.min(1.25, Math.max(0.75, h / 16)) + w * 0.08)).toFixed(1)}" cy="${(y * h).toFixed(1)}" rx="${(w * 0.08).toFixed(1)}" ry="${(h * 0.22).toFixed(1)}" fill="#fff"/>`).join("") : "";
  const stripes = has("striped") ? Array.from({ length: 6 }, (_, i) =>
    `<line x1="${-w + (i + 1) * (w / 3.5)}" y1="${-h}" x2="${-w + (i + 1) * (w / 3.5) - 8}" y2="${h}" stroke="#6b4a1e" stroke-width="3" opacity=".45"/>`).join("") : "";
  const crystal = has("crystal") ? `<path d="M${-w * 0.5},0 L${-w * 0.2},${-h * 0.6} L${w * 0.2},${-h * 0.2} L${w * 0.5},${-h * 0.5} M${-w * 0.2},${-h * 0.6} L0,${h * 0.5}" stroke="#fff" stroke-width="1.5" fill="none" opacity=".8"/>` : "";
  // аксессуары-эмодзи над грибом / вокруг банки
  const faceY = -(h + 12);                      // для аксессуаров над грибом
  const faceK = Math.min(1.25, Math.max(0.75, h / 16));   // лицо масштабируется под толщину диска
  const acc = [];
  if (has("crown")) acc.push(`<text x="0" y="${faceY - 16}" class="kb-acc" font-size="22">👑</text>`);
  else if (has("scholar")) acc.push(`<text x="0" y="${faceY - 14}" class="kb-acc" font-size="20">🎓</text>`);
  if (has("survivor")) acc.push(`<text x="${Math.max(w * 0.62, 22 * faceK + 12)}" y="${4}" class="kb-acc" font-size="14">🩹</text>`);
  if (has("phoenix")) acc.push(`<text x="${-w * 0.7}" y="${faceY + 4}" class="kb-acc kb-flick" font-size="16">🔥</text>`);
  if (has("chatty")) acc.push(`<text x="${w * 0.6}" y="${faceY}" class="kb-acc" font-size="14">💬</text>`);
  const hat = HALLOWEEN_HAT_UI[k.halloween_hat];
  if (hat) acc.push(`<text x="0" y="${faceY - 22}" class="kb-acc kb-halloween-hat" font-size="25">${hat.emoji}</text>`);
  if (has("halloween_eyes")) acc.push(`<text x="0" y="${-h * 0.08}" class="kb-acc kb-burning-eyes" font-size="12">👁️ 👁️</text>`);
  const outside = [];
  if (has("holivar")) outside.push(`<text x="196" y="120" class="kb-acc" font-size="20">⚔️</text>`);
  if (has("sparkle")) outside.push(...[[28, 60], [192, 80], [24, 170], [196, 190]].map(([x, y], i) => `<text x="${x}" y="${y}" class="kb-acc kb-twinkle" font-size="14" style="animation-delay:${i * 0.4}s">✨</text>`));
  // эпические и легендарные — эмодзи на орбите вокруг банки
  const SPECIAL = new Set(["crown", "scholar", "survivor", "phoenix", "chatty", "holivar", "sparkle"]);
  const orbit = [];  // эпические/легендарные теперь рисуются общим слоем kbMutFx
  const OP = [[20, 40], [200, 44], [14, 110], [206, 150], [22, 200], [198, 214]];
  orbit.forEach((m, i) => outside.push(`<text x="${OP[i][0]}" y="${OP[i][1]}" class="kb-acc kb-orbit ${m.rarity}" font-size="${m.rarity === "legendary" ? 20 : 16}" style="animation-delay:${i * 0.5}s">${esc(m.emoji)}</text>`));
  if (has("early")) outside.unshift(`<circle cx="110" cy="120" r="108" fill="url(#kb-halo)"/>`);
  const FX = kbMutFx(k, w, h, top, level);
  const gid = `${k.id || 0}${small ? "s" : ""}`;
  const discFill = !old && FX.discColors.length > 1
    ? `url(#kb-dg-${gid})` : null;
  const cls = ["kb-svg", k.frozen ? "frozen" : "", `mood-${k.mood}`, ...[...muts].map((c) => `mut-${c}`), small ? "small" : ""].join(" ");
  return `<svg class="${cls}" viewBox="0 0 220 230" role="img" aria-label="Чайный гриб ${esc(k.name)}: ${esc(k.stage.title)}">
    <defs><clipPath id="kb-jar-${k.id || 0}"><path d="M40,40 Q40,28 55,26 L165,26 Q180,28 180,40 L184,200 Q184,214 168,214 L52,214 Q36,214 36,200 Z"/></clipPath>
      ${discFill ? `<linearGradient id="kb-dg-${gid}" x1="0" x2="1" y1="0" y2="1">${FX.discColors.map((c, i) => `<stop offset="${(i / (FX.discColors.length - 1) * 100).toFixed(0)}%" stop-color="${c}"/>`).join("")}</linearGradient>` : ""}
      <radialGradient id="kb-halo"><stop offset="0%" stop-color="#ffb347" stop-opacity=".45"/><stop offset="100%" stop-color="#ffb347" stop-opacity="0"/></radialGradient></defs>
    ${outside.join("")}${FX.outside.join("")}
    <rect x="60" y="6" width="100" height="22" rx="6" class="kb-lid"${FX.lidColor ? ` style="fill:${FX.lidColor};stroke:${shade(FX.lidColor)}"` : ""}/>${FX.lid.join("")}
    <g clip-path="url(#kb-jar-${k.id || 0})">
      <path class="kb-liquid" data-y="${top}" d="M30,${top} Q70,${top - 4} 110,${top} T190,${top} L190,230 L30,230 Z" fill="${tint}"/>
      <path class="kb-liquid-surface" data-y="${top}" d="M30,${top} Q70,${top - 4} 110,${top} T190,${top}" stroke="#ffffff55" stroke-width="2" fill="none"/>
      ${stars}${bubbles}${FX.liquid.join("")}
      ${HALLOWEEN_ACTIVE && k.halloween_gone ? "" : `<g class="${k.alive ? "kb-float" : ""}"><g class="kb-mush" data-cx="${cx}" data-cy="${cy}" transform="translate(${cx},${cy})"${FX.glow.length ? ` style="filter:${FX.glow.slice(0, 3).join(" ")}"` : ""}>
        <g class="kb-disc-wrap">
          <ellipse rx="${w}" ry="${h}" class="kb-disc" ${discFill ? `style="fill:${discFill};stroke:${shade(FX.discColors[0])}"` : disc ? `style="fill:${disc[1]};stroke:${disc[2]}"` : ""}/>
          <ellipse rx="${w * 0.8}" ry="${h * 0.5}" cy="-${h * 0.3}" class="kb-disc-hi"/>
          ${stripes}${dots}${crystal}${FX.disc.join("")}
        </g>${FX.edge.join("")}
        ${size >= 4 ? `<path d="M-${w * 0.7},${h * 0.6} q6,14 12,0 q6,14 12,0 M${w * 0.3},${h * 0.6} q6,14 12,0" class="kb-tendrils"/>` : ""}
        <g class="kb-face" transform="translate(0,${(-h * 0.15).toFixed(1)}) scale(${faceK.toFixed(2)})">
          ${f.map((d) => `<path d="${d}"/>`).join("")}
          ${k.mood === "happy" || k.mood === "sticky" ? `<circle cx="-16" cy="4" r="3" class="kb-blush"/><circle cx="16" cy="4" r="3" class="kb-blush"/>` : ""}
        </g>
        ${acc.join("")}
      </g></g>`}
      <g opacity="${dirt.toFixed(2)}">${spots}</g>
      ${k.mold ? Array.from({ length: 9 }, (_, i) => `<circle cx="${cx + (((i * 37) % 80) - 40) * (w / 60)}" cy="${cy - h * 0.4 + ((i * 13) % 10) - 5}" r="${3 + (i % 3) * 2}" class="kb-moldspot"/>`).join("") : ""}
    </g>
    <path d="M40,40 Q40,28 55,26 L165,26 Q180,28 180,40 L184,200 Q184,214 168,214 L52,214 Q36,214 36,200 Z" class="kb-jar"${FX.glass.length ? ` style="fill:${FX.glass[0]}40;stroke:${FX.glass[FX.glass.length - 1]};stroke-width:4"` : ""}/>${FX.jar.join("")}
    ${k.halloween_web_until ? `<g class="kb-jar-web"><path d="M40 42 Q72 48 96 30 M40 42 Q50 72 38 100 M40 42 L78 66 L96 30 M50 48 L47 70 L70 61 L78 66 L69 84 L50 79 L47 70 M184 190 Q158 177 150 210 M184 190 Q160 198 138 190 M184 190 L160 168 L150 210 M174 184 L168 201 L151 194 L160 168"/></g>` : ""}
    <path d="M52,50 L50,190" class="kb-glare"/>${has("clean_freak") ? `<path d="M64,60 L63,110" class="kb-glare"/>` : ""}
    ${k.frozen ? `<path d="M40,40 Q40,28 55,26 L165,26 Q180,28 180,40 L184,200 Q184,214 168,214 L52,214 Q36,214 36,200 Z" class="kb-ice"/><text x="160" y="60" class="kb-acc" font-size="20">❄️</text>` : ""}
    ${small ? "" : `<g class="kb-mood-badge"><circle cx="186" cy="30" r="17"/><text x="186" y="37" text-anchor="middle" font-size="20">${KB_MOOD[k.mood]?.[0] || "🙂"}</text></g>`}
    <text x="110" y="228" text-anchor="middle" class="kb-label">3 л</text>
  </svg>`;
}

let kbTiltScene = null;
let kbTiltRoll = 0;
let kbTiltListening = false;
function clampN(value, min, max) { return Math.min(max, Math.max(min, value)); }

function applyKbTilt() {
  if (!kbTiltScene || REDUCED_MOTION) return;
  const svg = $(".kb-svg", kbTiltScene);
  if (!svg) return;
  const surface = $(".kb-liquid-surface", svg), liquid = $(".kb-liquid", svg);
  const y = surface?.dataset.y || 100;
  if (surface) surface.setAttribute("transform", `rotate(${-kbTiltRoll} 110 ${y})`);
  if (liquid) liquid.setAttribute("transform", `rotate(${-kbTiltRoll} 110 ${y})`);
  const mush = $(".kb-mush", svg);
  if (mush) {
    const cx = Number(mush.dataset.cx || 110), cy = Number(mush.dataset.cy || 100);
    const x = cx + kbTiltRoll * 1.25;
    const y = cy + Math.abs(kbTiltRoll) * 0.08 + Math.sin(performance.now() / 260) * Math.min(Math.abs(kbTiltRoll) * 0.015, 0.3);
    mush.setAttribute("transform", `translate(${x.toFixed(2)},${y.toFixed(2)}) rotate(${(kbTiltRoll * 0.25).toFixed(2)})`);
  }
  svg.style.setProperty("--sensor-tilt", "0deg");
}

function initTiltScene(scene) {
  if (!scene) return;
  kbTiltScene = scene;
  if (REDUCED_MOTION) {
    const button = $("[data-tilt]", scene);
    if (button) { button.disabled = true; button.textContent = "♿ Анимация выключена"; }
    return;
  }
  if (!scene.dataset.tiltBound) {
    scene.dataset.tiltBound = "1";
    scene.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse" || !window.matchMedia("(hover: hover)").matches) return;
      const r = scene.getBoundingClientRect(), px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
      const svg = $(".kb-svg", scene);
      if (svg) {
        svg.style.setProperty("--cursor-x", `${clampN(px * 6, -3, 3).toFixed(1)}px`);
        svg.style.setProperty("--cursor-y", `${clampN(py * 6, -3, 3).toFixed(1)}px`);
        svg.style.setProperty("--sensor-tilt", `${clampN(px * 2, -1, 1).toFixed(1)}deg`);
      }
    }, { passive: true });
    scene.addEventListener("pointerleave", () => {
      const svg = $(".kb-svg", scene);
      if (svg) { svg.style.setProperty("--cursor-x", "0px"); svg.style.setProperty("--cursor-y", "0px"); svg.style.setProperty("--sensor-tilt", "0deg"); }
    });
  }
  const button = $("[data-tilt]", scene);
  if (!button) return;
  const available = "DeviceOrientationEvent" in window;
  if (!available) { button.disabled = true; button.textContent = "📱 Наклон недоступен"; return; }
  button.textContent = kbTiltListening ? "📱 Наклон включён" : "📱 Включить наклон";
  button.onclick = async () => {
    try {
      const DOE = window.DeviceOrientationEvent;
      if (typeof DOE.requestPermission === "function") {
        const permission = await DOE.requestPermission();
        if (permission !== "granted") throw new Error("Разрешение на датчики не выдано");
      }
      if (!kbTiltListening) {
        window.addEventListener("deviceorientation", (event) => {
          if (Number.isFinite(event.gamma)) {
            kbTiltRoll = clampN(event.gamma, -18, 18);
            applyKbTilt();
          }
        }, { passive: true });
        kbTiltListening = true;
      }
      button.textContent = "📱 Наклон включён";
      applyKbTilt();
    } catch (err) { toast(err.message || "Не удалось включить наклон", true); }
  };
  applyKbTilt();
}

function fmtLeft(sec) {
  if (sec >= 3600) return `${Math.floor(sec / 3600)} ч ${Math.floor((sec % 3600) / 60)} мин`;
  if (sec >= 60) return `${Math.ceil(sec / 60)} мин`;
  return `${sec} с`;
}

async function pageKombucha() {
  const root = $("#kb-root");
  const loadTop = async () => {
    try {
      const t = await api("GET", "/api/kombucha/top", undefined, { quiet: true });
      $("#kb-top").innerHTML = t.items.length ? t.items.map((x) => `<li><a href="/u/${encodeURIComponent(x.username)}">@${esc(x.username)}</a> — «${esc(x.name)}», ${esc(x.stage)} · <b>${x.xp}</b> XP${x.mutations ? ` · 🧬 ${x.mutations}` : ""}${x.generation > 1 ? ` <span class="muted">(поколение ${x.generation})</span>` : ""}</li>`).join("") : `<li class="muted">Пока ни одного гриба. Будь первым!</li>`;
    } catch (_) {}
  };
  loadTop();
  if (!ME) {
    root.innerHTML = `<div class="panel kb-guest">${kombuchaSVG({ name: "Гриша", mood: "happy", alive: true, stats: { tea: 70, clean: 100, sweet: 70, happy: 80 }, stage: { size: 3, title: "Блинчик" }, mutations: [{ code: "sparkle" }] })}
      <p>Чтобы завести свой гриб, войди в аккаунт.</p><a class="btn btn-accent" href="/login?next=/">Войти</a></div>`;
    $("#kb-codex").innerHTML = "";
    return;
  }
  let S, sel = Number(localStorage.getItem("kb-sel")) || null, timer;
  const BTN = [["sugar", "🍬", "Сахар"], ["tea", "☕", "Заварка"], ["clean", "🧽", "Помыть банку"], ["pet", "🤚", "Погладить"]];
  const STAT = [["sweet", "🍬 Сахар"], ["tea", "☕ Заварка"], ["clean", "🧽 Чистота"], ["happy", "😊 Настроение"]];
  const say = (text) => { const b = $("#kb-say"); if (b) { b.textContent = text; b.classList.remove("pop"); void b.offsetWidth; b.classList.add("pop"); } };
  const cur = () => S.items.find((x) => x.id === sel) || S.items[0];
  const ask = (text, def = "") => { const v = prompt(text, def); return v == null ? null : v.trim(); };
  const call = async (method, url, body) => {
    try { return await api(method, url, body ?? {}, { quiet: true }); }
    catch (err) { toast(err.data?.message || "Не получилось", true); return null; }
  };

  const renderJars = () => {
    const tabs = S.items.map((k) => `<button class="kb-jar-tab ${k.id === cur()?.id ? "active" : ""} ${k.alive ? "" : "dead"} ${k.frozen ? "frozen" : ""}" data-sel="${k.id}">
      <span class="kb-jar-mini">${kombuchaSVG(k, { small: true })}</span><span class="kb-jar-name">${esc(k.name)}</span>
      <small>${k.frozen ? (k.price != null ? `🏷 ${k.price} $₽` : "🧊 на полке") : k.alive ? esc(k.stage.title) : "закис 🪦"}${k.dies_in != null && !k.frozen ? " · ⚠️" : ""}</small></button>`);
    for (let i = 0; i < S.jars.free; i++) tabs.push(`<button class="kb-jar-tab empty" data-plant><span class="kb-jar-plus">＋</span><span class="kb-jar-name">Пустая банка</span><small>посадить гриб</small></button>`);
    if (S.jars.jars < S.jars.max) tabs.push(`<button class="kb-jar-tab shop" data-buy><span class="kb-jar-plus">🫙</span><span class="kb-jar-name">Купить банку</span><small>${S.prices.jar} $₽</small></button>`);
    return `<div class="kb-jars">${tabs.join("")}</div>`;
  };

  const renderMain = (k) => {
    if (!k) return `<div class="panel kb-empty"><p>Банка пустая. Посади новый гриб!</p><button class="btn btn-accent" data-plant>🌱 Посадить гриб</button></div>`;
    const st = k.stage;
    const pct = st.next_xp ? Math.round(((k.xp - st.from_xp) / (st.next_xp - st.from_xp)) * 100) : 100;
    const sp = k.sprout_progress;
    const sprout = k.sprout_pending ? `<div class="kb-note">🌱 Отросток готов и ждёт свободную банку. <button class="link-btn" data-buy>Купить банку за ${S.prices.jar} $₽</button></div>`
      : !sp.legend ? `<div class="kb-note muted">🌱 Гриб делится только на последней стадии — «Легенда трёхлитровой банки». Сейчас: «${esc(st.title)}».</div>`
      : sp.count >= sp.max ? `<div class="kb-note muted">🌳 Гриб уже разделился ${sp.max} раза — больше отростков не будет. Династия продолжается в малышах!</div>`
      : `<div class="kb-sprout" title="Легенда делится раз в 7 дней, всего до ${sp.max} раз, если 3 дня за ней ухаживали и на ней нет плесени"><span>🌱 Деление ${sp.count}/${sp.max}:</span>
          <span class="${sp.legend ? "ok" : ""}">${sp.legend ? "✅" : "⏳"} стадия «Легенда»</span>
          <span class="${sp.care_days >= sp.need_days ? "ok" : ""}">${sp.care_days >= sp.need_days ? "✅" : "⏳"} дней ухода ${sp.care_days}/${sp.need_days}</span>
          <span class="${sp.next_in ? "" : "ok"}">${sp.next_in ? `⏳ следующее через ${fmtLeft(sp.next_in)}` : "✅ раз в 7 дней"}</span>
          ${sp.healthy ? "" : `<span>🦠 сначала вылечи плесень</span>`}</div>`;
    const halloweenGone = HALLOWEEN_ACTIVE && k.halloween_gone;
    return `<div class="panel kb-main ${k.alive ? "" : "is-dead"} ${halloweenGone ? "halloween-gone" : ""}">
      <div class="kb-scene">
        <button class="kb-fs-btn" data-fs title="Смотреть гриб во весь экран">⛶</button>
        <button class="kb-tilt-btn" data-tilt title="На телефоне включает управление наклоном">📱 Включить наклон</button>
        ${HALLOWEEN_ACTIVE ? `<button class="kb-music-btn" data-spooky-music aria-pressed="${spookyMusicEnabled ? "true" : "false"}">${spookyMusicEnabled ? "🔇 Выключить музыку" : "🕯️ Включить музыку"}</button>
          ${isHalloweenAdmin() ? `<button class="kb-scare-btn" data-screamer-test title="Проверить скример" aria-label="Проверить скример">👻</button>` : ""}
          <div class="kb-bat-swarm" aria-hidden="true"><span class="kb-bat bat-a">🦇</span><span class="kb-bat bat-b">🦇</span><span class="kb-bat bat-c">🦇</span></div>` : ""}
        <div class="kb-say" id="kb-say">${esc(halloweenGone ? "В банке только комбуча. Я ненадолго исчез." : k.alive ? k.phrase : "Гриб закис… 🪦")}</div>
        ${kombuchaSVG(k)}
        ${halloweenGone ? `<div class="kb-gone-note">🍵 Гриб пропал. В банке осталась комбуча. Попробуй вернуться завтра.</div>` : ""}
      </div>
      <div class="kb-info">
        <div class="kb-name"><h2>${esc(k.name)}</h2><button class="link-btn" data-rename title="Переименовать">✏️</button><a class="link-btn kb-diary-link" href="/g/${k.id}" title="Дневник гриба — можно поделиться">📖 Дневник</a><a class="link-btn kb-diary-link" href="/g/${k.id}#tree" title="Родственное дерево">🌳 Род</a></div>
        <div class="kb-mood mood-${k.mood}">${KB_MOOD[k.mood]?.[0] || ""} ${esc(KB_MOOD[k.mood]?.[1] || "")}</div>
        <div class="kb-stage">${esc(st.title)} · ${k.age_days} дн.${k.generation > 1 ? ` · поколение ${k.generation}` : ""}${k.is_sprout ? " · отросток" : ""}</div>
        <div class="kb-xp"><div class="kb-xp-bar"><span style="width:${pct}%"></span></div>
          <small>${k.xp} XP${st.next_xp ? ` · до стадии «${esc(st.next_title)}» ещё ${st.next_xp - k.xp}` : " · максимальная стадия 👑"} · рекорд ${k.best_xp}</small></div>
        ${k.mutations.length ? `<details class="kb-muts-box" data-fold="kb-muts"${localStorage.getItem("fold:kb-muts") === "1" ? " open" : ""}><summary>🧬 Мутации (${k.mutations.length}) — нажми, чтобы ${localStorage.getItem("fold:kb-muts") === "1" ? "свернуть" : "развернуть"}</summary><div class="kb-muts">${k.mutations.map(mutChip).join("")}</div>
          <div class="kb-mut-slots muted">На каждой стадии — до ${k.mut_per_stage || 3} мутаций этой стадии · ${[1, 2, 3, 4, 5, 6].filter((st) => st <= k.stage.size || k.mut_slots?.[st]).map((st) => { const n = k.mut_slots?.[st] || 0, mx = k.mut_per_stage || 3; return `<span class="${n >= mx ? "full" : ""}">ст.${st}: ${n}/${mx}</span>`; }).join(" · ")}</div></details>` : ""}
        ${k.dies_in != null && k.alive ? `<div class="kb-danger">⚠️ Гриб на грани! Закиснет через ${fmtLeft(k.dies_in)}, если не поднять показатель с нуля.</div>` : ""}
        <div class="kb-stats">${STAT.map(([key, label]) => { const v = k.stats[key];
          return `<div class="kb-stat"><span>${label}</span><div class="kb-bar ${v < 25 ? "low" : v > 90 && key === "sweet" ? "over" : ""}"><span style="width:${v}%"></span></div><b>${v}</b></div>`; }).join("")}</div>
        ${k.frozen ? `<div class="kb-note kb-frozen-note">🧊 Гриб заморожен${k.frozen_at ? ` с ${esc(fmtDate(k.frozen_at))}` : ""}: показатели не падают, банку не занимает, стоит на полке в твоём профиле.
            Продать или обменять можно только замороженный гриб.</div>
          <div class="kb-dead-actions">
            <button class="btn btn-accent" data-unfreeze>🔥 Разморозить</button>
            ${k.price != null ? `<button class="btn btn-ghost" data-unlist>🏷 Снять с продажи (${k.price} $₽)</button>` : `<button class="btn btn-ghost" data-list>💰 Продать</button>`}
            <button class="btn btn-ghost" data-trade>🔄 Обменять / подарить</button></div>`
        : k.alive ? `${k.mold ? `<div class="kb-danger kb-mold">🦠 Плесень! Гриб не растёт и не мутирует, чистота и настроение тают быстрее.
            <button class="btn btn-accent btn-sm" data-act="cure"${k.cooldowns.cure ? " disabled" : ""}>🧪 Уксусная ванна${k.cooldowns.cure ? ` · через ${fmtLeft(k.cooldowns.cure)}` : ""}</button></div>` : ""}
          <div class="kb-next muted">⏬ Показатели упадут через ${fmtLeft(k.next_drop_in)} (раз в 12 часов)${!k.mold && k.stats.clean < 35 ? " · ⚠️ банка грязная — может завестись плесень" : ""}</div>
          <div class="kb-actions">${BTN.map(([a, e, t]) => { const cd = k.cooldowns[a];
            return `<button class="btn kb-act" data-act="${a}"${cd ? " disabled" : ""}><span class="e">${e}</span><span>${t}</span>${cd ? `<small>через ${fmtLeft(cd)}</small>` : ""}</button>`; }).join("")}</div>
          <button class="btn kb-talk" data-act="talk"${k.cooldowns.talk ? " disabled" : ""}>💭 Поговорить с грибом${k.cooldowns.talk ? ` · через ${fmtLeft(k.cooldowns.talk)}` : " — о философии"}</button>
          ${k.alive && !k.frozen ? `<button class="btn kb-med-btn" data-games>🎮 Игры гриба</button>` : ""}
          <div id="kb-quote"></div>
          <button class="btn btn-accent kb-daily" data-act="daily"${k.cooldowns.daily ? " disabled" : ""}>🏆 Бонус дня${k.cooldowns.daily ? ` · через ${fmtLeft(k.cooldowns.daily)}` : ": опыт за игры и $₽ за уход"}</button>
          ${sprout}
          <button class="link-btn kb-freeze" data-freeze title="Заморозить: гриб перестанет требовать ухода и встанет на полку в профиле">🧊 Заморозить и поставить на полку</button>`
        : `<p>Прожил ${k.age_days} дн. и набрал ${k.xp} XP. Покойся с миром, ${esc(k.name)}.</p>
           <div class="kb-dead-actions">
             <button class="btn btn-accent" data-revive>💉 Реанимировать · ${S.prices.revive} $₽</button>
             <button class="btn btn-ghost" data-restart>🌱 Завести заново</button>
             <button class="btn btn-ghost" data-discard>🗑 Выбросить</button></div>
           <small class="muted">Реанимация сохраняет опыт и мутации. «Заново» — поколение +1, опыт с нуля, мутации остаются в коллекции.</small>`}
      </div></div>`;
  };

  const renderCodex = () => {
    const found = new Map(S.codex.map((c) => [c.code, c]));
    const byStage = {};
    S.catalog.forEach((m) => (byStage[m.stage] ||= []).push(m));
    const order = ["legendary", "epic", "rare", "common"];
    const cnt = (r) => S.catalog.filter((m) => m.rarity === r).length, got = (r) => S.catalog.filter((m) => m.rarity === r && found.has(m.code)).length;
    const codexOpen = localStorage.getItem("fold:kb-codex") === "1";
    $("#kb-codex").innerHTML = `<details class="kb-codex-box" data-fold="kb-codex"${codexOpen ? " open" : ""}><summary><h2>🧬 Коллекция мутаций <span class="muted">${found.size}/${S.catalog.length}</span></h2><span class="muted kb-fold-hint">${codexOpen ? "свернуть" : "развернуть"}</span></summary>
      <p class="muted kb-codex-lead">По 40 мутаций на каждую стадию. Каждый выпавший экземпляр получает номер на весь сайт — как подарки в Telegram: «#1» бывает только один.
        Первая находка каждой мутации даёт +15 $₽. Шанс за подходящее действие: обычная 6%, редкая 2,5%, эпическая 1%, легендарная 0,4%. Гриб получает только мутации своей текущей стадии и не больше 3 на стадию — вырос, открылись 3 новых места.</p>
      <div class="kb-rar-legend">${order.map((r) => `<span class="kb-mut r-${r}">${RAR[r]} ${got(r)}/${cnt(r)}</span>`).join("")}</div>
      ${Object.entries(byStage).map(([st, list]) => `<details class="kb-cx-stage-box" data-fold="kb-cx-${st}"${localStorage.getItem(`fold:kb-cx-${st}`) === "0" ? "" : " open"}><summary class="kb-cx-stage">Стадия ${st}: ${esc(list[0].stage_title)} <span class="muted">${list.filter((m) => found.has(m.code)).length}/${list.length}</span></summary>
      <div class="kb-codex">${list.slice().sort((x, y) => order.indexOf(x.rarity) - order.indexOf(y.rarity)).map((m) => { const f = found.get(m.code);
        return f ? `<div class="kb-cx found r-${m.rarity}" style="--mc:${m.color}"><span class="kb-cx-prev" title="Как выглядит мутация">${kombuchaSVG({ id: "cx" + m.code, name: m.title, alive: true, frozen: false, mood: "happy", mold: false, stats: { sweet: 70, tea: 70, clean: 100, happy: 80 }, stage: { size: Math.max(3, m.stage), title: "" }, mutations: [{ ...m }] }, { small: true })}</span><b>${esc(m.title)}</b><small>${RAR[m.rarity]}</small><small class="muted">у «${esc(f.kombucha_name || "?")}» · тираж ${m.issued}</small></div>`
          : `<div class="kb-cx r-${m.rarity}"><span class="e">❓</span><b>???</b><small>${esc(m.hint)}</small><small class="muted">${RAR[m.rarity]} · тираж ${m.issued}</small></div>`; }).join("")}</div></details>`).join("")}</details>`;
  };

  const renderHalloweenTools = (k) => {
    const owned = S.halloween?.owned_hats || [];
    if (!S.halloween?.active && !owned.length && !k?.halloween_hat && !k?.halloween_web_until) return "";
    const hats = owned.map((code) => [code, HALLOWEEN_HAT_UI[code]]).filter((x) => x[1]);
    return `<section class="panel kb-halloween-tools"><h3>🎃 Хэллоуинские находки</h3>
      ${S.halloween?.active ? `<p class="muted">Событие активно — шапки останутся у тебя и после его конца.</p><a class="btn btn-sm btn-ghost" href="/events">🦇 Перейти к ивентам и рейду</a>` : `<p class="muted">Шапки можно носить и после окончания события.</p>`}
      ${k?.halloween_web_until ? `<p class="kb-note">🕸️ На банке временная паутина — исчезнет ${esc(fmtDate(k.halloween_web_until))}.</p>` : ""}
      ${HALLOWEEN_ACTIVE && k?.halloween_gone ? `<p class="kb-note">👻 Сегодня меня нет в банке. Вернусь — или нет.</p>` : ""}
      ${hats.length && k ? `<div class="kb-hat-equip"><label>Надеть на «${esc(k.name)}» <select class="input" id="kb-hat-select"><option value="">Без шапки</option>${hats.map(([code, hat]) => `<option value="${esc(code)}"${k.halloween_hat === code ? " selected" : ""}>${hat.emoji} ${esc(hat.title)}</option>`).join("")}</select></label><button class="btn btn-sm btn-accent" data-equip-hat>Надеть</button></div>` : owned.length ? `<p>В коллекции ${owned.length} ${plural(owned.length, "шапка", "шапки", "шапок")}.</p>` : `<p class="muted">Пока шапок нет. Загляни к другу и нажми «Сладость или гадость».</p>`}
    </section>`;
  };

  const render = () => {
    if (!cur() && S.items.length) sel = S.items[0].id;
    const k = cur();
    if (k) { sel = k.id; localStorage.setItem("kb-sel", sel); }
    root.innerHTML = `<div class="kb-bar-top"><span>🫙 Банки: <b>${S.jars.used}/${S.jars.jars}</b></span><span>Баланс: <a href="/wallet"><b>${S.wood} $₽</b></a></span></div>
      ${renderJars()}${renderMain(k)}${renderHalloweenTools(k)}`;
    initTiltScene($(".kb-scene", root));
    renderCodex();
    setWood(S.wood);
    $$("[data-sel]", root).forEach((b) => (b.onclick = () => { sel = Number(b.dataset.sel); render(); }));
    $$("[data-act]", root).forEach((b) => (b.onclick = () => doAct(b.dataset.act)));
    $$("[data-buy]", root).forEach((b) => (b.onclick = async () => {
      if (!confirm(`Купить банку за ${S.prices.jar} $₽?`)) return;
      const r = await call("POST", "/api/shop/jar");
      if (!r) return;
      toast(r.sprouts.length ? `🫙 Банка куплена, в неё сел отросток «${r.sprouts[0]}» 🌱` : "🫙 Банка куплена — посади в неё гриб!");
      await load();
    }));
    $$("[data-plant]", root).forEach((b) => (b.onclick = async () => {
      const name = ask("Имя нового гриба (уникальное на весь сайт). Оставь пустым — придумаем сами:");
      if (name === null) return;
      const r = await call("POST", "/api/kombucha/plant", { name });
      if (r) { sel = r.kombucha.id; await load(); toast("🌱 Гриб посажен"); }
    }));
    const btn = (sel_) => $(sel_, root);
    if (btn("[data-fs]")) btn("[data-fs]").onclick = () => kbFullscreen(() => cur());
    if (btn("[data-equip-hat]") && k) btn("[data-equip-hat]").onclick = async () => {
      const code = $("#kb-hat-select", root).value || null;
      const r = await call("POST", `/api/events/halloween/hat/${k.id}`, { code });
      if (r) { S.items = S.items.map((x) => x.id === k.id ? r.kombucha : x); S.halloween.owned_hats = r.owned_hats; render(); toast(code ? "Шапка надета 🎃" : "Шапка снята"); }
    };
    const afterGame = (r) => {
      S.items = S.items.map((x) => (x.id === r.kombucha.id ? r.kombucha : x));
      S.wood = r.wood_balance; render();
      if (r.result.mutation) toast(`🧬 Игра открыла мутацию: ${r.result.mutation.emoji} «${r.result.mutation.title}» #${r.result.mutation.serial}!`);
      if (r.halloween_mutation) toast(`👁️ Хэллоуинская мутация: ${r.halloween_mutation.emoji} «${r.halloween_mutation.title}» на три дня`);
    };
    if (btn("[data-games]")) btn("[data-games]").onclick = () => kbGamesMenu(cur(), afterGame);
    const fsOpen = $(".kb-fs-art");
    if (fsOpen && cur()) fsOpen.innerHTML = kombuchaSVG({ ...cur(), id: "fs" + cur().id });     // полноэкранный вид обновляется вместе с данными
    if (btn("[data-rename]")) btn("[data-rename]").onclick = async () => {
      const name = ask("Как назовём гриб? Имя должно быть уникальным на весь сайт.", k.name);
      if (!name || name === k.name) return;
      const r = await call("PATCH", `/api/kombucha/${k.id}`, { name });
      if (r) { await load(); toast(`Теперь его зовут «${r.kombucha.name}»`); }
    };
    if (btn("[data-revive]")) btn("[data-revive]").onclick = async () => {
      if (!confirm(`Реанимировать за ${S.prices.revive} $₽?`)) return;
      if (await call("POST", `/api/kombucha/${k.id}/revive`)) { await load(); toast("💉 Гриб снова жив!"); }
    };
    if (btn("[data-restart]")) btn("[data-restart]").onclick = async () => {
      const name = ask("Имя для нового поколения (пусто — оставить прежнее):", "");
      if (name === null) return;
      if (await call("POST", `/api/kombucha/${k.id}/restart`, { name })) { await load(); toast("🌱 Новое поколение!"); loadTop(); }
    };
    if (btn("[data-freeze]")) btn("[data-freeze]").onclick = async () => {
      if (!confirm("Заморозить гриб? Он перестанет требовать ухода, освободит банку и встанет на полку в профиле. Разморозить можно, когда есть свободная банка.")) return;
      if (await call("POST", `/api/kombucha/${k.id}/freeze`)) { await load(); toast("🧊 Гриб на полке"); }
    };
    if (btn("[data-unfreeze]")) btn("[data-unfreeze]").onclick = async () => {
      if (await call("POST", `/api/kombucha/${k.id}/unfreeze`)) { await load(); toast("🔥 Гриб разморожен"); }
    };
    if (btn("[data-list]")) btn("[data-list]").onclick = async () => {
      const v = ask("За сколько $₽ выставить на рынок? (от 10; 5% комиссии сгорает)", "300");
      if (!v) return;
      if (await call("POST", `/api/kombucha/${k.id}/list`, { price: Number(v) })) { await load(); toast("🏷 Гриб выставлен на рынок"); }
    };
    if (btn("[data-unlist]")) btn("[data-unlist]").onclick = async () => {
      if (await call("DELETE", `/api/kombucha/${k.id}/list`)) { await load(); toast("Снят с продажи"); }
    };
    if (btn("[data-trade]")) btn("[data-trade]").onclick = () => tradeDialog(k, load);
    if (btn("[data-discard]")) btn("[data-discard]").onclick = async () => {
      if (!confirm("Выбросить закисший гриб? Банка освободится.")) return;
      if (await call("DELETE", `/api/kombucha/${k.id}`)) { sel = null; await load(); }
    };
  };

  const doAct = async (action) => {
    const k = cur();
    const r = await call("POST", `/api/kombucha/${k.id}/${action}`);
    if (!r) return;
    S = r; render();
    // В облачке — только цитаты. Исключение — сахарная кома: там гриб стонет.
    const kk = r.kombucha;
    if (kk.mood === "sticky") say(action === "sugar" ? r.message : kk.phrase);
    else if (action === "pet" || action === "talk") say(r.message);   // гриб говорит сам, от первого лица
    else { say(kk.phrase); if (r.message && action !== "talk") toast(r.message); }
    if (r.quote && kk.mood !== "sticky") { const b = $("#kb-say"); if (b) b.title = r.quote.lines.map((l) => l.who).join(", ") + (r.quote.book ? ` — ${r.quote.book}` : ""); }
    if (r.mutation) toast(`🧬 ${r.mutation.rarity_title} мутация: ${r.mutation.emoji} «${r.mutation.title}» #${r.mutation.serial}!${r.mutation.first_time ? " +15 $₽ за новую находку" : ""}`);
    if (r.halloween_mutation) toast(`👁️ Хэллоуинская мутация: ${r.halloween_mutation.emoji} «${r.halloween_mutation.title}» на три дня`);
    if (r.new_badges?.length) newBadgesToast(r.new_badges);
    if (r.stage_up) toast(`🎉 Гриб вырос: теперь это «${r.kombucha.stage.title}»!`);
    if (r.sprout) toast(r.sprout.planted ? `🌱 Гриб дал отросток «${r.sprout.name}»! +50 $₽` : "🌱 Гриб дал отросток, но банки нет — купи её в магазине. +50 $₽");
    if (action === "daily" || r.stage_up || r.sprout) loadTop();
  };
  const load = async () => {
    try { S = await api("GET", "/api/kombucha"); render(); } catch (_) {}
  };
  await load();
  clearInterval(timer);
  timer = setInterval(load, 60000);
}

// ---------------------------------------------------------------- обмен, рынок
async function tradeDialog(k, after) {
  const M = modal(`<h2>🔄 Обмен или подарок</h2>
    <p class="muted">Отдаёшь «${esc(k.name)}». Можно попросить взамен замороженный гриб с полки получателя, а можно просто подарить.</p>
    <label>Кому <input class="input" id="tr-user" placeholder="username" autocomplete="off"></label>
    <label>Подпись (необязательно) <input class="input" id="tr-msg" maxlength="140" placeholder="С днём варенья! 🎂"></label>
    <div id="tr-shelf" class="kb-shelf pick"></div>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Отмена</button><button class="btn btn-ghost" id="tr-gift">🎁 Подарить</button><button class="btn btn-accent" id="tr-send" disabled>🔄 Предложить обмен</button></div>`);
  let want = null, timer;
  const box = M.el.querySelector("#tr-shelf"), send = M.el.querySelector("#tr-send"), inp = M.el.querySelector("#tr-user");
  inp.oninput = () => { clearTimeout(timer); timer = setTimeout(async () => {
    want = null; send.disabled = true;
    const u = inp.value.trim().replace(/^@/, "");
    if (!u) { box.innerHTML = ""; return; }
    try {
      const d = await api("GET", `/api/users/${encodeURIComponent(u)}/shelf`, undefined, { quiet: true });
      box.innerHTML = d.items.length ? `<p class="muted">Выбери, что хочешь взамен:</p>` + d.items.map((x) => `<button type="button" class="kb-pick" data-id="${x.id}">${kombuchaCard(x)}</button>`).join("") : `<p class="muted">На полке у @${esc(u)} пусто — можно только подарить.</p>`;
      box.querySelectorAll("[data-id]").forEach((b) => (b.onclick = () => { box.querySelectorAll(".kb-pick").forEach((x) => x.classList.remove("on")); b.classList.add("on"); want = Number(b.dataset.id); send.disabled = false; }));
    } catch (_) { box.innerHTML = `<p class="muted">Нет такого пользователя</p>`; }
  }, 350); };
  const go = async (wantId) => {
    try {
      await api("POST", "/api/trades", { to_username: inp.value.trim().replace(/^@/, ""), give_id: k.id, want_id: wantId, message: M.el.querySelector("#tr-msg").value.trim() || null });
      toast(wantId ? "Предложение отправлено 🔄" : "Подарок отправлен — ждём, когда примут 🎁");
      M.close(); after?.();
    } catch (_) {}
  };
  M.el.querySelector("#tr-gift").onclick = () => { if (inp.value.trim() && confirm(`Подарить «${k.name}»?`)) go(null); };
  send.onclick = () => go(want);
}

async function pageMarket() {
  const list = $("#mk-list"), tr = $("#mk-trades");
  let sort = "new", rarity = "";
  const load = async () => {
    const d = await api("GET", `/api/market?sort=${sort}${rarity ? `&rarity=${rarity}` : ""}`);
    list.innerHTML = d.items.length ? d.items.map((k) => kombuchaCard(k, `<div class="kb-card-foot"><a href="/u/${encodeURIComponent(k.owner)}">@${esc(k.owner)}</a>
      ${ME && ME.user.username === k.owner ? `<span class="muted">твой · ${k.price} $₽</span>` : `<button class="btn btn-accent btn-sm" data-buy="${k.id}" data-price="${k.price}">Купить · ${k.price} $₽</button>`}</div>`)).join("")
      : `<p class="muted">На рынке пусто. Заморозь гриб и выстави его первым!</p>`;
    list.querySelectorAll("[data-buy]").forEach((b) => (b.onclick = async () => {
      if (!ME) { location.href = "/login?next=/market"; return; }
      if (!confirm(`Купить гриб за ${b.dataset.price} $₽?`)) return;
      try { const r = await api("POST", `/api/market/${b.dataset.buy}/buy`, { price: Number(b.dataset.price) }); setWood(r.wood); toast("🛒 Гриб твой! Он ждёт на полке — разморозь его на странице гриба."); load(); } catch (_) {}
    }));
  };
  $$("[data-sort]").forEach((b) => (b.onclick = () => { sort = b.dataset.sort; $$("[data-sort]").forEach((x) => x.classList.toggle("active", x === b)); load(); }));
  $("#mk-rarity").onchange = (e) => { rarity = e.target.value; load(); };
  const loadTrades = async () => {
    if (!ME) { tr.innerHTML = `<p class="muted"><a href="/login?next=/market">Войди</a>, чтобы меняться грибами.</p>`; return; }
    const d = await api("GET", "/api/trades");
    const row = (t, inc) => `<div class="trade ${t.status}"><div class="trade-side">${t.give ? kombuchaCard(t.give) : "—"}</div>
      <div class="trade-mid">${t.gift ? "🎁" : "⇄"}<small>${inc ? `от @${esc(t.from)}` : `для @${esc(t.to)}`}</small>${t.message ? `<small class="trade-msg">«${esc(t.message)}»</small>` : ""}
        ${t.status === "pending" ? (inc ? `<button class="btn btn-accent btn-sm" data-tr="${t.id}" data-op="accept">Принять</button><button class="btn btn-ghost btn-sm" data-tr="${t.id}" data-op="decline">Отклонить</button>`
          : `<button class="btn btn-ghost btn-sm" data-tr="${t.id}" data-op="cancel">Отменить</button>`) : `<span class="muted">${{ accepted: "✅ принято", declined: "❌ отклонено", cancelled: "отменено" }[t.status]}</span>`}</div>
      <div class="trade-side">${t.want ? kombuchaCard(t.want) : `<span class="muted">${t.gift ? "подарок" : "—"}</span>`}</div></div>`;
    tr.innerHTML = `<h3>Входящие</h3>${d.incoming.map((t) => row(t, true)).join("") || `<p class="muted">Пусто</p>`}
      <h3>Исходящие</h3>${d.outgoing.map((t) => row(t, false)).join("") || `<p class="muted">Пусто. Предложить обмен можно на странице гриба (сначала заморозь его).</p>`}`;
    tr.querySelectorAll("[data-tr]").forEach((b) => (b.onclick = async () => {
      try { await api("POST", `/api/trades/${b.dataset.tr}/${b.dataset.op}`, {}); toast(b.dataset.op === "accept" ? "🤝 Сделка! Новый гриб на полке" : "Готово"); loadTrades(); } catch (_) {}
    }));
  };
  try { await Promise.all([load(), loadTrades()]); } catch (_) {}
}

// ---------------------------------------------------------------- полка в профиле
async function profileExtras(d) {
  const u = d.user, hidden = new Set(d.is_owner ? [] : d.custom.hidden_sections);
  const box = $("#profile-extras");
  if (!box) return;
  const parts = [];
  if (!hidden.has("shelf")) parts.push(`<div class="panel" id="shelf"><h2 style="margin-top:0">🧊 Полка с грибами</h2><div class="kb-shelf" id="shelf-list"><p class="muted">Загружаем…</p></div></div>`);
  box.innerHTML = parts.join("");
  if (!hidden.has("shelf")) {
    try {
      const s = await api("GET", `/api/users/${encodeURIComponent(u.username)}/shelf`, undefined, { quiet: true });
      $("#shelf-list").innerHTML = s.items.length ? s.items.map((k) => kombuchaCard(k, k.price != null ? `<a class="btn btn-sm btn-accent" href="/market">🏷 ${k.price} $₽</a>` : "")).join("")
        : `<p class="muted">${d.is_owner ? "Пусто. Заморозь гриб на <a href=\"/\">странице гриба</a> — и он встанет сюда." : "Пока пусто."}</p>`;
    } catch (_) {}
  }
  if (!d.is_owner && ME && !ME.ban) {
    try {
      const event = await api("GET", "/api/events/state", undefined, { quiet: true });
      if (event.active) {
        const alive = new Set((d.garden || []).filter((k) => k.alive).map((k) => String(k.id)));
        $$("#profile .profile-skin .kb-card[data-kcard]").forEach((card) => {
          const id = card.dataset.kcard;
          if (alive.has(id)) card.insertAdjacentHTML("beforeend", `<button class="btn btn-sm halloween-treat" data-treat="${esc(id)}">🎃 Сладость или гадость</button>`);
        });
        $$("#profile [data-treat]").forEach((button) => { button.onclick = async (e) => {
          e.stopPropagation(); button.disabled = true;
          try {
            const r = await api("POST", `/api/events/halloween/treat/${button.dataset.treat}`, {});
            toast(r.message); button.textContent = "✅ Сегодня уже заходил(а)";
          } catch (_) { button.disabled = false; }
        }; });
      }
    } catch (_) {}
  }
}

// ---------------------------------------------------------------- «Деревянные» ($₽)
async function pageWallet() {
  let before = null;
  const hist = $("#w-history");
  const load = async (more = false) => {
    const d = await api("GET", `/api/wallet${before ? `?before=${before}` : ""}`);
    $("#w-balance").textContent = `${d.balance} $₽`;
    setWood(d.balance);
    if (!more) $("#w-rules").innerHTML = d.rules.map((r) => `<div class="wallet-rule"><b class="plus">+${r.amount} $₽</b><span>${esc(r.title)}${r.reason === "daily_login" ? " (+ до 10 $₽ за стрик)" : ""}</span>${r.daily_cap ? `<small class="muted">до ${r.daily_cap} раз в день</small>` : ""}</div>`).join("")
      + `<p class="muted">Потратить: банка для гриба — ${d.prices.jar} $₽, реанимация гриба — ${d.prices.revive} $₽, грибы на <a href="/market">рынке</a>. Продажа на рынке: тебе 95%, 5% сгорает.</p>`;
    const rows = d.items.map((t) => `<div class="wallet-row"><span class="${t.delta > 0 ? "plus" : "minus"}">${t.delta > 0 ? "+" : ""}${t.delta} $₽</span><span>${esc(t.title)}</span><small class="muted">${esc(fmtDate(t.created_at))} · баланс ${t.balance_after}</small></div>`).join("");
    if (more) hist.insertAdjacentHTML("beforeend", rows);
    else hist.innerHTML = rows || `<p class="muted">Пока пусто. Ответь на вопрос — и первые деревянные твои.</p>`;
    before = d.next_before;
    $("#w-more").hidden = !before;
  };
  $("#w-more").onclick = () => load(true);
  try { await load(); } catch (_) {}
}

// ---------------------------------------------------------------- FAQ
function pageFaq() {
  const input = $("#faq-search");
  if (!input) return;
  const items = [...document.querySelectorAll(".faq-item")];
  const open = () => { const el = location.hash && document.querySelector(location.hash); if (el?.tagName === "DETAILS") el.open = true; };
  open(); window.addEventListener("hashchange", open);
  input.oninput = () => {
    const q = input.value.trim().toLowerCase();
    let n = 0;
    items.forEach((it) => { const hit = !q || it.textContent.toLowerCase().includes(q); it.hidden = !hit; if (hit) n++; if (q && hit) it.open = true; });
    $("#faq-empty").hidden = n > 0;
  };
}

// ---------------------------------------------------------------- сезонные события
async function pageEvents() {
  const root = $("#events-root"), status = $("#events-status"), panel = $("#halloween-panel");
  if (!root || !panel) return;
  let event;
  try { event = await api("GET", "/api/events/state", undefined, { quiet: true }); }
  catch (_) { status.textContent = "Не удалось загрузить расписание события."; return; }
  const renderInactive = () => {
    status.textContent = event.enabled
      ? `Хэллоуин запланирован: ${fmtDate(event.start_at)} — ${fmtDate(event.end_at)}.`
      : "Сейчас нет активных событий.";
    const gifts = (event.raid_gifts || []).slice().reverse().map((gift) =>
      `<li><span>${esc(gift.emoji || "🎁")}</span><div><b>${esc(gift.title)}</b>${gift.description ? `<small>${esc(gift.description)}</small>` : ""}</div></li>`).join("");
    panel.innerHTML = `<h2>🌘 Сейчас тихо</h2><p class="muted">Загляни во время активного ивента — тогда здесь появится общий босс.</p>
      ${gifts ? `<section class="raid-rewards raid-gift-box"><h3>🎁 Твои подарки за рейды</h3><ul>${gifts}</ul></section>` : ""}
      ${isHalloweenAdmin() ? `<button class="btn btn-ghost scare-test" data-screamer-test>👻 Проверить скример</button>` : ""}`;
  };
  if (!event.active) { renderInactive(); return; }
  status.textContent = `Хэллоуин идёт до ${fmtDate(event.end_at)}. Не оставляй грибов одних в темноте.`;
  let raid;
  try { raid = await api("GET", "/api/events/halloween/raid", undefined, { quiet: true }); }
  catch (_) { panel.innerHTML = `<p class="muted">Не удалось загрузить босса. Попробуй обновить страницу.</p>`; return; }
  if (!raid.active) { event.active = false; renderInactive(); return; }

  let partyIds = (raid.party_ids || []).map(Number);
  let partyDirty = false, tapBusy = false, tapAllowedAt = 0;
  const canJoin = () => !!(event.active && ME && !ME.ban
    && (ME.permissions?.includes("kombucha.play") || isHalloweenAdmin()));
  const canTap = () => canJoin() && !tapBusy && Date.now() >= tapAllowedAt
    && raid.available_mushrooms?.length > 0 && partyIds.length > 0;
  const tapLabel = () => {
    if (!ME) return "🔐 Войди, чтобы вступить в рейд";
    if (ME.ban) return "🚫 Аккаунт заблокирован";
    if (!canJoin()) return "🔒 Нет права на участие";
    if (!raid.available_mushrooms?.length) return "🍄 Сначала заведи живого гриба";
    if (!partyIds.length) return "Выставь хотя бы одного гриба";
    return `🗡️ Атаковать · −${partyIds.length} HP`;
  };
  const tap = async () => {
    if (tapBusy || Date.now() < tapAllowedAt || !canTap()) return;
    tapBusy = true;
    tapAllowedAt = Date.now() + 1000;
    const buttons = [$("#halloween-boss", panel), $("#halloween-tap", panel)];
    buttons.forEach((b) => { if (b) b.disabled = true; });
    try {
      const r = await api("POST", "/api/events/halloween/raid/tap", { kombucha_ids: partyIds });
      raid = r;
      partyIds = (r.party_ids || partyIds).map(Number);
      partyDirty = false;
      paint();
      if (r.defeated) toast(r.message || "Стадия побеждена!");
      const boss = $("#halloween-boss", panel);
      if (boss) {
        const effect = r.defeated ? "boss-defeat" : "boss-hit";
        boss.classList.add(effect);
        setTimeout(() => boss.classList.remove(effect), r.defeated ? 850 : 520);
      }
    } catch (_) {} finally {
      setTimeout(() => { tapBusy = false; if (panel.isConnected) paint(); }, Math.max(0, tapAllowedAt - Date.now()));
    }
  };
  const paint = () => {
    const pct = Math.max(0, Math.min(100, raid.hp / raid.max_hp * 100));
    const ready = canTap();
    const available = raid.available_mushrooms || [];
    const selected = new Set(partyIds);
    const teamSlots = [0, 1, 2].map((slot) => {
      const chosen = partyIds[slot] || "";
      const options = available.map((m) => {
        const usedElsewhere = partyIds.some((id, index) => index !== slot && id === m.id);
        return `<option value="${m.id}" ${m.id === chosen ? "selected" : ""} ${usedElsewhere ? "disabled" : ""}>${esc(m.name)} · чистота ${m.stats.clean}, счастье ${m.stats.happy}</option>`;
      }).join("");
      return `<label>Слот ${slot + 1}<select class="input raid-team-select" data-raid-slot="${slot}" ${canJoin() && available.length ? "" : "disabled"}>
        <option value="">— не выставлять —</option>${options}</select></label>`;
    }).join("");
    const stageGifts = (raid.stage_gifts || []).map((gift) => {
      const received = (raid.gifts_received || []).some((item) => item.id === gift.id);
      const remaining = Math.max(0, gift.required_damage - (raid.stage_damage || 0));
      return `<li><b>${esc(gift.emoji)} ${esc(gift.title)}</b> — ${received ? "уже получен" : `нанеси ещё ${remaining} урона на этой стадии`}${gift.description ? `<small>${esc(gift.description)}</small>` : ""}</li>`;
    }).join("");
    const receivedGifts = (raid.gifts_received || []).slice().reverse().map((gift) =>
      `<li><span>${esc(gift.emoji || "🎁")}</span><div><b>${esc(gift.title)}</b>${gift.description ? `<small>${esc(gift.description)}</small>` : ""}</div></li>`).join("");
    const selectedNames = available.filter((m) => selected.has(m.id)).map((m) => esc(m.name));
    panel.innerHTML = `<div class="halloween-event-card">
      <div class="haunt-stage"><span class="haunt-web">🕸️</span><span class="haunt-bats">🦇　🦇</span><span class="haunt-fly fly-a">🪰</span><span class="haunt-fly fly-b">🪰</span>
        <button id="halloween-boss" class="halloween-boss" aria-label="Атаковать босса" ${ready ? "" : "disabled"}>🎃<span>🦠</span></button><span class="haunt-caption">ОН УЖЕ ЗАМЕТИЛ ТЕБЯ</span></div>
      <div class="haunt-info"><p class="eyebrow">ОБЩИЙ РЕЙД · ФАЗА ${raid.phase} · СТАДИЯ ${raid.stage_number}/${raid.stage_count}</p>
        <h2>${esc(raid.boss)}</h2><h3 class="raid-stage-title">${esc(raid.stage_title)}</h3>
        <p>${esc(raid.stage_description || "Один босс для всех игроков сайта.")} Регенерация — <b>${raid.regen_per_minute} HP в минуту</b>.</p>
        <p>Выставь до трёх своих живых грибов: каждый наносит 1 урон. При ударе каждый участник получает +1 чистоты и счастья, но теряет по 1 сахару и заварки.</p>
        <div class="raid-hp"><div class="raid-hp-label"><b>${raid.hp.toLocaleString("ru-RU")} HP</b><span>${raid.max_hp.toLocaleString("ru-RU")} максимум</span></div><div class="raid-hp-bar"><i style="width:${pct}%"></i></div></div>
        <div class="raid-meta"><span>Твой урон: <b>${raid.my_damage}</b></span><span>Урон на стадии: <b>${raid.stage_damage || 0}</b></span><span>Всего урона: <b>${raid.total_damage.toLocaleString("ru-RU")}</b></span></div>
        ${ME ? `<section class="raid-party"><h3>🍄 Твоя боевая группа</h3>${available.length ? `<div class="raid-team-slots">${teamSlots}</div>
          <p class="raid-team-status muted">${partyIds.length ? `Выставлено: ${selectedNames.join(", ")} · урон за удар: ${partyIds.length}` : "Выбери хотя бы одного гриба"}</p>`
          : `<p class="muted">У тебя пока нет живых незамороженных грибов для рейда. Заведи гриб на <a href="/">подоконнике</a>.</p>`}</section>` : ""}
        <button class="btn btn-accent raid-tap" id="halloween-tap" ${ready ? "" : "disabled"}>${tapLabel()}</button>
        ${!ME ? `<a class="btn btn-ghost btn-sm" href="/login?next=/events">🔐 Войти и бить босса вместе</a>` : ""}
        ${stageGifts ? `<section class="raid-rewards"><h3>🎁 Награды этой стадии</h3><ul>${stageGifts}</ul></section>` : ""}
        ${ME && receivedGifts ? `<section class="raid-rewards raid-gift-box"><h3>🎁 Твои подарки за рейд</h3><ul>${receivedGifts}</ul></section>` : ""}
        <div class="haunt-controls">${isHalloweenAdmin() ? `<button class="btn btn-ghost scare-test" data-screamer-test>👻 Проверить скример</button>` : ""}<button class="btn btn-ghost" data-spooky-music aria-pressed="${spookyMusicEnabled ? "true" : "false"}">${spookyMusicEnabled ? "🔇 Выключить музыку" : "🕯️ Включить музыку"}</button></div>
        <p class="muted">«Сладость или гадость» раз в день доступна на живых грибах друзей — открой профиль и постучи по банке.</p></div>
    </div>`;
    $("#halloween-boss", panel).onclick = tap;
    $("#halloween-tap", panel).onclick = tap;
    $$('[data-raid-slot]', panel).forEach((select) => {
      select.onchange = () => {
        const next = $$('[data-raid-slot]', panel).map((item) => item.value ? Number(item.value) : null).filter(Boolean);
        if (new Set(next).size !== next.length) {
          toast("Одного гриба нельзя выставить в два слота", true);
          select.value = partyIds[Number(select.dataset.raidSlot)] || "";
          return;
        }
        partyIds = next;
        partyDirty = true;
        const statusLine = $(".raid-team-status", panel);
        const names = available.filter((m) => partyIds.includes(m.id)).map((m) => m.name);
        if (statusLine) statusLine.textContent = partyIds.length
          ? `Выставлено: ${names.join(", ")} · урон за удар: ${partyIds.length}` : "Выбери хотя бы одного гриба";
        [$("#halloween-boss", panel), $("#halloween-tap", panel)].forEach((button) => {
          if (button) button.disabled = !canTap() || tapBusy;
        });
        const attackButton = $("#halloween-tap", panel);
        if (attackButton) attackButton.textContent = tapLabel();
      };
    });
  };
  paint();
  let raidRefreshBusy = false, raidPoll;
  const refreshRaid = async () => {
    if (raidRefreshBusy || tapBusy || document.hidden) return;
    raidRefreshBusy = true;
    try {
      const fresh = await api("GET", "/api/events/halloween/raid", undefined, { quiet: true });
      if (!fresh.active) {
        event.active = false;
        await applyEventTheme();
        renderInactive();
        clearInterval(raidPoll);
        return;
      }
      const changed = fresh.hp !== raid.hp || fresh.max_hp !== raid.max_hp || fresh.phase !== raid.phase
        || fresh.stage_number !== raid.stage_number || fresh.total_damage !== raid.total_damage
        || fresh.my_damage !== raid.my_damage || fresh.stage_damage !== raid.stage_damage
        || JSON.stringify(fresh.available_mushrooms) !== JSON.stringify(raid.available_mushrooms)
        || JSON.stringify(fresh.gifts_received) !== JSON.stringify(raid.gifts_received);
      if (changed) {
        raid = fresh;
        if (!partyDirty) partyIds = (fresh.party_ids || []).map(Number);
        else partyIds = partyIds.filter((id) => fresh.available_mushrooms.some((m) => m.id === id));
        paint();
      }
    } catch (_) {} finally { raidRefreshBusy = false; }
  };
  raidPoll = setInterval(refreshRaid, 5000);
  window.addEventListener("pagehide", () => clearInterval(raidPoll), { once: true });
}

// ---------------------------------------------------------------- boot
async function pageDiary() {
  const root = $("#diary"), kid = root.dataset.kid, list = $("#diary-list"), more = $("#diary-more");
  let next = null, first = true;
  const row = (e) => `<div class="kb-diary-row ${esc(e.kind)}"><span class="e">${e.emoji}</span><div><p>${esc(e.text)}</p><small class="muted">${esc(new Date(e.at).toLocaleString("ru-RU", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }))}</small></div></div>`;
  const load = async () => {
    let d;
    try { d = await api("GET", `/api/kombucha/${kid}/diary${next ? `?before=${next}` : ""}`); }
    catch (_) { $(".kb-diary-head", root).innerHTML = `<p>Такого гриба нет — может, его и не было 🍄</p>`; return; }
    if (first) {
      const k = d.kombucha; first = false;
      document.title = `Дневник гриба «${k.name}» — schematoz-bulboz.org`;
      $(".kb-diary-head", root).innerHTML = `<div class="kb-diary-art">${kombuchaSVG({ ...k, id: "dy" + k.id }, { small: true })}</div>
        <div><h1>📖 Дневник гриба «${esc(k.name)}»</h1>
        <p class="muted">${esc(k.stage.title)} · ${k.xp} XP · поколение ${k.generation} · ${k.alive ? `живёт ${k.age_days} дн.` : "закис 🪦"}${k.frozen ? " · 🧊 заморожен" : ""}${k.owner ? ` · хозяин <a href="/u/${encodeURIComponent(k.owner)}">@${esc(k.owner)}</a>` : ""}</p>
        <div class="row"><button class="btn btn-accent btn-sm" id="diary-share">🔗 Поделиться</button>${d.mine ? `<a class="btn btn-ghost btn-sm" href="/">🍄 К грибу</a>` : ""}</div></div>`;
      $("#diary-share").onclick = async () => {
        const url = location.href.split("#")[0], title = `Дневник гриба «${k.name}»`;
        if (navigator.share) { try { await navigator.share({ title, url }); return; } catch (_) {} }
        try { await navigator.clipboard.writeText(url); toast("Ссылка скопирована 📋"); } catch (_) { prompt("Скопируй ссылку:", url); }
      };
      if (!d.items.length) list.innerHTML = `<p class="muted">Пока пусто: гриб ещё ничего не пережил. Всё впереди.</p>`;
    }
    list.insertAdjacentHTML("beforeend", d.items.map(row).join(""));
    next = d.next; more.hidden = !next;
  };
  more.onclick = load;
  kbTree($("#kb-tree"), kid);
  await load();
  if (location.hash === "#tree") $("#tree")?.scrollIntoView();
}

// 🌳 Родственное дерево: предки → прародитель → все ветки. Свой гриб подсвечен.
async function kbTree(box, kid) {
  let d;
  try { d = await api("GET", `/api/kombucha/${kid}/tree`, undefined, { quiet: true }); } catch (_) { box.innerHTML = `<p class="muted">Род не нашёлся.</p>`; return; }
  const by = new Map(d.nodes.map((n) => [n.id, { ...n, kids: [] }]));
  for (const n of by.values()) if (n.parent_id && by.has(n.parent_id) && n.id !== d.root) by.get(n.parent_id).kids.push(n);
  const line = new Set([...d.ancestors, d.focus]);
  const node = (n) => `<li${line.has(n.id) ? ' class="on-line"' : ""}>
    <a class="kb-tree-node${n.id === d.focus ? " focus" : ""}${n.alive ? "" : " dead"}" href="/g/${n.id}#tree" title="${esc(n.stage)} · ${n.xp} XP · мутаций ${n.mutations}">
      <span class="kb-tree-e">${n.alive ? (n.frozen ? "🧊" : "🍄") : "🪦"}</span>
      <span class="kb-tree-t"><b>${esc(n.name)}</b><small>${esc(n.stage)} · @${esc(n.owner)}</small>
        <small>${n.emojis.map(esc).join("")}${n.mutations > n.emojis.length ? ` +${n.mutations - n.emojis.length}` : ""}${n.sprouts ? ` · 🌱${n.sprouts}` : ""}</small></span></a>
    ${n.kids.length ? `<ul>${n.kids.map(node).join("")}</ul>` : ""}</li>`;
  const total = d.nodes.length;
  const desc = (n) => n.kids.reduce((a, c) => a + 1 + desc(c), 0);
  const me = by.get(Number(kid));
  box.innerHTML = total === 1
    ? `<p class="muted">Гриб — основатель рода, родственников пока нет. На последней стадии он может разделиться (раз в 7 дней, до 3 раз) — и род начнётся 🌱</p>${`<ul class="kb-tree">${node(by.get(d.root))}</ul>`}`
    : `<p class="muted">В роду ${total} ${plural(total, "гриб", "гриба", "грибов")} · предков у этого: ${d.ancestors.length} · потомков: ${desc(me)}${d.truncated ? " · показаны не все" : ""}</p>
       <div class="kb-tree-wrap"><ul class="kb-tree">${node(by.get(d.root))}</ul></div>`;
}

async function pageHome() {
  $("#home-art").innerHTML = kombuchaSVG({ id: "home", name: "Гриша", mood: "happy", alive: true, stats: { tea: 80, clean: 100, sweet: 70, happy: 90 },
    stage: { size: 4, title: "Медуза" }, mutations: [{ code: "sparkle" }] });
  try {
    const t = await api("GET", "/api/kombucha/top", undefined, { quiet: true });
    $("#home-top").innerHTML = t.items.length ? t.items.slice(0, 8).map((x) => kombuchaCard(x.kombucha,
      `<div class="kb-card-foot"><a href="/g/${x.id}">📖 Дневник</a><small class="muted">@${esc(x.username)}</small></div>`)).join("")
      : `<p class="muted">Пока ни одного гриба. Будь первым!</p>`;
  } catch (_) {}
}

const PAGES = {
  home: pageHome, diary: pageDiary, kombucha: pageKombucha, events: pageEvents, market: pageMarket, wallet: pageWallet,
  profile: pageProfile, login: pageAuth, register: pageAuth, banned: pageBanned, notifications: pageNotifications, admin: pageAdmin,
  settings: pageSettings, faq: pageFaq,
};

(async function boot() {
  initHeader();
  await loadMe();
  await applyEventTheme();
  const fn = PAGES[document.body.dataset.page];
  if (fn) fn();
})();

// ---------------------------------------------------------------- PWA
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
  window.addEventListener("load", () => navigator.serviceWorker?.register("/sw.js", { scope: "/" }).catch(() => {}));
}
let kbInstallPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault(); kbInstallPrompt = e;
  if (localStorage.getItem("pwa-dismissed")) return;
  const b = document.createElement("div");
  b.className = "pwa-banner";
  b.innerHTML = `<span>🍄 Поставь гриба на главный экран — так он не потеряется</span><button class="btn btn-accent btn-sm" data-i>Установить</button><button class="link-btn" data-x>✕</button>`;
  document.body.appendChild(b);
  b.querySelector("[data-i]").onclick = async () => { b.remove(); kbInstallPrompt.prompt(); await kbInstallPrompt.userChoice; kbInstallPrompt = null; };
  b.querySelector("[data-x]").onclick = () => { b.remove(); localStorage.setItem("pwa-dismissed", "1"); };
});
