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
const cyr = (t) => { const l = [...t].filter((c) => /\p{L}/u.test(c)); return l.length && l.filter((c) => /[а-яё]/i.test(c)).length * 2 >= l.length; };
(async () => {
  let d = await open("/login");
  const f = d.window.document.querySelector("#auth-form");
  f.elements.login.value = "dasha"; f.elements.password.value = "demo-password";
  f.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(1200);
  d = await open("/kombucha", 2000);
  const doc = d.window.document;
  check("облачко при загрузке — цитата", txt(d, "#kb-say").startsWith("Как говорил"), txt(d, "#kb-say"));
  for (const a of ["tea", "clean", "pet", "sugar"]) {
    doc.querySelector(`[data-act="${a}"]`).click(); await sleep(1500);
    const say = txt(d, "#kb-say"), mood = doc.querySelector(".kb-mood")?.className || "";
    const ok = mood.includes("sticky") ? !say.startsWith("Как говорил") : say.startsWith("Как говорил");
    check(`облачко после «${a}» — ${mood.includes("sticky") ? "сахарная кома" : "цитата"}, по-русски`, ok && cyr(say), say);
  }
  doc.querySelector('[data-act="talk"]').click(); await sleep(1500);
  check("«Поговорить» — цитата философа по-русски", cyr(txt(d, ".kb-quote")), txt(d, ".kb-quote"));
  const muts = doc.querySelector("details.kb-muts-box");
  check("мутации на грибе свёрнуты (или их ещё нет)", !muts || !muts.open);
  const cx = doc.querySelector("details.kb-codex-box");
  check("коллекция свёрнута, стадии тоже сворачиваются", !cx.open && doc.querySelectorAll("details.kb-cx-stage-box").length === 6);
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
})();
