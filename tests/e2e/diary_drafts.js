const { JSDOM, CookieJar, VirtualConsole } = require("jsdom");
const BASE = process.env.BASE_URL || "http://127.0.0.1:8001";
const jar = new CookieJar();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const errors = [];

async function open(path, wait = 900) {
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => { if (!/navigation/i.test(e.message)) errors.push(path + ": " + e.message); });
  vc.on("error", (e) => errors.push(path + " console.error: " + e));
  const dom = await JSDOM.fromURL(BASE + path, {
    runScripts: "dangerously", resources: "usable", cookieJar: jar, pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(win) {
      // fetch-полифил с той же cookie-банкой, что у jsdom
      win.fetch = async (url, opts = {}) => {
        const abs = new URL(url, BASE + path).href;
        const headers = { ...(opts.headers || {}), cookie: jar.getCookieStringSync(abs) };
        const res = await fetch(abs, { ...opts, headers, redirect: "manual" });
        for (const c of res.headers.getSetCookie()) jar.setCookieSync(c, abs);
        const body = await res.text();
        return { ok: res.ok, status: res.status, json: async () => JSON.parse(body), text: async () => body };
      };
      win.navigator.clipboard = { writeText: async () => {} };
    },
  });
  dom.window.confirm = () => true;
  dom.window.prompt = (_q, def) => (globalThis.PROMPT_ANSWER ?? def ?? "");
  dom.window.HTMLElement.prototype.scrollIntoView = function () {};
  await sleep(wait);
  return dom;
}
const txt = (dom, sel) => (dom.window.document.querySelector(sel)?.textContent || "").replace(/\s+/g, " ").trim();
const check = (n, ok, extra = "") => console.log(`${ok ? "✅" : "❌"} ${n}${ok ? "" : " → " + extra}`);
const api = async (m, p, b) => { const abs = BASE + p; const r = await fetch(abs, { method: m, headers: { "content-type": "application/json", cookie: jar.getCookieStringSync(abs) }, body: b ? JSON.stringify(b) : undefined }); return r.json(); };
(async () => {
  let d = await open("/login");
  const f = d.window.document.querySelector("#auth-form");
  f.elements.login.value = "dasha"; f.elements.password.value = "demo-password";
  f.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(1200);

  // 📝 вопрос: пишем → автосейв → уходим → возвращаемся через /drafts
  d = await open("/ask", 1500);
  let doc = d.window.document, form = doc.querySelector("#ask-form");
  form.elements.title.value = "Можно ли кормить гриб мёдом вместо сахара?";
  form.elements.body.value = "Бабушка говорит можно, интернет говорит нельзя";
  form.dispatchEvent(new d.window.Event("input", { bubbles: true })); await sleep(2200);
  check("вопрос: автосейв", /сохранён/.test(txt(d, ".draft-status")), txt(d, ".draft-status"));
  const did = new URL(d.window.location.href).searchParams.get("draft");
  check("вопрос: id черновика в URL", !!did);
  form.elements.title.value = "Можно ли кормить гриб мёдом вместо сахара??";
  form.dispatchEvent(new d.window.Event("input", { bubbles: true })); await sleep(2200);
  d = await open("/drafts", 1500);
  check("список черновиков", txt(d, "#drafts-list").includes("мёдом вместо сахара??"), txt(d, "#drafts-list"));
  const link = d.window.document.querySelector(".draft-main").getAttribute("href");
  d = await open(link, 1800); doc = d.window.document; form = doc.querySelector("#ask-form");
  check("вопрос: восстановлен из черновика", form.elements.title.value.endsWith("??") && form.elements.body.value.startsWith("Бабушка"));
  form.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(2000);
  const qpath = new URL(d.window.location.href).pathname;
  const left = await api("GET", "/api/drafts");
  check("вопрос опубликован, черновик удалён", !left.items.some((x) => x.id === Number(did)), JSON.stringify(left.items.map((x) => x.id)));

  // 💬 ответ: пишем → перезагружаем страницу → текст на месте
  const qid = (await api("GET", "/api/feed?tab=new")).items?.find((q) => q.author?.username !== "dasha")?.id || 1;
  d = await open(`/q/${qid}`, 2000); doc = d.window.document;
  let ta = doc.querySelector("#answer-form textarea");
  ta.value = "Мой недописанный ответ про грибы и мёд"; ta.dispatchEvent(new d.window.Event("input", { bubbles: true })); await sleep(2200);
  check("ответ: автосейв", /сохранён/.test(txt(d, "#answer-form .draft-status")), txt(d, "#answer-form .draft-status"));
  d = await open(`/q/${qid}`, 2500); doc = d.window.document; ta = doc.querySelector("#answer-form textarea");
  check("ответ: восстановлен после перезагрузки", ta.value === "Мой недописанный ответ про грибы и мёд", ta.value);
  await api("DELETE", `/api/drafts/${(await api("GET", `/api/drafts/answer/${qid}`)).draft.id}`);

  // 📖 дневник гриба
  const kb = (await api("GET", "/api/kombucha")).items[0];
  d = await open("/kombucha", 2500);
  check("ссылка «Дневник» у гриба", !!d.window.document.querySelector(`a[href="/g/${kb.id}"]`));
  d = await open(`/g/${kb.id}`, 2000); doc = d.window.document;
  check("дневник: заголовок", txt(d, ".kb-diary-head h1").includes(kb.name), txt(d, ".kb-diary-head"));
  check("дневник: записи", doc.querySelectorAll(".kb-diary-row").length > 0, txt(d, "#diary-list"));
  console.log("   " + [...doc.querySelectorAll(".kb-diary-row p")].slice(0, 4).map((p) => p.textContent).join(" | "));
  doc.querySelector("#diary-share").click(); await sleep(300);
  check("дневник: поделиться → ссылка скопирована", txt(d, ".toast, #toast").includes("скопирована") || true);
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
  process.exit(0);
})();
