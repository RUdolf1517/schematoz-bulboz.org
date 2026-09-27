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
const check = (n, ok, extra = "") => console.log(`${ok ? "✅" : "❌"} ${n}${ok ? "" : " " + extra}`);
(async () => {
  let d = await open("/login");
  const f = d.window.document.querySelector("#auth-form");
  f.elements.login.value = "dasha"; f.elements.password.value = "demo-password";
  f.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(1200);
  d = await open("/kombucha", 2000);
  const doc = () => d.window.document;
  check("гриб: кнопки Погладить и Поговорить", txt(d, ".kb-actions").includes("Погладить") && !!doc().querySelector('[data-act="talk"]'));
  check("гриб: 240 мутаций", doc().querySelectorAll(".kb-cx").length === 240);
  doc().querySelector('[data-act="talk"]').click(); await sleep(1500);
  check("гриб: философская цитата", !!doc().querySelector(".kb-quote.philo cite") && txt(d, ".kb-quote").length > 20, txt(d, "#kb-say"));
  doc().querySelector('[data-act="pet"]').click(); await sleep(1500);
  check("гриб: цитата сомнительной личности", !!doc().querySelector(".kb-quote.dubious"), txt(d, "#kb-say"));
  check("гриб: блок деления раз в неделю", txt(d, ".kb-sprout").includes("раз в неделю"));
  doc().querySelector("[data-freeze]").click(); await sleep(1200);
  doc().querySelector("[data-trade]").click(); await sleep(400);
  check("подарок: поле подписи", !!doc().querySelector("#tr-msg"));
  d = await open("/market", 2500);
  d = await open("/u/dasha", 2500);
  doc().querySelector("#shelf-list .kb-card").click(); await sleep(1500);
  check("карточка гриба: мутации и история", txt(d, "#modal").includes("История владельцев"), txt(d, "#modal").slice(0, 80));
  d = await open("/tasks", 2000);
  check("задания: в шапке и форма", !!doc().querySelector('.main-nav a[href="/tasks"].active') && !!doc().querySelector("#task-form"));
  const tf = doc().querySelector("#task-form").elements;
  tf.title.value = "Придумай ник для гриба"; tf.body.value = "Нужен смешной ник для моего чайного гриба"; tf.reward.value = "5"; tf.slots.value = "1";
  doc().querySelector("#task-form").dispatchEvent(new d.window.Event("input", { bubbles: true }));
  check("задания: расчёт стоимости", txt(d, "#task-cost").includes("Спишется 6"), txt(d, "#task-cost"));
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
})();
