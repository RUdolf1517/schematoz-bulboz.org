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
    <div><span class="kind">${KIND[q.kind] || esc(q.kind)}</span>${room}<span class="q-rating" title="Рейтинг вопроса: голоса + ответы + комментарии">★ ${esc(q.rating)}</span></div>
    ${cover}
    <h2>${esc(q.title)}</h2>
    ${preview}
    <div class="meta-row"><span>${answersWord(q.answers_count)}</span><span>@${esc(q.author?.username)}</span><span class="open-hint">Открыть →</span></div>
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
  feed.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
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
    const idx = Math.round(feed.scrollTop / (cards[0].offsetHeight + 12));
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); cards[Math.min(idx + 1, cards.length - 1)].scrollIntoView({ behavior: "smooth" }); }
    if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); cards[Math.max(idx - 1, 0)].scrollIntoView({ behavior: "smooth" }); }
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
  root.innerHTML = profileHTML(d);
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
  const chips = (name, obj, cur) => Object.entries(obj).map(([k, v]) => `<label class="pick"><input type="radio" name="${name}" value="${esc(k)}"${k === cur ? " checked" : ""}><span class="swatch ${name}-${esc(k)}"></span>${esc(v)}</label>`).join("");
  const lvl = d.user.level, unlimited = d.user.rating_tier > 0;
  form.innerHTML = `
    <section class="panel"><h2>👤 Основное</h2>
      <label>Отображаемое имя<input class="input" name="display_name" maxlength="${L.display_name}" value="${esc(s.display_name)}"></label>
      <label>Короткое био<textarea name="bio" rows="2" maxlength="${L.bio}">${esc(s.bio)}</textarea></label>
      <div class="row2">
        <label>Статус-эмодзи<input class="input" name="status_emoji" maxlength="8" placeholder="😎" value="${esc(s.status_emoji)}"></label>
        <label>Статус<input class="input" name="status_text" maxlength="${L.status_text}" placeholder="готовлюсь к ЕГЭ 📚" value="${esc(s.status_text)}"></label>
      </div>
      <div class="row2">
        <label>Город<input class="input" name="city" maxlength="${L.city}" value="${esc(s.city)}"></label>
        <label>Местоимения<input class="input" name="pronouns" maxlength="${L.pronouns}" placeholder="он/его" value="${esc(s.pronouns)}"></label>
      </div>
      <label>О себе (markdown, до ${L.about} символов)<textarea name="about" rows="5" maxlength="${L.about}">${esc(s.about)}</textarea></label>
    </section>
    <section class="panel"><h2>🖼 Аватар и обложка</h2>
      <div class="media-row"><div id="av-prev"></div>
        <label class="btn btn-sm btn-ghost">Загрузить аватар<input type="file" accept="image/*" id="av-file" hidden></label>
        <button type="button" class="btn btn-sm btn-ghost" id="av-clear">Убрать</button></div>
      <div class="media-row"><div id="bn-prev" class="bn-prev"></div>
        <label class="btn btn-sm btn-ghost">Загрузить обложку<input type="file" accept="image/*" id="bn-file" hidden></label>
        <button type="button" class="btn btn-sm btn-ghost" id="bn-clear">Убрать</button></div>
      <h3>Рамка аватара</h3>
      <div class="picks">${Object.entries(O.frames).map(([k, f]) => { const locked = !unlimited && lvl < f.min_level;
        return `<label class="pick${locked ? " locked" : ""}" title="${locked ? `Откроется на ${f.min_level} уровне` : ""}"><input type="radio" name="avatar_frame" value="${esc(k)}"${k === s.avatar_frame ? " checked" : ""}${locked ? " disabled" : ""}><span class="avatar frame-${esc(k)}">${initial(d.user.username)}</span>${esc(f.title)}${locked ? ` 🔒${f.min_level}` : ""}</label>`; }).join("")}</div>
    </section>
    <section class="panel"><h2>🎨 Оформление</h2>
      <h3>Тема</h3><div class="picks">${chips("theme", O.themes, s.theme)}</div>
      <div class="row2">
        <label>Акцентный цвет<span class="accent-row"><input type="color" name="accent" value="${esc(s.accent || "#ff5a36")}"><label class="toggle-inline"><input type="checkbox" name="accent_on"${s.accent ? " checked" : ""}> свой цвет</label></span></label>
        <label>Шрифт<select name="font">${opts(O.fonts, s.font)}</select></label>
      </div>
      <div class="row2">
        <label>Карточки<select name="card_style">${opts(O.card_styles, s.card_style)}</select></label>
        <label>Раскладка шапки<select name="layout">${opts(O.layouts, s.layout)}</select></label>
      </div>
    </section>
    <section class="panel"><h2>🏷 Интересы и ссылки</h2>
      <label>Интересы через запятую (до ${L.interests})<input class="input" name="interests" value="${esc(s.interests.join(", "))}" placeholder="аниме, физика, cs2"></label>
      <div id="links"></div>
      <button type="button" class="btn btn-sm btn-ghost" id="add-link">+ ссылка</button>
    </section>
    <section class="panel"><h2>🏆 Витрина и закреп</h2>
      <p class="muted">Выбери до ${L.showcase_badges} бейджей, они будут в шапке профиля.</p>
      <div class="picks">${d.badges.length ? d.badges.map((b) => `<label class="pick"><input type="checkbox" name="showcase" value="${esc(b.code)}"${s.showcase_badges.includes(b.code) ? " checked" : ""}>${esc(b.emoji)} ${esc(b.title)}</label>`).join("") : `<span class="muted">Бейджей пока нет</span>`}</div>
      <label>Закреплённый ответ<select name="pinned_answer_id"><option value="">— не закреплять —</option>${d.answers.map((a) => `<option value="${a.id}"${a.id === s.pinned_answer_id ? " selected" : ""}>${esc(a.question_title.slice(0, 80))}</option>`).join("")}</select></label>
    </section>
    <section class="panel"><h2>🙈 Приватность разделов</h2>
      <p class="muted">Отмеченные разделы увидишь только ты.</p>
      <div class="picks">${Object.entries(O.sections).map(([k, v]) => `<label class="pick"><input type="checkbox" name="hidden" value="${esc(k)}"${s.hidden_sections.includes(k) ? " checked" : ""}>${esc(v)}</label>`).join("")}</div>
    </section>
    <div class="save-bar"><button class="btn btn-accent">Сохранить</button> <a class="btn btn-ghost" href="/u/${encodeURIComponent(d.user.username)}">Открыть профиль</a></div>`;

  let links = [...s.links];
  let avatar = s.avatar_url, banner = s.banner_url;
  const renderLinks = () => {
    $("#links").innerHTML = links.map((l, i) => `<div class="row2 link-row"><input class="input" data-i="${i}" data-k="title" placeholder="Название" maxlength="30" value="${esc(l.title)}"><input class="input" data-i="${i}" data-k="url" placeholder="https://…" value="${esc(l.url)}"><button type="button" class="btn btn-sm btn-ghost" data-del="${i}">✕</button></div>`).join("");
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
  form.addEventListener("input", preview);
  form.addEventListener("change", preview);
  const hook = (inputId, set) => {
    $(inputId).onchange = async (e) => {
      const file = e.target.files[0]; e.target.value = "";
      if (!file) return;
      try { const r = await uploadImage(file); set(r.url); preview(); toast("Загружено, не забудь сохранить"); } catch (_) {}
    };
  };
  hook("#av-file", (u) => (avatar = u)); hook("#bn-file", (u) => (banner = u));
  $("#av-clear").onclick = () => { avatar = null; preview(); };
  $("#bn-clear").onclick = () => { banner = null; preview(); };
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("PATCH", "/api/me/profile", collect());
      base.user = { ...base.user, ...r.user }; base.custom = { ...base.custom, ...r.settings };
      toast("Профиль сохранён ✨"); preview();
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

async function pageAdmin() {
  if (denied("analytics.read")) return;
  initPanel({
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
  feed: () => initFeed(), room: pageRoom, question: pageQuestion, ask: pageAsk, rooms: pageRooms,
  profile: pageProfile, login: pageAuth, register: pageAuth, banned: pageBanned, notifications: pageNotifications, search: pageSearch, mod: pageMod, admin: pageAdmin,
  settings: pageSettings, faq: pageFaq,
};

(async function boot() {
  initHeader();
  await loadMe();
  const fn = PAGES[document.body.dataset.page];
  if (fn) fn();
})();
