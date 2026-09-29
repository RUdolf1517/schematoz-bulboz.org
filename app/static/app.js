/* schematoz-bulboz.org — клиент. Без фреймворков: страница = функция в PAGES.
   Весь пользовательский текст выводится через esc() / textContent. */
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const KIND = { opinion: "💬 Мнение", knowledge: "📚 Знания", story: "📖 История", debate: "⚔️ Холивар" };
const REPORT_REASONS = { spam: "Спам", bullying: "Травля / оскорбления", nsfw: "18+", doxxing: "Деанон / личные данные", self_harm: "Самоповреждение", illegal: "Незаконное", other: "Другое" };
const plural = (n, one, few, many) => { const m10 = n % 10, m100 = n % 100; return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? few : many; };
const answersWord = (n) => `${n} ${plural(n, "ответ", "ответа", "ответов")}`;
const fmtDate = (iso) => new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const signed = (n) => (n > 0 ? `+${n}` : `${n}`);
const initial = (name) => esc((name || "?")[0].toUpperCase());
// markdown → простой текст для превью в ленте
const mdPlain = (t) => String(t || "").replace(/!\[[^\]]*\]\([^)]*\)/g, "🖼").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[*_`#>~]+/g, "").trim();
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
  $("#me-mod").hidden = !ME.permissions.includes("report.review");
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
function ratingChip(u) {
  if (!u || u.rating_display == null) return "";
  const cls = u.rating_tier === 2 ? "tier-admin" : u.rating_tier === 1 ? "tier-mod" : "";
  const title = u.rating_tier === 2 ? "Админ: рейтинг бесконечный" : u.rating_tier === 1 ? "Модератор: рейтинг бесконечный (ниже админа)" : "Рейтинг пользователя";
  return `<span class="urating ${cls}" title="${title}">★${esc(u.rating_display)}</span>`;
}

function userLink(u) {
  if (!u) return "";
  return `<a href="/u/${encodeURIComponent(u.username)}">${avatarHTML(u)}@${esc(u.username)}${u.status_emoji ? ` <span class="status-emoji sm">${esc(u.status_emoji)}</span>` : ""}</a>${ratingChip(u)}`;
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

// Панель над textarea: жирный, курсив, код, ссылка, картинка. Вставка картинки из буфера — тоже.
function mdToolbar(ta) {
  if (!ta || ta.dataset.mdReady) return;
  ta.dataset.mdReady = "1";
  const bar = document.createElement("div");
  bar.className = "md-toolbar";
  bar.innerHTML = `<button type="button" data-md="b" title="Жирный"><b>B</b></button><button type="button" data-md="i" title="Курсив"><i>I</i></button><button type="button" data-md="code" title="Код">&lt;/&gt;</button><button type="button" data-md="link" title="Ссылка">🔗</button><label class="md-img" title="Картинка">📷<input type="file" accept="image/*" hidden></label><span class="md-hint">markdown</span>`;
  ta.parentNode.insertBefore(bar, ta);
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-md]");
    if (!b) return;
    ({ b: () => wrapSelection(ta, "**"), i: () => wrapSelection(ta, "_"), code: () => wrapSelection(ta, "`"),
       link: () => wrapSelection(ta, "[", "](https://)") })[b.dataset.md]();
  });
  const put = async (file) => {
    try { const r = await uploadImage(file); insertAtCursor(ta, (ta.value && !ta.value.endsWith("\n") ? "\n" : "") + r.markdown + "\n"); } catch (_) {}
  };
  const fileIn = $("input[type=file]", bar);
  fileIn.onchange = () => { if (fileIn.files[0]) put(fileIn.files[0]); fileIn.value = ""; };
  ta.addEventListener("paste", (e) => {
    const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith("image/"));
    if (f) { e.preventDefault(); put(f); }
  });
}

function newBadgesToast(codes) {
  if (codes && codes.length) toast(`🏅 Новый бейдж! Загляни в профиль`);
}

function reportDialog(targetType, targetId) {
  if (!requireLogin()) return;
  const opts = Object.entries(REPORT_REASONS).map(([k, v]) => `<label class="check"><input type="radio" name="reason" value="${k}"> ${esc(v)}</label>`).join("");
  const m = modal(`<h2>Пожаловаться</h2><form class="form" id="report-form">${opts}
    <label>Комментарий (необязательно)<textarea name="comment" rows="3" maxlength="1000"></textarea></label>
    <div class="row"><button type="button" class="btn btn-ghost" data-close>Отмена</button><button class="btn btn-accent">Отправить</button></div></form>`);
  $("#report-form", m.el).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    if (!f.get("reason")) return toast("Выбери причину", true);
    try {
      await api("POST", "/api/reports", { target_type: targetType, target_id: targetId, reason: f.get("reason"), comment: f.get("comment") || null });
      m.close();
      toast("Жалоба отправлена. Спасибо, что следишь за порядком 🙏");
    } catch (_) { /* toast уже показан */ }
  };
}

function shareDialog(imgUrl, pageUrl) {
  const abs = new URL(pageUrl, location.origin).href;
  const m = modal(`<h2>Поделиться в сторис</h2>
    <img src="${esc(imgUrl)}" alt="Картинка для сторис" loading="lazy">
    <div class="row">
      <button class="btn btn-ghost" id="copy-link">Скопировать ссылку</button>
      <a class="btn btn-accent" href="${esc(imgUrl)}" download="bulboz-story.png">Скачать картинку</a>
    </div>`);
  $("#copy-link", m.el).onclick = async () => {
    try { await navigator.clipboard.writeText(abs); toast("Ссылка скопирована"); } catch (_) { toast(abs); }
  };
}

// ---------------------------------------------------------------- feed (swipe)
// голосование за вопрос/холивар прямо из ленты (своё — только смотреть)
function cardVoteHtml(q) {
  const own = ME && ME.user.id === q.author_id;
  const t = own ? "Свой вопрос поднимать нельзя" : "";
  return `<span class="card-vote" data-qid="${q.id}" data-my="${q.my_vote ?? 0}">
    <button class="cv-btn ${q.my_vote === 1 ? "on-up" : ""}" data-cvote="1" aria-label="Поднять" title="${t || "Поднять"}"${own ? " disabled" : ""}>▲</button>
    <b class="cv-score" title="Рейтинг: голоса + 2×ответы + 0.5×комментарии">${esc(q.rating)}</b>
    <button class="cv-btn ${q.my_vote === -1 ? "on-down" : ""}" data-cvote="-1" aria-label="Опустить" title="${t || "Опустить"}"${own ? " disabled" : ""}>▼</button></span>`;
}

function feedCard(q) {
  const a = q.top_answer;
  const room = q.room ? `<a class="room-link" href="/r/${encodeURIComponent(q.room.slug)}">#${esc(q.room.title)}</a>` : "";
  let preview = `<div class="answer-preview"><span class="muted">Ответов пока нет — будь первым 👀</span></div>`;
  if (a) {
    const tag = a.is_best ? `<span class="scheme-badge">🔥 Схема</span>` : `<span class="muted">Лучший ответ</span>`;
    const side = a.debate_side && q.debate ? ` <span class="side-badge side-${a.debate_side}">${esc(q.debate[a.debate_side])}</span>` : "";
    preview = `<div class="answer-preview">${tag}${side} <span class="muted">· @${esc(a.author?.username)} · ${signed(a.score)}</span><p>${esc(mdPlain(a.content.body))}</p></div>`;
  }
  const cover = q.cover_url ? `<img class="card-cover" src="${esc(q.cover_url)}" alt="" loading="lazy">` : "";
  return `<article class="card ${q.cover_url ? "has-cover" : ""}" data-href="/q/${q.id}" tabindex="-1">
    <div><span class="kind">${KIND[q.kind] || esc(q.kind)}</span>${room}</div>
    <div class="card-main">
      ${cover}
      <h2>${esc(q.title)}</h2>
      ${q.body ? `<p class="card-desc">${esc(mdPlain(q.body))}</p>` : ""}
      ${preview}
    </div>
    <div class="meta-row">${cardVoteHtml(q)}<span>${answersWord(q.answers_count)}</span><span>@${esc(q.author?.username)}</span><span class="open-hint">Открыть →</span></div>
  </article>`;
}

function initFeed(extraParams = {}) {
  const feed = $("#feed");
  let tab = $("#feed-tabs")?.dataset.preset || "hot", offset = 0, loading = false, done = false;
  $$("#feed-tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === tab));

  async function load(reset = false) {
    if (loading || (done && !reset)) return;
    loading = true;
    if (reset) { offset = 0; done = false; feed.innerHTML = ""; feed.scrollTop = 0; }
    const params = new URLSearchParams({ tab, offset, ...extraParams });
    try {
      const data = await api("GET", `/api/feed?${params}`);
      if (!data.items.length && offset === 0) {
        feed.innerHTML = `<div class="card empty-card"><div><h2>Тут пока пусто</h2><p>Задай первый вопрос — стань легендой.</p><a class="btn btn-accent" href="/ask">+ Спросить</a></div></div>`;
      } else {
        feed.insertAdjacentHTML("beforeend", data.items.map(feedCard).join(""));
      }
      if (data.next_offset == null) done = true; else offset = data.next_offset;
    } finally { loading = false; }
  }

  // открыть вопрос по клику (но не по клику на ссылку внутри карточки)
  feed.addEventListener("click", async (e) => {
    const vb = e.target.closest("[data-cvote]");
    if (vb) {
      e.stopPropagation();
      if (!requireLogin() || vb.disabled) return;
      const box = vb.closest(".card-vote"), qid = box.dataset.qid, v = Number(vb.dataset.cvote), mine = Number(box.dataset.my);
      $$(".cv-btn", box).forEach((b) => (b.disabled = true));
      try {
        const r = mine === v ? await api("DELETE", `/api/questions/${qid}/vote`) : await api("PUT", `/api/questions/${qid}/vote`, { value: v });
        box.dataset.my = r.my_vote ?? 0;
        $(".cv-score", box).textContent = r.rating;
        $("[data-cvote='1']", box).classList.toggle("on-up", r.my_vote === 1);
        $("[data-cvote='-1']", box).classList.toggle("on-down", r.my_vote === -1);
        box.classList.remove("bump"); void box.offsetWidth; box.classList.add("bump");
      } catch (_) {} finally { $$(".cv-btn", box).forEach((b) => (b.disabled = false)); }
      return;
    }
    if (e.target.closest("a, button")) return;
    const card = e.target.closest(".card[data-href]");
    if (card) location.href = card.dataset.href;
  });
  // подгрузка при приближении к концу
  feed.addEventListener("scroll", () => {
    if (feed.scrollTop + feed.clientHeight * 2 >= feed.scrollHeight) load();
  });
  // клавиатура: ↑/↓/j/k — листать, Enter — открыть
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
    const cards = $$(".card", feed);
    if (!cards.length) return;
    // карточки разной высоты: текущая — та, чей верх ближе всего к верху ленты
    let idx = 0, best = Infinity;
    cards.forEach((c, i) => { const dist = Math.abs(c.offsetTop - feed.scrollTop); if (dist < best) { best = dist; idx = i; } });
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); cards[Math.min(idx + 1, cards.length - 1)].scrollIntoView({ behavior: "smooth", block: "start" }); }
    if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); cards[Math.max(idx - 1, 0)].scrollIntoView({ behavior: "smooth", block: "start" }); }
    if (e.key === "Enter" && cards[idx]?.dataset.href) location.href = cards[idx].dataset.href;
  });
  $$("#feed-tabs button").forEach((b) => (b.onclick = () => {
    $$("#feed-tabs button").forEach((x) => x.classList.toggle("active", x === b));
    tab = b.dataset.tab;
    load(true);
  }));
  load(true);
}

// ---------------------------------------------------------------- question page
async function pageQuestion() {
  const root = $("#question");
  const qid = Number(root.dataset.qid);
  let data;

  async function reload() {
    try {
      data = await api("GET", `/api/questions/${qid}`, undefined, { quiet: true });
    } catch (e) {
      root.innerHTML = `<div class="panel"><h1>Вопрос не найден</h1><p class="muted">Возможно, его скрыл модератор или удалил автор.</p><a class="btn" href="/">В ленту</a></div>`;
      return;
    }
    render();
  }

  function voteButtons(a) {
    if (!ME) return `<span class="score">${signed(a.score)}</span>`;
    if (ME.user.id === a.author_id) return `<span class="score" title="Свой ответ оценивать нельзя">${signed(a.score)}</span>`;
    if (data.you_are_author) {
      return `<button class="btn btn-sm vote ${a.my_vote === 5 ? "on-fire" : ""}" data-vote="5" title="Лучший ответ: +5 и статус «Схема»">🔥 +5</button>
              <span class="score">${signed(a.score)}</span>
              <button class="btn btn-sm vote ${a.my_vote === -1 ? "on-down" : ""}" data-vote="-1" title="Мимо: −1">👎 −1</button>`;
    }
    return `<button class="btn btn-sm vote ${a.my_vote === 1 ? "on-up" : ""}" data-vote="1" aria-label="Плюс">▲ +1</button>
            <span class="score">${signed(a.score)}</span>
            <button class="btn btn-sm vote ${a.my_vote === -1 ? "on-down" : ""}" data-vote="-1" aria-label="Минус">▼ −1</button>`;
  }

  function commentsHtml(a) {
    const items = a.comments.map((c) => {
      const mine = ME && ME.user.id === c.author_id;
      return `<li class="comment" data-cid="${c.id}"><div class="md">${c.body_html}</div>
        <div class="c-meta">${userLink(c.author)} · ${esc(fmtDate(c.created_at))}${c.edited_at ? " · изменено" : ""}
          ${mine ? `<button class="link-btn" data-c-edit="${c.id}">изменить</button><button class="link-btn" data-c-del="${c.id}">удалить</button>` : ""}
          ${ME && !mine ? `<button class="link-btn" data-c-report="${c.id}">пожаловаться</button>` : ""}
          ${perm("content.hide") ? `<button class="link-btn" data-c-hide="${c.id}">скрыть</button>` : ""}</div></li>`;
    }).join("");
    const form = ME && !ME.ban ? `<form class="comment-form" data-aid="${a.id}"><textarea name="body" maxlength="200" rows="1" required placeholder="Комментарий (до 200 символов, markdown)"></textarea><span class="c-count">0/200</span><button class="btn btn-sm">➤</button></form>` : "";
    return `<div class="comments">${items ? `<ul>${items}</ul>` : ""}${form}</div>`;
  }

  function qVoteHtml(q) {
    const can = ME && ME.user.id !== q.author_id;
    if (!can) return `<div class="q-vote"><span class="score" title="Рейтинг вопроса">★ ${esc(q.rating)}</span><small>${signed(q.votes_score)} голосов</small></div>`;
    return `<div class="q-vote"><button class="btn btn-sm ${q.my_vote === 1 ? "on-up" : ""}" data-qvote="1" aria-label="Поднять вопрос">▲</button>
      <span class="score" title="Рейтинг вопроса: голоса + 2×ответы + 0.5×комментарии">★ ${esc(q.rating)}</span>
      <button class="btn btn-sm ${q.my_vote === -1 ? "on-down" : ""}" data-qvote="-1" aria-label="Опустить вопрос">▼</button></div>`;
  }

  function answerHtml(a) {
    const q = data.question;
    const side = a.debate_side && q.debate ? `<span class="side-badge side-${a.debate_side}">${esc(q.debate[a.debate_side])}</span>` : "";
    const modBtn = perm("content.hide") ? `<button class="link-btn" data-hide="${a.id}">Скрыть</button>` : "";
    return `<div class="answer ${a.is_best ? "best" : ""}" id="a${a.id}" data-aid="${a.id}">
      <div class="byline">${userLink(a.author)} ${a.is_best ? `<span class="scheme-badge">🔥 Схема</span>` : ""} ${side} <span>· ${esc(fmtDate(a.created_at))}</span></div>
      <div class="text md">${a.body_html}</div>${a.edited_at ? `<div class="edited">изменено ${esc(fmtDate(a.edited_at))}</div>` : ""}
      <div class="actions">${voteButtons(a)}<span class="spacer"></span>
        ${ME && ME.user.id === a.author_id ? `<button class="link-btn" data-edit-a="${a.id}">Изменить</button><button class="link-btn" data-del-a="${a.id}">Удалить</button>` : ""}
        <button class="link-btn" data-share="${a.id}">📤 В сторис</button>
        <button class="link-btn" data-report="${a.id}">Пожаловаться</button>${modBtn}</div>
      ${commentsHtml(a)}
    </div>`;
  }

  function debateHtml() {
    const q = data.question, d = data.debate_votes;
    if (!d) return "";
    const total = d.a + d.b;
    return `<div class="debate-bar">
      <div class="bar"><div class="a" style="width:${d.a_pct}%">${esc(q.debate.a)} · ${d.a_pct}%</div><div class="b" style="width:${d.b_pct}%">${d.b_pct}% · ${esc(q.debate.b)}</div></div>
      <div class="btns"><button class="btn btn-sm ${d.my_side === "a" ? "mine" : ""}" data-side="a">Я за «${esc(q.debate.a)}»</button><button class="btn btn-sm ${d.my_side === "b" ? "mine" : ""}" data-side="b">Я за «${esc(q.debate.b)}»</button></div>
      <p class="muted" style="font-size:13px;margin:6px 0 0">${total} ${plural(total, "голос", "голоса", "голосов")}</p>
    </div>`;
  }

  function formHtml() {
    const q = data.question;
    if (!ME) return `<div class="panel"><a class="btn btn-accent" href="/login?next=${encodeURIComponent(here())}">Войди, чтобы ответить</a></div>`;
    if (ME.ban) return "";
    const sides = q.debate ? `<div class="side-pick">Твоя сторона: <label><input type="radio" name="debate_side" value="a" required> ${esc(q.debate.a)}</label><label><input type="radio" name="debate_side" value="b"> ${esc(q.debate.b)}</label></div>` : "";
    return `<form class="panel answer-form" id="answer-form">
      <h2 style="margin-top:0">Твой ответ</h2>
      <textarea class="input" name="body" maxlength="5000" required placeholder="Пиши по делу — автор может поставить +5, и ответ станет «Схемой»"></textarea>
      <div class="row">${sides}<span class="spacer" style="flex:1"></span><span class="muted" id="ans-count" style="font-size:13px">0/5000</span><button class="btn btn-accent">Ответить</button></div>
    </form>`;
  }

  function render() {
    const q = data.question;
    document.title = `${q.title} — schematoz-bulboz.org`;
    const room = q.room ? ` · <a href="/r/${encodeURIComponent(q.room.slug)}">#${esc(q.room.title)}</a>` : "";
    const hint = data.you_are_author && data.answers.length
      ? `<div class="author-hint">Ты автор вопроса: ставь <b>🔥 +5</b> лучшему ответу (он станет «Схемой») или <b>👎 −1</b>, если ответ мимо. Остальные могут ставить только ±1.</div>` : "";
    const qMod = perm("content.hide") ? `<button class="link-btn" data-hide-q="${q.id}">Скрыть вопрос</button>` : "";
    root.innerHTML = `
      <div class="panel q-head">
        ${q.cover_url ? `<img class="q-cover" src="${esc(q.cover_url)}" alt="">` : ""}
        <div class="q-top"><span class="kind">${KIND[q.kind] || esc(q.kind)}</span>${qVoteHtml(q)}</div>
        <h1>${esc(q.title)}</h1>
        ${q.body ? `<div class="body md">${q.body_html}</div>` : ""}${q.edited_at ? `<div class="edited">изменено ${esc(fmtDate(q.edited_at))}</div>` : ""}
        <div class="byline">${userLink(q.author)} <span>· ${esc(fmtDate(q.created_at))}</span>${room}<span class="spacer" style="flex:1"></span>
          ${data.you_are_author ? `<button class="link-btn" data-edit-q>Изменить</button><button class="link-btn" data-del-q>Удалить</button>` : ""}
          <button class="link-btn" data-report-q="${q.id}">Пожаловаться</button>${qMod}</div>
        ${debateHtml()}
      </div>
      <h2 class="answers-title">${answersWord(data.answers.length)}</h2>
      ${hint}
      ${data.answers.map(answerHtml).join("") || `<p class="muted">Пока никто не ответил. Твой ответ может стать первым!</p>`}
      ${formHtml()}`;
    bind();
    if (location.hash && $(location.hash)) $(location.hash).scrollIntoView();
  }

  function bind() {
    $$("[data-vote]", root).forEach((btn) => (btn.onclick = async () => {
      const aid = Number(btn.closest(".answer").dataset.aid);
      const value = Number(btn.dataset.vote);
      const a = data.answers.find((x) => x.id === aid);
      try {
        if (a.my_vote === value) {
          await api("DELETE", `/api/answers/${aid}/vote`);
        } else {
          await api("PUT", `/api/answers/${aid}/vote`, { value });
          if (value === 5) toast("🔥 Ответ стал «Схемой»! Автор получил +5");
        }
        await reload();
      } catch (_) { /* toast уже показан */ }
    }));
    $$("[data-side]", root).forEach((btn) => (btn.onclick = async () => {
      if (!requireLogin()) return;
      try { await api("PUT", `/api/questions/${qid}/debate-vote`, { side: btn.dataset.side }); await reload(); } catch (_) {}
    }));
    $$("[data-qvote]", root).forEach((b) => (b.onclick = async () => {
      if (!requireLogin()) return;
      const v = Number(b.dataset.qvote);
      try {
        if (data.question.my_vote === v) await api("DELETE", `/api/questions/${qid}/vote`);
        else await api("PUT", `/api/questions/${qid}/vote`, { value: v });
        await reload();
      } catch (_) {}
    }));
    $$(".comment-form", root).forEach((f) => {
      const ta = f.elements.body;
      mdToolbar(ta);
      ta.oninput = () => { $(".c-count", f).textContent = `${ta.value.length}/200`; ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };
      ta.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); f.requestSubmit ? f.requestSubmit() : f.dispatchEvent(new Event("submit", { cancelable: true })); } };
      f.onsubmit = async (e) => {
        e.preventDefault();
        if (!ta.value.trim()) return;
        try { await api("POST", `/api/answers/${f.dataset.aid}/comments`, { body: ta.value }); await reload(); } catch (_) {}
      };
    });
    const findComment = (cid) => data.answers.flatMap((a) => a.comments).find((c) => c.id === cid);
    $$("[data-c-edit]", root).forEach((b) => (b.onclick = () => {
      const c = findComment(Number(b.dataset.cEdit));
      const m = modal(`<h2>Изменить комментарий</h2><form class="form edit-box" id="edit-form"><textarea class="input" name="body" rows="3" maxlength="200" required>${esc(c.body)}</textarea>
        <div class="row"><button type="button" class="btn btn-ghost" data-close>Отмена</button><button class="btn btn-accent">Сохранить</button></div></form>`);
      mdToolbar($("textarea", m.el));
      $("#edit-form", m.el).onsubmit = async (e) => {
        e.preventDefault();
        try { await api("PATCH", `/api/comments/${c.id}`, { body: e.target.elements.body.value }); m.close(); await reload(); } catch (_) {}
      };
    }));
    $$("[data-c-del]", root).forEach((b) => (b.onclick = async () => {
      if (!confirm("Удалить комментарий?")) return;
      try { await api("DELETE", `/api/comments/${b.dataset.cDel}`); await reload(); } catch (_) {}
    }));
    $$("[data-c-report]", root).forEach((b) => (b.onclick = () => reportDialog("comment", Number(b.dataset.cReport))));
    $$("[data-c-hide]", root).forEach((b) => (b.onclick = async () => {
      if (!confirm("Скрыть комментарий?")) return;
      try { await api("POST", `/mod/content/comment/${b.dataset.cHide}/hide`, {}); toast("Комментарий скрыт"); await reload(); } catch (_) {}
    }));
    $$("[data-edit-a]", root).forEach((b) => (b.onclick = () => {
      const aid = Number(b.dataset.editA), a = data.answers.find((x) => x.id === aid);
      const m = modal(`<h2>Изменить ответ</h2><form class="form edit-box" id="edit-form"><textarea class="input" name="body" rows="6" maxlength="5000" required>${esc(a.content.body)}</textarea>
        <div class="row"><button type="button" class="btn btn-ghost" data-close>Отмена</button><button class="btn btn-accent">Сохранить</button></div></form>`);
      mdToolbar($("textarea", m.el));
      $("#edit-form", m.el).onsubmit = async (e) => {
        e.preventDefault();
        try { await api("PATCH", `/api/answers/${aid}`, { body: e.target.elements.body.value }); m.close(); toast("Сохранено"); await reload(); } catch (_) {}
      };
    }));
    $$("[data-del-a]", root).forEach((b) => (b.onclick = async () => {
      if (!confirm("Удалить ответ? Репутация, полученная за него, останется.")) return;
      try { await api("DELETE", `/api/answers/${b.dataset.delA}`); toast("Ответ удалён"); await reload(); } catch (_) {}
    }));
    $$("[data-edit-q]", root).forEach((b) => (b.onclick = () => {
      const q = data.question, locked = data.answers.length > 0;
      const m = modal(`<h2>Изменить вопрос</h2><form class="form edit-box" id="edit-form">
        <label>Заголовок<input class="input" name="title" maxlength="200" minlength="5" value="${esc(q.title)}" ${locked ? "disabled" : ""}></label>
        ${locked ? `<p class="muted" style="font-size:13px">На вопрос уже ответили — заголовок менять нельзя, но можно дополнить подробности.</p>` : ""}
        <label>Подробности<textarea class="input" name="body" rows="5" maxlength="5000">${esc(q.body || "")}</textarea></label>
        <div class="row"><button type="button" class="btn btn-ghost" data-close>Отмена</button><button class="btn btn-accent">Сохранить</button></div></form>`);
      mdToolbar($("textarea[name=body]", m.el));
      $("#edit-form", m.el).onsubmit = async (e) => {
        e.preventDefault();
        const el = e.target.elements, body = { body: el.body.value };
        if (!locked) body.title = el.title.value;
        try { await api("PATCH", `/api/questions/${qid}`, body); m.close(); toast("Сохранено"); await reload(); } catch (_) {}
      };
    }));
    $$("[data-del-q]", root).forEach((b) => (b.onclick = async () => {
      if (!confirm("Удалить вопрос вместе с ответами?")) return;
      try { await api("DELETE", `/api/questions/${qid}`); toast("Вопрос удалён"); location.href = "/"; } catch (_) {}
    }));
    $$("[data-report]", root).forEach((b) => (b.onclick = () => reportDialog("answer", Number(b.dataset.report))));
    $$("[data-report-q]", root).forEach((b) => (b.onclick = () => reportDialog("question", Number(b.dataset.reportQ))));
    $$("[data-share]", root).forEach((b) => (b.onclick = () => shareDialog(`/api/share/answer/${b.dataset.share}.png`, `/q/${qid}#a${b.dataset.share}`)));
    $$("[data-hide]", root).forEach((b) => (b.onclick = async () => {
      if (!confirm("Скрыть этот ответ?")) return;
      try { await api("POST", `/mod/content/answer/${b.dataset.hide}/hide`, {}); toast("Ответ скрыт"); await reload(); } catch (_) {}
    }));
    $$("[data-hide-q]", root).forEach((b) => (b.onclick = async () => {
      if (!confirm("Скрыть весь вопрос?")) return;
      try { await api("POST", `/mod/content/question/${b.dataset.hideQ}/hide`, {}); toast("Вопрос скрыт"); await reload(); } catch (_) {}
    }));
    const form = $("#answer-form", root);
    if (form) {
      const ta = $("textarea", form);
      mdToolbar(ta);
      ta.oninput = () => ($("#ans-count").textContent = `${ta.value.length}/5000`);
      form.onsubmit = async (e) => {
        e.preventDefault();
        const f = new FormData(form);
        const body = { body: f.get("body"), content_type: "text" };
        if (f.get("debate_side")) body.debate_side = f.get("debate_side");
        const btn = $("button", form); btn.disabled = true;
        try {
          const r = await api("POST", `/api/questions/${qid}/answers`, body);
          toast("Ответ опубликован!");
          newBadgesToast(r.new_badges);
          await reload();
          $(`#a${r.answer.id}`)?.scrollIntoView({ behavior: "smooth" });
        } catch (_) { btn.disabled = false; }
      };
    }
  }

  await reload();
}

// ---------------------------------------------------------------- ask
async function pageAsk() {
  const form = $("#ask-form");
  const kind = form.elements.kind, title = form.elements.title, roomSel = form.elements.room_id;
  const params = new URLSearchParams(location.search);
  kind.onchange = () => ($(".debate-fields", form).hidden = kind.value !== "debate");
  if (perm("debate.create")) { const o = $("#debate-opt"); o.hidden = false; o.disabled = false; }
  mdToolbar(form.elements.body);
  let coverUrl = null;
  const coverIn = $("#cover-input"), prev = $("#cover-preview");
  coverIn.onchange = async () => {
    const file = coverIn.files[0]; coverIn.value = "";
    if (!file) return;
    try {
      const r = await uploadImage(file);
      coverUrl = r.url; $("img", prev).src = r.url; prev.hidden = false; $("#cover-pick").hidden = true;
    } catch (_) {}
  };
  $("#cover-remove").onclick = () => { coverUrl = null; prev.hidden = true; $("#cover-pick").hidden = false; };
  title.oninput = () => ($('.counter[data-for="title"]').textContent = `${title.value.length}/300`);
  const { items } = await api("GET", "/api/rooms");
  roomSel.insertAdjacentHTML("beforeend", items.map((r) => `<option value="${r.id}">${esc(r.title)}</option>`).join(""));
  if (params.get("room")) { const r = items.find((x) => x.slug === params.get("room")); if (r) roomSel.value = r.id; }
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const body = { kind: f.get("kind"), title: f.get("title"), body: f.get("body") || null, room_id: f.get("room_id") ? Number(f.get("room_id")) : null, cover_url: coverUrl };
    if (body.kind === "debate") { body.side_a = f.get("side_a") || null; body.side_b = f.get("side_b") || null; }
    try {
      const r = await api("POST", "/api/questions", body);
      location.href = `/q/${r.question.id}`;
    } catch (_) {}
  };
}

// ---------------------------------------------------------------- rooms
function joinButton(r) {
  if (r.joined == null) return `<a class="btn btn-sm btn-ghost" href="/login?next=${encodeURIComponent(here())}">Вступить</a>`;
  return `<button class="btn btn-sm ${r.joined ? "btn-ghost" : "btn-accent"}" data-join="${esc(r.slug)}" data-joined="${r.joined ? 1 : 0}">${r.joined ? "Ты в комнате ✓" : "Вступить"}</button>`;
}

function bindJoin(root, after) {
  $$("[data-join]", root).forEach((b) => (b.onclick = async () => {
    const joined = b.dataset.joined === "1";
    try {
      await api(joined ? "DELETE" : "POST", `/api/rooms/${encodeURIComponent(b.dataset.join)}/join`);
      after();
    } catch (_) {}
  }));
}

async function pageRooms() {
  const root = $("#rooms");
  async function render() {
    const { items } = await api("GET", "/api/rooms");
    const groups = {};
    items.forEach((r) => { const k = r.category?.title || "Разное"; (groups[k] ||= []).push(r); });
    root.innerHTML = Object.entries(groups).map(([title, rooms]) => `<div class="room-group"><h2>${esc(title)}</h2>
      ${rooms.map((r) => `<div class="room-row"><div><a class="title" href="/r/${encodeURIComponent(r.slug)}">#${esc(r.title)}</a><div class="count">${r.member_count} ${plural(r.member_count, "участник", "участника", "участников")}</div></div>${joinButton(r)}</div>`).join("")}
    </div>`).join("");
    bindJoin(root, render);
  }
  await render();
}

async function pageRoom() {
  const head = $("#room-head");
  const slug = head.dataset.slug;
  async function renderHead() {
    try {
      const { room } = await api("GET", `/api/rooms/${encodeURIComponent(slug)}`, undefined, { quiet: true });
      document.title = `#${room.title} — schematoz-bulboz.org`;
      head.innerHTML = `<h1>#${esc(room.title)}</h1><span class="muted">${room.member_count} уч.</span>${joinButton(room)}<a class="btn btn-sm btn-accent" href="/ask?room=${encodeURIComponent(slug)}">+ Спросить</a>`;
      bindJoin(head, renderHead);
    } catch (_) {
      head.innerHTML = `<h1>Комната не найдена</h1>`;
    }
  }
  await renderHead();
  initFeed({ room: slug });
}

// ---------------------------------------------------------------- profile
function avatarHTML(u, size = "") {
  const inner = u.avatar_url ? `<img src="${esc(u.avatar_url)}" alt="">` : initial(u.username);
  const frame = u.avatar_frame && u.avatar_frame !== "none" ? ` frame-${esc(u.avatar_frame)}` : "";
  return `<span class="avatar ${size}${frame}">${inner}</span>`;
}

// классы/переменные темы профиля — только из белых списков (сервер валидирует тоже)
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
  const ST = { expert: "⚡ Эксперт", connoisseur: "Знаток", newbie: "Новичок" };
  const statsParts = [];
  if (u.streak_days != null && !hidden.has("streak")) statsParts.push(`<div class="stat"><b>🔥 ${u.streak_days}</b><span>дней стрик</span></div>`);
  statsParts.push(`<div class="stat" title="${u.rating_tier ? "У админов и модераторов рейтинг бесконечный" : "Бульбоз-индекс: активность, ответы, их оценки, «Схемы», вопросы и комментарии"}"><b>★ ${esc(u.rating_display)}</b><span>рейтинг${u.rating_tier === 2 ? " · админ" : u.rating_tier === 1 ? " · модер" : ""}</span></div>`);
  statsParts.push(`<div class="stat"><b>${u.reputation}</b><span>репутация</span></div>`);
  if (st.schemes != null) statsParts.push(`<div class="stat"><b>${st.schemes}</b><span>схем</span></div>`);
  if (st.answers != null) statsParts.push(`<div class="stat"><b>${st.answers}</b><span>ответов</span></div>`);
  const showcase = (d.badges || []).filter((b) => b.showcase);
  const meta = [c.pronouns && esc(c.pronouns), c.city && `📍 ${esc(c.city)}`, u.created_at && `с нами с ${new Date(u.created_at).toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}`].filter(Boolean);
  return `<div class="profile-skin ${profileSkin(c).cls}" style="${profileSkin(c).style}">
    <div class="panel profile-card">
      ${c.banner_url ? `<div class="profile-banner" style="background-image:url('${esc(c.banner_url)}')"></div>` : `<div class="profile-banner empty"></div>`}
      <div class="profile-head">${avatarHTML(u, "lg")}
        <div class="ph-main"><h1>${esc(u.display_name || u.username)} ${c.status_emoji ? `<span class="status-emoji">${esc(c.status_emoji)}</span>` : ""}</h1>
          <div class="muted">@${esc(u.username)}${meta.length ? " · " + meta.join(" · ") : ""}</div>
          <div class="level">Уровень ${u.level} · ${esc(u.level_name)}</div>
          ${c.status_text ? `<div class="status-line">${esc(c.status_text)}</div>` : ""}
          ${showcase.length ? `<div class="showcase">${showcase.map((b) => `<span class="sc-badge" title="${esc(b.title)}: ${esc(b.description)}">${esc(b.emoji)} ${esc(b.title)}</span>`).join("")}</div>` : ""}
        </div></div>
      ${u.bio ? `<p class="bio">${esc(u.bio)}</p>` : ""}
      ${c.interests.length ? `<div class="interests">${c.interests.map((t) => `<a class="chip" href="/search?q=${encodeURIComponent(t)}">#${esc(t)}</a>`).join("")}</div>` : ""}
      ${c.links.length ? `<div class="plinks">${c.links.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="nofollow noopener ugc">🔗 ${esc(l.title)}</a>`).join("")}</div>` : ""}
      <div class="stats">${statsParts.join("")}</div>
      ${u.streak_freeze_available && !hidden.has("streak") ? `<div class="freeze">❄️ Заморозка стрика доступна: если пропустишь один день на этой неделе, 🔥 не сгорит</div>` : ""}
      <div class="follow-row">${st.followers != null ? `<span><b id="followers-n">${st.followers}</b> подписчиков</span><span><b>${st.following}</b> подписок</span>${tag("follows")}` : ""}
        ${preview ? "" : d.i_follow == null ? "" : `<button class="btn btn-sm ${d.i_follow ? "btn-ghost" : "btn-accent"}" id="follow-btn">${d.i_follow ? "Отписаться" : "Подписаться"}</button>`}
        ${!preview && !ME && d.i_follow == null ? `<a class="btn btn-sm btn-accent" href="/login?next=${encodeURIComponent(here())}">Подписаться</a>` : ""}</div>
      ${preview ? "" : `<button class="btn btn-sm btn-ghost" id="share-profile">📤 Поделиться в сторис</button>${d.is_owner ? ` <a class="btn btn-sm btn-accent" href="/settings">🎨 Настроить профиль</a>` : ""}`}
    </div>
    ${d.about_html ? `<div class="panel"><h2 style="margin-top:0">О себе</h2><div class="md">${d.about_html}</div></div>` : ""}
    ${d.pinned_answer ? `<a class="panel pinned" href="/q/${d.pinned_answer.question_id}#a${d.pinned_answer.answer_id}"><div class="kind">📌 Закреплённый ответ${d.pinned_answer.is_best ? " · 🔥 Схема" : ""}</div><b>${esc(d.pinned_answer.question_title)}</b><div class="md">${d.pinned_answer.body_html}</div></a>` : ""}
    ${hidden.has("topics") ? "" : `<div class="panel"><h2 style="margin-top:0">За что репутация${tag("topics")}</h2>
      ${d.topics.length ? d.topics.map((t) => `<div class="topic"><span class="st ${t.status}">${ST[t.status]}</span>
        <div>${t.room_slug ? `<a href="/r/${encodeURIComponent(t.room_slug)}">#${esc(t.title)}</a>` : esc(t.title)}</div>
        <div class="nums"><b>${t.schemes}</b> ${plural(t.schemes, "схема", "схемы", "схем")} · ${t.points} очк.<br>${t.plus} 👍 / ${t.minus} 👎</div></div>`).join("")
        : `<p class="muted">Пока нет оценённых ответов.</p>`}
      <p class="muted" style="font-size:13px">«Схема» — ответ, которому автор вопроса поставил +5. Эксперт в теме: 15+ схем и меньше 15% минусов.</p></div>`}
    ${hidden.has("badges") ? "" : `<div class="panel"><h2 style="margin-top:0">Бейджи${tag("badges")}</h2>
      ${d.badges.length ? `<div class="badges">${d.badges.map((b) => `<div class="badge${b.showcase ? " on-show" : ""}"><div class="e">${esc(b.emoji)}</div><b>${esc(b.title)}</b><span>${esc(b.description)}</span></div>`).join("")}</div>` : `<p class="muted">Пока нет. Ответь на пару вопросов 😉</p>`}</div>`}
    ${hidden.has("best_answers") ? "" : `<div class="panel"><h2 style="margin-top:0">Лучшие ответы${tag("best_answers")}</h2>
      ${d.best_answers.length ? d.best_answers.map((b) => `<a class="best-item" href="/q/${b.question_id}#a${b.answer_id}"><b>${esc(b.question_title)}</b><small>${esc(b.body)}</small></a>`).join("") : `<p class="muted">Схем пока нет.</p>`}</div>`}
  </div>`;
}

async function pageProfile() {
  const root = $("#profile");
  const username = root.dataset.username;
  let d;
  try { d = await api("GET", `/api/users/${encodeURIComponent(username)}`, undefined, { quiet: true }); }
  catch (_) { root.innerHTML = `<div class="panel"><h1>Пользователь не найден</h1></div>`; return; }
  const u = d.user;
  document.title = `${u.display_name || "@" + u.username} — schematoz-bulboz.org`;
  root.innerHTML = profileHTML(d) + `<div id="profile-extras"></div>`;
  profileExtras(d);
  let following = d.i_follow;
  const fb = $("#follow-btn");
  if (fb) fb.onclick = async () => {
    try {
      const r = await api(following ? "DELETE" : "PUT", `/api/users/${encodeURIComponent(u.username)}/follow`);
      following = r.following;
      const n = $("#followers-n"); if (n) n.textContent = r.followers;
      fb.textContent = following ? "Отписаться" : "Подписаться";
      fb.className = `btn btn-sm ${following ? "btn-ghost" : "btn-accent"}`;
    } catch (_) {}
  };
  $("#share-profile").onclick = () => shareDialog(`/api/share/user/${encodeURIComponent(u.username)}.png`, `/u/${encodeURIComponent(u.username)}`);
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
  const lvl = d.user.level, unlimited = d.user.rating_tier > 0;
  const SECTIONS_UI = [["basic", "👤", "Основное"], ["media", "🖼", "Аватар"], ["look", "🎨", "Оформление"], ["links", "🏷", "Интересы"], ["show", "🏆", "Витрина"], ["privacy", "🙈", "Приватность"]];
  $("#st-nav").innerHTML = SECTIONS_UI.map(([id, e, t]) => `<a href="#st-${id}">${e} ${t}</a>`).join("");
  form.innerHTML = `
    <section class="st-card" id="st-basic"><h2>👤 Основное</h2>
      <div class="st-grid">
        ${field("Отображаемое имя", text("display_name", s.display_name, L.display_name))}
        ${field("Местоимения", text("pronouns", s.pronouns, L.pronouns, "он/его"))}
        ${field("Статус-эмодзи", text("status_emoji", s.status_emoji, 8, "😎"), "Только эмодзи")}
        ${field("Город", text("city", s.city, L.city, "Казань"))}
      </div>
      ${field("Статус", text("status_text", s.status_text, L.status_text, "готовлюсь к ЕГЭ 📚"))}
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
          <span class="st-opt-body"><span class="st-emoji">${esc(b.emoji)}</span><span>${esc(b.title)}</span></span></label>`).join("") : `<span class="muted">Бейджей пока нет: ответь на пару вопросов</span>`}</div>
        <small class="st-hint">До ${L.showcase_badges} штук</small></div>
      ${field("Закреплённый ответ", `<select class="input" name="pinned_answer_id"><option value="">— не закреплять —</option>${d.answers.map((a) => `<option value="${a.id}"${a.id === s.pinned_answer_id ? " selected" : ""}>${esc(a.question_title.slice(0, 80))}</option>`).join("")}</select>`, d.answers.length ? "" : "Появится, когда ответишь на вопрос")}
    </section>

    <section class="st-card" id="st-privacy"><h2>🙈 Приватность</h2>
      <p class="muted st-lead">Отмеченные разделы видишь только ты. Сервер не отдаёт их даже через API.</p>
      <label class="st-check st-toggle"><input type="checkbox" name="wall_closed"${s.wall_closed ? " checked" : ""}> 🔒 Закрыть стену: писать могу только я</label>
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
      showcase_badges: all("showcase"), hidden_sections: all("hidden"), wall_closed: f.wall_closed.checked,
      pinned_answer_id: f.pinned_answer_id.value ? Number(f.pinned_answer_id.value) : null,
      avatar_url: avatar || null, banner_url: banner || null,
    };
  };
  const preview = () => {
    const v = collect();
    const user = { ...base.user, display_name: v.display_name, bio: v.bio, avatar_url: v.avatar_url, avatar_frame: v.avatar_frame };
    const custom = { ...base.custom, ...v, links: v.links.map((l) => ({ ...l, title: l.title || l.url })), interests: v.interests.slice(0, L.interests) };
    const badges = base.badges.map((b) => ({ ...b, showcase: v.showcase_badges.includes(b.code) }))
      .sort((a, b) => (v.showcase_badges.indexOf(a.code) + 1 || 99) - (v.showcase_badges.indexOf(b.code) + 1 || 99));
    const pin = v.pinned_answer_id ? (base.pinned_answer?.answer_id === v.pinned_answer_id ? base.pinned_answer
      : { answer_id: v.pinned_answer_id, question_id: 0, question_title: d.answers.find((a) => a.id === v.pinned_answer_id)?.question_title || "", body_html: "<p class='muted'>текст появится после сохранения</p>" }) : null;
    $("#preview").innerHTML = profileHTML({ ...base, user, custom, badges, pinned_answer: pin,
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
  loginKeysPanel($("#login-keys"));
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
  const STATUS = { none: "", pending: "⏳ Апелляция на рассмотрении — её разбирает другой модератор, не тот, кто выдал бан.", accepted: "✅ Апелляция принята.", rejected: "❌ Апелляция отклонена." };
  root.innerHTML = `<h1>Аккаунт заблокирован</h1>
    <p><b>Причина:</b> ${esc(ban.reason)}</p>
    <p><b>Срок:</b> ${ban.ends_at ? "до " + esc(fmtDate(ban.ends_at)) : "навсегда"}</p>
    <p class="muted">Подробнее — в <a href="/rules">правилах сообщества</a>.</p>
    ${ban.appeal_status !== "none" ? `<p>${STATUS[ban.appeal_status]}</p>${ban.appeal_comment ? `<p class="muted">Комментарий модератора: ${esc(ban.appeal_comment)}</p>` : ""}` : `
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
  show($("#panel-tabs button.active").dataset.tab);
  return show;
}

function denied(perm_) {
  if (!ME) { location.href = `/login?next=${encodeURIComponent(here())}`; return true; }
  if (!perm(perm_)) { $("main").innerHTML = `<div class="panel"><h1>Нет доступа</h1><p class="muted">Этот раздел только для команды модерации.</p></div>`; return true; }
  return false;
}

function modlogTable(items) {
  if (!items.length) return `<p class="muted">Записей нет.</p>`;
  return `<table class="list"><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Цель</th><th>Детали</th></tr>
    ${items.map((a) => `<tr><td>${esc(fmtDate(a.created_at))}</td><td>#${a.actor_id}</td><td><code>${esc(a.action)}</code></td><td>${esc(a.target_type)} ${a.target_id ?? ""}</td><td><small class="muted">${esc(JSON.stringify(a.payload || {}))}</small></td></tr>`).join("")}</table>`;
}

async function banDialog(userId, username, reportId) {
  const canPerm = perm("ban.permanent");
  const m = modal(`<h2>Бан @${esc(username)}</h2><form class="form" id="ban-form">
    <label>Срок<select name="days"><option value="1">1 день</option><option value="7" selected>7 дней</option><option value="30">30 дней</option>${canPerm ? `<option value="perm">Навсегда</option>` : ""}</select></label>
    <label>Причина (увидит пользователь)<input name="reason" required placeholder="Спам (п. 2 Правил)"></label>
    <div class="row"><button type="button" class="btn btn-ghost" data-close>Отмена</button><button class="btn btn-danger">Забанить</button></div></form>`);
  return new Promise((resolve) => {
    $("#ban-form", m.el).onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const days = f.get("days") === "perm" ? null : Number(f.get("days"));
      try {
        await api("POST", "/mod/bans", { user_id: userId, reason: f.get("reason"), days, report_id: reportId || null });
        m.close(); toast("Бан выдан"); resolve(true);
      } catch (_) {}
    };
  });
}

async function pageMod() {
  if (denied("report.review")) return;
  const show = initPanel({
    async reports(panel) {
      const { items } = await api("GET", "/mod/reports");
      if (!items.length) { panel.innerHTML = `<p class="muted">Очередь пуста. Можно выдохнуть ☕</p>`; return; }
      panel.innerHTML = items.map((r) => {
        const t = r.target;
        const link = t?.question_id ? `<a href="/q/${t.question_id}" target="_blank">открыть</a>` : "";
        return `<div class="item" data-rid="${r.id}">
          <div class="head"><span class="pill ${r.priority >= 90 ? "p0" : ""}">${esc(REPORT_REASONS[r.reason] || r.reason)}</span>
            <span>${esc(r.target_type)} #${r.target_id}</span><span class="muted">· жалоб: ${r.same_target_count} · ${esc(fmtDate(r.created_at))}</span> ${link}</div>
          ${t ? `<div class="quote">${esc(t.text)}</div><div class="muted" style="font-size:13px">Автор: @${esc(t.author)}${t.status ? ` · статус: ${esc(t.status)}` : ""}</div>` : `<p class="muted">Объект удалён</p>`}
          ${r.comment ? `<p style="font-size:14px">💬 ${esc(r.comment)}</p>` : ""}
          <div class="btns" style="margin-top:10px">
            ${r.target_type !== "user" ? `<button class="btn btn-sm btn-danger" data-act="hide">Скрыть контент</button>` : ""}
            <button class="btn btn-sm btn-ghost" data-act="reject">Нарушений нет</button>
            ${t ? `<button class="btn btn-sm btn-ghost" data-act="ban" data-uid="${t.author_id}" data-uname="${esc(t.author)}">Бан автора…</button>` : ""}
          </div></div>`;
      }).join("");
      $$("[data-act]", panel).forEach((b) => (b.onclick = async () => {
        const rid = Number(b.closest(".item").dataset.rid);
        try {
          if (b.dataset.act === "ban") { await banDialog(Number(b.dataset.uid), b.dataset.uname, rid); return; }
          const r = await api("POST", `/mod/reports/${rid}/resolve`, { decision: b.dataset.act });
          toast(`Готово, закрыто жалоб: ${r.closed}`);
          show("reports");
        } catch (_) {}
      }));
    },
    async appeals(panel) {
      const { items } = await api("GET", "/mod/appeals");
      if (!items.length) { panel.innerHTML = `<p class="muted">Апелляций нет. Свои баны ты здесь не видишь — их разбирают коллеги.</p>`; return; }
      panel.innerHTML = items.map((a) => `<div class="item" data-bid="${a.ban_id}">
        <div class="head"><b>@${esc(a.username)}</b><span class="muted">бан ${a.ends_at ? "до " + esc(fmtDate(a.ends_at)) : "навсегда"} · выдал #${a.issued_by}</span></div>
        <p style="font-size:14px"><b>Причина бана:</b> ${esc(a.reason)}</p>
        <div class="quote">${esc(a.text)}</div>
        <input class="input" placeholder="Комментарий для пользователя" data-comment>
        <div class="btns" style="margin-top:10px"><button class="btn btn-sm btn-good" data-dec="accept">Принять (снять бан)</button><button class="btn btn-sm btn-danger" data-dec="reject">Отклонить</button></div>
      </div>`).join("");
      $$("[data-dec]", panel).forEach((b) => (b.onclick = async () => {
        const item = b.closest(".item");
        try {
          await api("POST", `/mod/appeals/${item.dataset.bid}/decide`, { decision: b.dataset.dec, comment: $("[data-comment]", item).value });
          toast("Решение сохранено"); show("appeals");
        } catch (_) {}
      }));
    },
    async log(panel) {
      const { items } = await api("GET", "/mod/log");
      panel.innerHTML = modlogTable(items);
    },
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

async function pageAdmin() {
  if (denied("analytics.read")) return;
  initPanel({
    async kombucha(panel) { await kbDebugPanel(panel); },
    async analytics(panel) {
      const a = await api("GET", "/admin/analytics");
      const L = { users_total: "Всего юзеров", users_24h: "Новых за 24 ч", dau: "DAU", questions_24h: "Вопросов за 24 ч", answers_24h: "Ответов за 24 ч", reports_open: "Открытых жалоб" };
      panel.innerHTML = `<div class="kv">${Object.entries(L).map(([k, v]) => `<div class="stat"><b>${a[k]}</b><span>${v}</span></div>`).join("")}</div>`;
    },
    async users(panel) {
      panel.innerHTML = `<input class="input" id="user-q" placeholder="Поиск по нику или email"><div id="user-list" style="margin-top:12px"></div>`;
      const ROLES = ["user", "moderator", "admin"];
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
    async features(panel) {
      const { value } = await api("GET", "/admin/settings/features");
      const L = { ANSWER_TEXT_ENABLED: "Текстовые ответы", ANSWER_VOICE_ENABLED: "Голосовые ответы (заготовка — ещё не реализованы!)", ANSWER_VIDEO_ENABLED: "Видео-ответы (заготовка — ещё не реализованы!)" };
      panel.innerHTML = Object.entries(value).map(([k, on]) => `<label class="toggle"><input type="checkbox" data-flag="${esc(k)}" ${on ? "checked" : ""}> <span>${esc(L[k] || k)}<br><code>${esc(k)}</code></span></label>`).join("");
      $$("[data-flag]", panel).forEach((i) => (i.onchange = async () => {
        const val = {}; $$("[data-flag]", panel).forEach((x) => (val[x.dataset.flag] = x.checked));
        try { await api("PUT", "/admin/settings/features", { value: val }); toast("Флаги обновлены"); } catch (_) { i.checked = !i.checked; }
      }));
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
    async rooms(panel) {
      const [{ items: cats }, { items: rooms }] = await Promise.all([api("GET", "/api/categories"), api("GET", "/api/rooms")]);
      panel.innerHTML = `<form class="panel form" id="room-form"><h3 style="margin-top:0">Новая комната</h3>
          <label>Slug (латиница)<input name="slug" required pattern="[a-z0-9-]{2,64}"></label>
          <label>Название<input name="title" required></label>
          <label>Категория<select name="category_id">${cats.map((c) => `<option value="${c.id}">${esc(c.title)}</option>`).join("")}</select></label>
          <button class="btn btn-accent">Создать</button></form>
        <form class="panel form" id="cat-form"><h3 style="margin-top:0">Новая категория</h3>
          <label>Slug<input name="slug" required pattern="[a-z0-9-]{2,64}"></label><label>Название<input name="title" required></label>
          <button class="btn">Создать</button></form>
        <table class="list">${rooms.map((r) => `<tr><td><a href="/r/${encodeURIComponent(r.slug)}">#${esc(r.title)}</a></td><td>${esc(r.category?.title || "")}</td><td>${r.member_count} уч.</td></tr>`).join("")}</table>`;
      $("#room-form").onsubmit = async (e) => {
        e.preventDefault(); const f = new FormData(e.target);
        try { await api("POST", "/admin/rooms", { slug: f.get("slug"), title: f.get("title"), category_id: Number(f.get("category_id")) }); toast("Комната создана"); this.rooms(panel); } catch (_) {}
      };
      $("#cat-form").onsubmit = async (e) => {
        e.preventDefault(); const f = new FormData(e.target);
        try { await api("POST", "/admin/categories", { slug: f.get("slug"), title: f.get("title") }); toast("Категория создана"); this.rooms(panel); } catch (_) {}
      };
    },
    async modlog(panel) {
      const { items } = await api("GET", "/admin/modlog");
      panel.innerHTML = modlogTable(items);
    },
  });
}

// ---------------------------------------------------------------- notifications
const NOTIF = {
  answer: (p) => ["💬", `@${esc(p.username)} ответил(а) на твой вопрос «${esc(p.question_title)}»`, `/q/${p.question_id}#a${p.answer_id}`],
  scheme: (p) => ["🔥", `Твой ответ стал «Схемой» в вопросе «${esc(p.question_title)}» (+5)`, `/q/${p.question_id}#a${p.answer_id}`],
  badge: (p) => [esc(p.emoji || "🏅"), `Новый бейдж: ${esc(p.title)}`, ME ? `/u/${encodeURIComponent(ME.user.username)}` : "#"],
  comment: (p) => ["💭", `@${esc(p.username)} прокомментировал(а) твой ответ в «${esc(p.question_title)}»`, `/q/${p.question_id}#a${p.answer_id}`],
  follow: (p) => ["👋", `@${esc(p.username)} подписался(ась) на тебя`, `/u/${encodeURIComponent(p.username)}`],
  ban: (p) => ["⛔", `Аккаунт заблокирован. Причина: ${esc(p.reason || "—")}`, "/banned"],
  trade: (p) => [p.accepted ? "🤝" : p.gift ? "🎁" : "🔄", p.accepted ? `@${esc(p.username)} принял(а) твоё предложение обмена` : p.gift ? `@${esc(p.username)} дарит тебе чайный гриб` : `@${esc(p.username)} предлагает обмен грибами`, "/market#trades"],
  sale: (p) => ["💰", `@${esc(p.username)} купил(а) твой гриб «${esc(p.kombucha_name)}» — +${p.amount} $₽`, "/wallet"],
  task: (p) => ({ new_submission: ["📋", `@${esc(p.username)} откликнулся на задание «${esc(p.title)}»`],
    approved: ["✅", `Задание «${esc(p.title)}» засчитано: +${p.amount} $₽`], rejected: ["❌", `Отклик на «${esc(p.title)}» отклонён: ${esc(p.reason || "")}`],
    dispute_lost: ["⚖️", `Модератор подтвердил отказ по заданию «${esc(p.title)}»`] }[p.result] || ["📋", esc(p.title)]).concat([`/tasks/${p.task_id}`]),
  wall: (p) => ["📝", `@${esc(p.username)} написал(а) у тебя на стене: «${esc(p.preview)}»`, ME ? `/u/${encodeURIComponent(ME.user.username)}#wall` : "#"],
  appeal: (p) => ["⚖️", p.decision === "accept" || p.decision === "approve" ? "Апелляцию приняли — блокировка снята" : `Апелляцию отклонили${p.comment ? ": " + esc(p.comment) : ""}`, "/banned"],
};

async function pageNotifications() {
  const root = $("#notifications");
  const d = await api("GET", "/api/notifications");
  root.innerHTML = d.items.length ? d.items.map((n) => {
    const [e, text, href] = (NOTIF[n.kind] || (() => ["🔔", esc(n.kind), "#"]))(n.payload || {});
    return `<a class="notif ${n.is_read ? "" : "unread"}" href="${href}"><span class="e">${e}</span><span>${text}<small>${esc(fmtDate(n.created_at))}</small></span></a>`;
  }).join("") : `<p class="muted">Пока тихо. Ответь на пару вопросов — и тут станет шумно 😉</p>`;
  $("#read-all").onclick = async () => {
    const r = await api("POST", "/api/notifications/read", {});
    setBell(r.unread);
    $$(".notif.unread", root).forEach((x) => x.classList.remove("unread"));
  };
}

// ---------------------------------------------------------------- search
async function pageSearch() {
  const form = $("#search-form"), out = $("#search-results");
  async function run(q) {
    if (q.trim().length < 2) { out.innerHTML = ""; return; }
    history.replaceState(null, "", `/search?q=${encodeURIComponent(q)}`);
    try {
      const d = await api("GET", `/api/search?q=${encodeURIComponent(q)}`);
      out.innerHTML = d.items.length
        ? d.items.map((q) => `<a class="best-item" href="/q/${q.id}"><b>${esc(q.title)}</b><small>${answersWord(q.answers_count)} · @${esc(q.author?.username)}</small></a>`).join("")
        : `<p class="muted">Ничего не нашли. Может, самое время <a href="/ask">спросить</a>?</p>`;
    } catch (_) {}
  }
  form.onsubmit = (e) => { e.preventDefault(); run(form.elements.q.value); };
  if (form.elements.q.value) run(form.elements.q.value);
}

// ---------------------------------------------------------------- мини-игра «Чайный гриб»
const KB_DISC = [ // [мутация, заливка, обводка] — первая подходящая по приоритету
  ["crystal", "#aef4ff", "#4fc3dc"], ["golden", "#ffd54a", "#b8860b"], ["spotted", "#e0442f", "#9c2414"],
  ["night", "#51639e", "#2c3866"], ["sweet_tooth", "#ffc2e0", "#e58db1"],
];

function shade(hex, f = 0.6) {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => Math.round(v * f));
  return `rgb(${c.join(",")})`;
}
const RAR = { legendary: "Легендарная", epic: "Эпическая", rare: "Редкая", common: "Обычная" };
function mutChip(m) {
  return `<span class="kb-mut r-${m.rarity}" title="${esc(RAR[m.rarity] || "")}: ${esc(m.title)}${m.inherited ? " (унаследована)" : ""}">${esc(m.emoji)} ${esc(m.title)}${m.serial ? ` <b class="kb-serial">#${m.serial}</b>` : ""}${m.inherited ? " 🧬" : ""}</span>`;
}
async function kombuchaCardModal(id) {
  let d;
  try { d = (await api("GET", `/api/kombucha/${id}/card`, undefined, { quiet: true })).kombucha; } catch (_) { return; }
  const HOW = { grown: "вырастил(а)", gift: "получил(а) в подарок", trade: "выменял(а)", sale: "купил(а)" };
  modal(`<div class="kb-cardm"><div class="kb-cardm-svg">${kombuchaSVG(d)}</div>
    <h2>${esc(d.name)} ${d.frozen ? "🧊" : ""}</h2>
    <div class="muted">${esc(d.stage.title)} · ${d.xp} XP · поколение ${d.generation} · владелец <a href="/u/${encodeURIComponent(d.owner)}">@${esc(d.owner)}</a>${d.price != null ? ` · 🏷 ${d.price} $₽` : ""}</div>
    <h3>Мутации</h3>${d.mutations.length ? `<table class="kb-cardm-t">${d.mutations.map((m) => `<tr><td>${esc(m.emoji)} ${esc(m.title)}</td><td>${esc(RAR[m.rarity])}</td><td><b>#${m.serial ?? "?"}</b> из ${m.issued}</td></tr>`).join("")}</table>` : `<p class="muted">Без мутаций</p>`}
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
    if (KB_OWN_FX.has(m.code)) return;                               // у этих — ручная отрисовка ниже
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
      try { r = await api("POST", `/api/kombucha/${k.id}/game/${game}/finish`, body); } catch (_) { sh.close(); return; }
      sh.over = true;
      const R = r.result, ST = { tea: "🫖 заварка", sweet: "🍬 сахар", clean: "🧽 чистота" };
      const extra = { pour: `налито точно: ${R.rounds?.filter((x) => x.points >= 0.5).length || 0}/5${R.rounds?.some((x) => x.spilled) ? " · пролито: " + R.rounds.filter((x) => x.spilled).length : ""}`,
        memory: `цепочка: ${R.reached}/${R.total}`, sugar: `сахар ${R.caught} · ошибок ${R.wrong} · пропущено ${R.missed}`,
        flies: `отогнано мушек: ${R.swatted}` }[game] || "";
      sh.area.innerHTML = `<div class="kb-med-result"><h2>${esc(R.grade)}</h2><p class="kb-med-acc">Точность: <b>${Math.round(R.accuracy * 100)}%</b></p>
        <p class="muted">${esc(extra)}</p>
        <p>${R.wood ? `+${R.wood} $₽ · ` : `<span class="muted">$₽ за игры сегодня уже собраны · </span>`}💛 +${R.happy}${R.boost ? ` · ${ST[R.stat]} +${R.boost}` : ""}${R.xp ? ` · +${R.xp} опыта` : ""}</p>
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

async function kbStart(k, game) {
  try { return await api("POST", `/api/kombucha/${k.id}/game/${game}/start`); } catch (_) { return null; }
}

// 🫖 Налей и не пролей: держишь — льётся, отпускаешь — стоп. 5 раундов.
async function kbPour(k, onDone) {
  const G = await kbStart(k, "pour"); if (!G) return;
  const sh = kbGameShell("🫖 Налей и не пролей", "Зажми палец (или пробел) — льётся чай. Отпусти, когда уровень дойдёт до метки. Перелил через край — пролил.");
  const holds = []; let round = 0, t0 = 0, pouring = false;
  const level = (rd, ms) => rd.rate * (ms / 1000) + rd.accel * (ms / 1000) ** 2;
  const draw = (lvl) => {
    const rd = G.rounds[round];
    sh.area.innerHTML = `<div class="kb-pour"><div class="kb-pour-jar ${esc(rd.jar)}"><div class="kb-pour-tea" style="height:${Math.min(100, lvl * 100)}%"></div>
      <div class="kb-pour-mark" style="bottom:${rd.target * 100}%"><span>метка</span></div>${pouring ? `<div class="kb-pour-stream"></div>` : ""}</div>
      <div class="muted">${esc(rd.jar)}</div></div>`;
    sh.hud.textContent = `раунд ${round + 1}/5`;
  };
  const tick = () => { if (!pouring) return; const rd = G.rounds[round], lvl = level(rd, performance.now() - t0); draw(lvl); if (lvl >= 1.05) up(); else sh.raf = requestAnimationFrame(tick); };
  const down = (e) => { if (sh.over || pouring || round >= 5 || e.target.closest?.(".kb-med-x")) return; e.preventDefault?.(); pouring = true; t0 = performance.now(); tick(); };
  const up = () => {
    if (!pouring) return; pouring = false; cancelAnimationFrame(sh.raf);
    const ms = Math.round(performance.now() - t0), rd = G.rounds[round], lvl = level(rd, ms);
    holds.push(ms); draw(lvl);
    const err = Math.abs(lvl - rd.target);
    sh.say(lvl >= 1 ? "Пролил! 💦" : err <= G.tolerance * 0.3 ? "Идеально ✨" : err <= G.tolerance ? "Неплохо 👍" : "Мимо метки", lvl >= 1 ? "miss" : err <= G.tolerance ? "perfect" : "miss");
    round++;
    if (round >= 5) sh.later(() => sh.finish(k, "pour", { token: G.token, holds }, onDone), 700);
    else sh.later(() => draw(0), 700);
  };
  sh.el.addEventListener("pointerdown", down); sh.el.addEventListener("pointerup", up); sh.el.addEventListener("pointerleave", up);
  const kd = (e) => { if (e.code === "Space" && !e.repeat) down(e); }, ku = (e) => { if (e.code === "Space") up(); };
  document.addEventListener("keydown", kd); document.addEventListener("keyup", ku);
  const close0 = sh.close; sh.close = () => { document.removeEventListener("keydown", kd); document.removeEventListener("keyup", ku); close0(); };
  draw(0);
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
  const sh = kbGameShell("🪰 Отгони мушек", "Мушки летят к банке — тапни каждую, пока не села. Три севшие — конец.");
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
    d.className = "kb-fly"; d.textContent = "🪰";
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
    try { r = await api("POST", `/api/kombucha/${k.id}/meditate/finish`, { token: T.token, taps }); }
    catch (_) { cleanup(); return; }
    const R = r.result;
    el.querySelector(".kb-med-stage").insertAdjacentHTML("afterend", `<div class="kb-med-result">
      <h2>${esc(R.grade)}</h2>
      <p class="kb-med-acc">Точность: <b>${Math.round(R.accuracy * 100)}%</b></p>
      <p class="muted">✨ идеально ${R.perfect} · 👍 хорошо ${R.good} · мимо ${R.miss}${R.extra ? ` · лишних тапов ${R.extra}` : ""}</p>
      <p>${R.wood ? `+${R.wood} $₽ · ` : `<span class="muted">$₽ за сегодня уже собраны · </span>`}💛 +${R.happy} счастья${R.xp ? ` · +${R.xp} опыта` : ""}</p>
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
      <rect x="30" y="${top}" width="160" height="${230 - top}" fill="${tint}" class="kb-liquid"/>
      <path d="M30,${top} Q70,${top - 4} 110,${top} T190,${top}" stroke="#ffffff55" stroke-width="2" fill="none"/>
      ${stars}${bubbles}${FX.liquid.join("")}
      <g class="${k.alive ? "kb-float" : ""}"><g class="kb-mush" transform="translate(${cx},${cy})"${FX.glow.length ? ` style="filter:${FX.glow.slice(0, 3).join(" ")}"` : ""}>
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
      </g></g>
      <g opacity="${dirt.toFixed(2)}">${spots}</g>
      ${k.mold ? Array.from({ length: 9 }, (_, i) => `<circle cx="${cx + (((i * 37) % 80) - 40) * (w / 60)}" cy="${cy - h * 0.4 + ((i * 13) % 10) - 5}" r="${3 + (i % 3) * 2}" class="kb-moldspot"/>`).join("") : ""}
    </g>
    <path d="M40,40 Q40,28 55,26 L165,26 Q180,28 180,40 L184,200 Q184,214 168,214 L52,214 Q36,214 36,200 Z" class="kb-jar"${FX.glass.length ? ` style="fill:${FX.glass[0]}40;stroke:${FX.glass[FX.glass.length - 1]};stroke-width:4"` : ""}/>${FX.jar.join("")}
    <path d="M52,50 L50,190" class="kb-glare"/>${has("clean_freak") ? `<path d="M64,60 L63,110" class="kb-glare"/>` : ""}
    ${k.frozen ? `<path d="M40,40 Q40,28 55,26 L165,26 Q180,28 180,40 L184,200 Q184,214 168,214 L52,214 Q36,214 36,200 Z" class="kb-ice"/><text x="160" y="60" class="kb-acc" font-size="20">❄️</text>` : ""}
    ${small ? "" : `<g class="kb-mood-badge"><circle cx="186" cy="30" r="17"/><text x="186" y="37" text-anchor="middle" font-size="20">${KB_MOOD[k.mood]?.[0] || "🙂"}</text></g>`}
    <text x="110" y="228" text-anchor="middle" class="kb-label">3 л</text>
  </svg>`;
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
      <p>Чтобы завести свой гриб, войди в аккаунт.</p><a class="btn btn-accent" href="/login?next=/kombucha">Войти</a></div>`;
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
      : `<div class="kb-sprout" title="Легенда делится раз в неделю, если 7 дней за ней ухаживали и на ней нет плесени"><span>🌱 Деление${sp.count ? ` (было ${sp.count})` : ""}:</span>
          <span class="${sp.legend ? "ok" : ""}">${sp.legend ? "✅" : "⏳"} стадия «Легенда»</span>
          <span class="${sp.care_days >= sp.need_days ? "ok" : ""}">${sp.care_days >= sp.need_days ? "✅" : "⏳"} дней ухода ${sp.care_days}/${sp.need_days}</span>
          <span class="${sp.next_in ? "" : "ok"}">${sp.next_in ? `⏳ следующее через ${fmtLeft(sp.next_in)}` : "✅ раз в неделю"}</span>
          ${sp.healthy ? "" : `<span>🦠 сначала вылечи плесень</span>`}</div>`;
    return `<div class="panel kb-main ${k.alive ? "" : "is-dead"}">
      <div class="kb-scene">
        <button class="kb-fs-btn" data-fs title="Смотреть гриб во весь экран">⛶</button>
        <div class="kb-say" id="kb-say">${esc(k.alive ? k.phrase : "Гриб закис… 🪦")}</div>
        ${kombuchaSVG(k)}
      </div>
      <div class="kb-info">
        <div class="kb-name"><h2>${esc(k.name)}</h2><button class="link-btn" data-rename title="Переименовать">✏️</button></div>
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
          <button class="btn btn-accent kb-daily" data-act="daily"${k.cooldowns.daily ? " disabled" : ""}>🏆 Схема дня${k.cooldowns.daily ? ` · через ${fmtLeft(k.cooldowns.daily)}` : ": забрать бонус за ответы"}</button>
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

  const render = () => {
    if (!cur() && S.items.length) sel = S.items[0].id;
    const k = cur();
    if (k) { sel = k.id; localStorage.setItem("kb-sel", sel); }
    root.innerHTML = `<div class="kb-bar-top"><span>🫙 Банки: <b>${S.jars.used}/${S.jars.jars}</b></span><span>Баланс: <a href="/wallet"><b>${S.wood} $₽</b></a></span></div>
      ${renderJars()}${renderMain(k)}`;
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
    const afterGame = (r) => {
      S.items = S.items.map((x) => (x.id === r.kombucha.id ? r.kombucha : x));
      S.wood = r.wood_balance; render();
      if (r.result.mutation) toast(`🧬 Игра открыла мутацию: ${r.result.mutation.emoji} «${r.result.mutation.title}» #${r.result.mutation.serial}!`);
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
      ${ME && ME.user.username === k.owner ? `<span class="muted">твой</span>` : `<button class="btn btn-accent btn-sm" data-buy="${k.id}" data-price="${k.price}">Купить · ${k.price} $₽</button>`}</div>`)).join("")
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

// ---------------------------------------------------------------- полка и стена в профиле
async function profileExtras(d) {
  const u = d.user, hidden = new Set(d.is_owner ? [] : d.custom.hidden_sections);
  const box = $("#profile-extras");
  if (!box) return;
  const parts = [];
  if (!hidden.has("shelf")) parts.push(`<div class="panel" id="shelf"><h2 style="margin-top:0">🧊 Полка с грибами</h2><div class="kb-shelf" id="shelf-list"><p class="muted">Загружаем…</p></div></div>`);
  if (!hidden.has("wall")) parts.push(`<div class="panel" id="wall"><h2 style="margin-top:0">📝 Стена</h2><div id="wall-form"></div><div id="wall-list"></div><button class="btn btn-ghost btn-sm" id="wall-more" hidden>Ещё</button></div>`);
  box.innerHTML = parts.join("");
  if (!hidden.has("shelf")) {
    try {
      const s = await api("GET", `/api/users/${encodeURIComponent(u.username)}/shelf`, undefined, { quiet: true });
      $("#shelf-list").innerHTML = s.items.length ? s.items.map((k) => kombuchaCard(k, k.price != null ? `<a class="btn btn-sm btn-accent" href="/market">🏷 ${k.price} $₽</a>` : "")).join("")
        : `<p class="muted">${d.is_owner ? "Пусто. Заморозь гриб на <a href=\"/kombucha\">странице гриба</a> — и он встанет сюда." : "Пока пусто."}</p>`;
    } catch (_) {}
  }
  if (hidden.has("wall")) return;
  let before = null;
  const list = $("#wall-list");
  const post = (p) => `<div class="wall-post" data-id="${p.id}">${avatarHTML(p.author)}<div class="wp-body"><div class="wp-head">${userLink(p.author)} <small class="muted">${esc(fmtDate(p.created_at))}</small>
      ${p.can_delete ? `<button class="link-btn wp-del" data-del="${p.id}" title="Удалить">✕</button>` : ""}</div><div class="md">${p.body_html}</div></div></div>`;
  const load = async (more = false) => {
    const w = await api("GET", `/api/users/${encodeURIComponent(u.username)}/wall${before ? `?before=${before}` : ""}`, undefined, { quiet: true });
    if (!more) $("#wall-form").innerHTML = w.can_post ? `<form class="wall-form"><textarea class="input" maxlength="500" rows="2" placeholder="Напиши что-нибудь на стене @${esc(u.username)}…"></textarea><div class="wall-form-foot"><small class="muted"><span id="wall-n">0</span>/500</small><button class="btn btn-accent btn-sm">Отправить</button></div></form>`
      : w.closed ? `<p class="muted">🔒 Хозяин закрыл стену.</p>` : ME ? "" : `<p class="muted"><a href="/login?next=${encodeURIComponent(here())}">Войди</a>, чтобы написать на стене.</p>`;
    const html = w.items.map(post).join("");
    if (more) list.insertAdjacentHTML("beforeend", html); else list.innerHTML = html || `<p class="muted">Здесь пока тихо. Будь первым!</p>`;
    before = w.next_before; $("#wall-more").hidden = !before;
    const f = $("#wall-form form");
    if (f && !more) {
      const ta = f.querySelector("textarea");
      ta.oninput = () => ($("#wall-n").textContent = ta.value.length);
      f.onsubmit = async (e) => {
        e.preventDefault();
        if (!ta.value.trim()) return;
        try { await api("POST", `/api/users/${encodeURIComponent(u.username)}/wall`, { body: ta.value.trim() }); ta.value = ""; before = null; load(); } catch (_) {}
      };
    }
  };
  list.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-del]");
    if (!b || !confirm("Удалить запись?")) return;
    try { await api("DELETE", `/api/wall/${b.dataset.del}`); b.closest(".wall-post").remove(); } catch (_) {}
  });
  $("#wall-more").onclick = () => load(true);
  try { await load(); } catch (_) {}
  if (location.hash === "#wall") $("#wall")?.scrollIntoView();
}

// ---------------------------------------------------------------- задания за $₽
const TASK_ST = { open: "🟢 открыто", done: "✅ все места заняты", closed: "⏹ закрыто автором", expired: "⌛ срок вышел", removed: "⛔ снято модератором" };
const SUB_ST = { pending: "⏳ на проверке", approved: "✅ засчитано", rejected: "❌ отклонено", disputed: "⚖️ спор у модератора" };
function taskCard(t) {
  return `<a class="task-card panel" href="/tasks/${t.id}"><div class="task-top"><b class="task-reward">+${t.reward} $₽</b><span class="muted">${TASK_ST[t.status] || t.status}</span></div>
    <h3>${esc(t.title)}</h3><div class="muted task-meta">от @${esc(t.author.username)} · мест ${t.slots_left}/${t.slots} · до ${esc(fmtDate(t.deadline))}${t.pending ? ` · на проверке ${t.pending}` : ""}</div>
    ${t.my_submission ? `<div class="task-mine">${SUB_ST[t.my_submission.status]}</div>` : ""}</a>`;
}
async function pageTasks() {
  const root = $("#tasks-root");
  const id = root.dataset.taskId;
  if (id) return pageTask(root, id);
  let tab = "open", sort = "new", rules;
  const load = async () => {
    const d = await api("GET", `/api/tasks?tab=${tab}&sort=${sort}`);
    rules = d.rules;
    $("#tasks-list").innerHTML = d.items.map(taskCard).join("") || `<p class="muted panel">${tab === "open" ? "Открытых заданий нет. Создай первое!" : "Пусто."}</p>`;
  };
  $$("[data-ttab]").forEach((b) => (b.onclick = () => { tab = b.dataset.ttab; $$("[data-ttab]").forEach((x) => x.classList.toggle("active", x === b)); load(); }));
  $("#tasks-sort").onchange = (e) => { sort = e.target.value; load(); };
  const f = $("#task-form");
  let upd = null;
  if (f) {
    upd = () => {
      const r = Number(f.elements.reward.value) || 0, n = Number(f.elements.slots.value) || 0, base = r * n;
      const fee = Math.max(1, Math.round(base * (rules?.fee ?? 0.1)));
      $("#task-cost").textContent = base ? `Спишется ${base + fee} $₽: ${r} × ${n} мест + ${fee} комиссии` : "";
    };
    f.addEventListener("input", upd);
    f.onsubmit = async (e) => {
      e.preventDefault();
      const el = f.elements;
      try {
        const r = await api("POST", "/api/tasks", { title: el.title.value.trim(), body: el.body.value.trim(), proof: el.proof.value.trim(),
          reward: Number(el.reward.value), slots: Number(el.slots.value), days: Number(el.days.value) });
        setWood(r.wood); toast("📋 Задание опубликовано, $₽ в эскроу"); location.href = `/tasks/${r.task.id}`;
      } catch (_) {}
    };
  }
  if (ME?.permissions?.includes("content.hide")) $("#tasks-disputes-tab")?.removeAttribute("hidden");
  $("#tasks-disputes-tab")?.addEventListener("click", async () => {
    const d = await api("GET", "/api/mod/task-disputes");
    $("#tasks-list").innerHTML = d.items.map((x) => `<div class="panel"><b>«${esc(x.task.title)}»</b> · ${x.task.reward} $₽ · исполнитель ${userLink(x.user)}
      <div class="muted">Нужно прислать: ${esc(x.task.proof || "—")}</div><div class="md">${x.body_html}</div><div class="muted">Причина отказа: ${esc(x.reason || "—")}</div>
      <button class="btn btn-accent btn-sm" data-dis="${x.id}" data-op="approve">Засчитать</button> <button class="btn btn-ghost btn-sm" data-dis="${x.id}" data-op="reject">Подтвердить отказ</button></div>`).join("") || `<p class="muted panel">Споров нет</p>`;
    $$("[data-dis]").forEach((b) => (b.onclick = async () => { try { await api("POST", `/api/mod/task-submissions/${b.dataset.dis}/${b.dataset.op}`, {}); b.closest(".panel").remove(); } catch (_) {} }));
  });
  try { await load(); upd?.(); } catch (_) {}
}
async function pageTask(root, id) {
  const load = async () => {
    let d;
    try { d = await api("GET", `/api/tasks/${id}`, undefined, { quiet: true }); } catch (_) { root.innerHTML = `<div class="panel"><h1>Задание не найдено</h1><a href="/tasks">← Все задания</a></div>`; return; }
    const t = d.task, mine = t.my_submission;
    root.innerHTML = `<a href="/tasks" class="muted">← Все задания</a>
      <article class="panel task-full"><div class="task-top"><b class="task-reward">+${t.reward} $₽</b><span>${TASK_ST[t.status]}</span></div>
        <h1>${esc(t.title)}</h1><div class="muted">от ${userLink(t.author)} · мест ${t.slots_left}/${t.slots} · до ${esc(fmtDate(t.deadline))}</div>
        <div class="md">${t.body_html}</div>${t.proof ? `<div class="task-proof">📎 Что прислать: ${esc(t.proof)}</div>` : ""}
        ${d.is_author && t.status === "open" ? `<button class="btn btn-ghost btn-sm" id="task-close">⏹ Закрыть досрочно (вернуть остаток)</button>` : ""}
        ${d.is_mod && t.status !== "removed" ? `<button class="btn btn-ghost btn-sm" id="task-remove">⛔ Снять (модератор)</button>` : ""}
        ${t.refunded != null && d.is_author ? `<div class="muted">Возвращено тебе: ${t.refunded} $₽</div>` : ""}</article>
      ${!ME ? `<p class="panel"><a href="/login?next=${encodeURIComponent(here())}">Войди</a>, чтобы выполнить задание.</p>`
        : !d.is_author && !mine && t.status === "open" ? `<form class="panel" id="sub-form"><h2>Выполнить</h2><textarea class="input" name="body" rows="3" maxlength="1000" placeholder="Доказательство: ссылка, текст, описание…" required></textarea><button class="btn btn-accent">📤 Отправить на проверку</button>
          <p class="muted">Автор проверит отклик. Если он не ответит за 72 часа, отклик засчитается сам. На отказ можно подать спор модератору.</p></form>` : ""}
      ${mine ? `<div class="panel">Твой отклик: <b>${SUB_ST[mine.status]}</b>${mine.reason ? ` — ${esc(mine.reason)}` : ""} ${mine.status === "rejected" ? `<button class="btn btn-ghost btn-sm" data-sub="${mine.id}" data-op="dispute">⚖️ Оспорить</button>` : ""}</div>` : ""}
      <section class="panel"><h2>${d.is_author ? "Отклики" : "Засчитанные"} (${d.submissions.length})</h2>
        ${d.submissions.map((x) => `<div class="task-sub ${x.status}"><div>${userLink(x.user)} <span class="muted">${SUB_ST[x.status]} · ${esc(fmtDate(x.created_at))}</span></div><div class="md">${x.body_html}</div>
          ${x.reason ? `<div class="muted">${esc(x.reason)}</div>` : ""}
          ${d.is_author && x.status === "pending" ? `<button class="btn btn-accent btn-sm" data-sub="${x.id}" data-op="approve">✅ Засчитать (+${t.reward} $₽)</button> <button class="btn btn-ghost btn-sm" data-sub="${x.id}" data-op="reject">❌ Отклонить</button>` : ""}</div>`).join("") || `<p class="muted">Пока никого.</p>`}</section>`;
    $("#sub-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await api("POST", `/api/tasks/${id}/submit`, { body: e.target.elements.body.value.trim() }); toast("📤 Отправлено на проверку"); load(); } catch (_) {}
    });
    $$("[data-sub]", root).forEach((b) => (b.onclick = async () => {
      let reason = null;
      if (b.dataset.op === "reject") { reason = prompt("Почему отклоняешь? Исполнитель сможет оспорить."); if (!reason) return; }
      try { await api("POST", `/api/task-submissions/${b.dataset.sub}/${b.dataset.op}`, { reason }); load(); } catch (_) {}
    }));
    $("#task-close")?.addEventListener("click", async () => { if (confirm("Закрыть задание? Невыплаченный остаток вернётся (комиссия — нет).")) { try { await api("POST", `/api/tasks/${id}/close`, {}); load(); } catch (_) {} } });
    $("#task-remove")?.addEventListener("click", async () => { const r = prompt("Причина снятия:", "нарушение правил"); if (r) { try { await api("POST", `/api/mod/tasks/${id}/remove`, { reason: r }); load(); } catch (_) {} } });
  };
  await load();
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

// ---------------------------------------------------------------- boot
const PAGES = {
  feed: () => initFeed(), debates: () => initFeed(), kombucha: pageKombucha, market: pageMarket, tasks: pageTasks, wallet: pageWallet, room: pageRoom, question: pageQuestion, ask: pageAsk, rooms: pageRooms,
  profile: pageProfile, login: pageAuth, register: pageAuth, banned: pageBanned, notifications: pageNotifications, search: pageSearch, mod: pageMod, admin: pageAdmin,
  settings: pageSettings, faq: pageFaq,
};

(async function boot() {
  initHeader();
  await loadMe();
  const fn = PAGES[document.body.dataset.page];
  if (fn) fn();
})();
