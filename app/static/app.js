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
  if (ME.ban && document.body.dataset.page !== "banned") {
    const b = $("#ban-banner");
    b.innerHTML = `Аккаунт заблокирован${ME.ban.ends_at ? " до " + esc(fmtDate(ME.ban.ends_at)) : " навсегда"}. <a href="/banned">Подробнее и апелляция →</a>`;
    b.hidden = false;
  }
  return ME;
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
  return `<a href="/u/${encodeURIComponent(u.username)}"><span class="avatar">${initial(u.username)}</span>@${esc(u.username)}</a>`;
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
    preview = `<div class="answer-preview">${tag}${side} <span class="muted">· @${esc(a.author?.username)} · ${signed(a.score)}</span><p>${esc(a.content.body)}</p></div>`;
  }
  return `<article class="card" data-href="/q/${q.id}" tabindex="-1">
    <div><span class="kind">${KIND[q.kind] || esc(q.kind)}</span>${room}</div>
    <h2>${esc(q.title)}</h2>
    ${preview}
    <div class="meta-row"><span>${answersWord(q.answers_count)}</span><span>@${esc(q.author?.username)}</span><span class="open-hint">Открыть →</span></div>
  </article>`;
}

function initFeed(extraParams = {}) {
  const feed = $("#feed");
  let tab = "hot", offset = 0, loading = false, done = false;

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

  function answerHtml(a) {
    const q = data.question;
    const side = a.debate_side && q.debate ? `<span class="side-badge side-${a.debate_side}">${esc(q.debate[a.debate_side])}</span>` : "";
    const modBtn = perm("content.hide") ? `<button class="link-btn" data-hide="${a.id}">Скрыть</button>` : "";
    return `<div class="answer ${a.is_best ? "best" : ""}" id="a${a.id}" data-aid="${a.id}">
      <div class="byline">${userLink(a.author)} ${a.is_best ? `<span class="scheme-badge">🔥 Схема</span>` : ""} ${side} <span>· ${esc(fmtDate(a.created_at))}</span></div>
      <div class="text">${esc(a.content.body)}</div>
      <div class="actions">${voteButtons(a)}<span class="spacer"></span>
        <button class="link-btn" data-share="${a.id}">📤 В сторис</button>
        <button class="link-btn" data-report="${a.id}">Пожаловаться</button>${modBtn}</div>
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
        <span class="kind">${KIND[q.kind] || esc(q.kind)}</span>
        <h1>${esc(q.title)}</h1>
        ${q.body ? `<div class="body">${esc(q.body)}</div>` : ""}
        <div class="byline">${userLink(q.author)} <span>· ${esc(fmtDate(q.created_at))}</span>${room}<span class="spacer" style="flex:1"></span>
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
  title.oninput = () => ($('.counter[data-for="title"]').textContent = `${title.value.length}/300`);
  const { items } = await api("GET", "/api/rooms");
  roomSel.insertAdjacentHTML("beforeend", items.map((r) => `<option value="${r.id}">${esc(r.title)}</option>`).join(""));
  if (params.get("room")) { const r = items.find((x) => x.slug === params.get("room")); if (r) roomSel.value = r.id; }
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const body = { kind: f.get("kind"), title: f.get("title"), body: f.get("body") || null, room_id: f.get("room_id") ? Number(f.get("room_id")) : null };
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
async function pageProfile() {
  const root = $("#profile");
  const username = root.dataset.username;
  let d;
  try { d = await api("GET", `/api/users/${encodeURIComponent(username)}`, undefined, { quiet: true }); }
  catch (_) { root.innerHTML = `<div class="panel"><h1>Пользователь не найден</h1></div>`; return; }
  const u = d.user;
  document.title = `@${u.username} — schematoz-bulboz.org`;
  const ST = { expert: "⚡ Эксперт", connoisseur: "Знаток", newbie: "Новичок" };
  root.innerHTML = `
    <div class="panel">
      <div class="profile-head"><span class="avatar lg">${initial(u.username)}</span>
        <div><h1>@${esc(u.username)}</h1><div class="level">Уровень ${u.level} · ${esc(u.level_name)}</div>${u.bio ? `<div class="muted">${esc(u.bio)}</div>` : ""}</div></div>
      <div class="stats">
        <div class="stat"><b>🔥 ${u.streak_days}</b><span>дней стрик</span></div>
        <div class="stat"><b>${u.reputation}</b><span>репутация</span></div>
        <div class="stat"><b>${d.stats.schemes}</b><span>схем</span></div>
        <div class="stat"><b>${d.stats.answers}</b><span>ответов</span></div>
      </div>
      <button class="btn btn-sm btn-ghost" id="share-profile">📤 Поделиться в сторис</button>
    </div>
    <div class="panel"><h2 style="margin-top:0">За что репутация</h2>
      ${d.topics.length ? d.topics.map((t) => `<div class="topic"><span class="st ${t.status}">${ST[t.status]}</span>
        <div>${t.room_slug ? `<a href="/r/${encodeURIComponent(t.room_slug)}">#${esc(t.title)}</a>` : esc(t.title)}</div>
        <div class="nums"><b>${t.schemes}</b> ${plural(t.schemes, "схема", "схемы", "схем")} · ${t.points} очк.<br>${t.plus} 👍 / ${t.minus} 👎</div></div>`).join("")
        : `<p class="muted">Пока нет оценённых ответов.</p>`}
      <p class="muted" style="font-size:13px">«Схема» — ответ, которому автор вопроса поставил +5. Эксперт в теме: 15+ схем и меньше 15% минусов.</p>
    </div>
    <div class="panel"><h2 style="margin-top:0">Бейджи</h2>
      ${d.badges.length ? `<div class="badges">${d.badges.map((b) => `<div class="badge"><div class="e">${esc(b.emoji)}</div><b>${esc(b.title)}</b><span>${esc(b.description)}</span></div>`).join("")}</div>` : `<p class="muted">Пока нет — ответь на пару вопросов 😉</p>`}
    </div>
    <div class="panel"><h2 style="margin-top:0">Лучшие ответы</h2>
      ${d.best_answers.length ? d.best_answers.map((b) => `<a class="best-item" href="/q/${b.question_id}#a${b.answer_id}"><b>${esc(b.question_title)}</b><small>${esc(b.body)}</small></a>`).join("") : `<p class="muted">Схем пока нет.</p>`}
    </div>`;
  $("#share-profile").onclick = () => shareDialog(`/api/share/user/${encodeURIComponent(u.username)}.png`, `/u/${encodeURIComponent(u.username)}`);
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
      panel.innerHTML = `<form class="panel form" id="cap-form"><p class="muted">Капча kremle-detect: задания ЕГЭ. Обязательна на входе и регистрации, а также при подозрительной активности.</p>
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
      const PAGES = { rules: "Правила сообщества", terms: "Пользовательское соглашение", privacy: "Политика конфиденциальности", requisites: "Реквизиты" };
      panel.innerHTML = `<select class="input" id="legal-slug">${Object.entries(PAGES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
        <div id="legal-editor" style="margin-top:12px"></div>`;
      const load = async () => {
        const slug = $("#legal-slug").value;
        const [page, versions] = await Promise.all([api("GET", `/api/legal/${slug}`), api("GET", `/admin/legal/${slug}/versions`)]);
        $("#legal-editor").innerHTML = `<form class="form" id="legal-form">
          <label>Заголовок<input name="title" value="${esc(page.title)}"></label>
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

// ---------------------------------------------------------------- boot
const PAGES = {
  feed: () => initFeed(), room: pageRoom, question: pageQuestion, ask: pageAsk, rooms: pageRooms,
  profile: pageProfile, login: pageAuth, register: pageAuth, banned: pageBanned, mod: pageMod, admin: pageAdmin,
};

(async function boot() {
  initHeader();
  await loadMe();
  const fn = PAGES[document.body.dataset.page];
  if (fn) fn();
})();
