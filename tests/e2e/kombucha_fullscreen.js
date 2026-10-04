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
(async () => {
  let d = await open("/login");
  const f = d.window.document.querySelector("#auth-form");
  f.elements.login.value = "dasha"; f.elements.password.value = "demo-password";
  f.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(1200);
  d = await open("/kombucha", 2000);
  const doc = d.window.document;
  const say0 = txt(d, "#kb-say");
  check("облачко — фраза от первого лица", say0.length > 3 && !/Как говорил|процитировал/.test(say0), say0);
  console.log("   облачко:", say0);
  doc.querySelector('[data-act="talk"]').click(); await sleep(1500);
  const say1 = txt(d, "#kb-say");
  check("«Поговорить» — гриб говорит сам", !/процитировал|Как говорил/.test(say1) && !doc.querySelector(".kb-quote"), say1);
  console.log("   после «Поговорить»:", say1, "| автор в подсказке:", doc.querySelector("#kb-say").title);
  doc.querySelector("[data-fs]").click(); await sleep(300);
  const fs = doc.querySelector(".kb-fs");
  check("во весь экран: открылся", !!fs && !!fs.querySelector(".kb-fs-art svg"));
  check("во весь экран: интерфейс скрыт", doc.body.classList.contains("kb-fs-on"));
  check("во весь экран: свои id (нет дублей clipPath)", !!fs.querySelector('clipPath[id^="kb-jar-fs"]'));
  doc.dispatchEvent(new d.window.KeyboardEvent("keydown", { key: "Escape" })); await sleep(200);
  check("Esc — выход", !doc.querySelector(".kb-fs") && !doc.body.classList.contains("kb-fs-on"));
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
})();
