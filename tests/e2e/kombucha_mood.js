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
  const doc = d.window.document;
  const face = doc.querySelector(".kb-main .kb-face");
  check("лицо на диске (не над ним) и масштабировано", /scale\(/.test(face.getAttribute("transform")), face.getAttribute("transform"));
  check("значок настроения на банке", !!doc.querySelector(".kb-main .kb-mood-badge text"));
  check("подпись настроения", txt(d, ".kb-mood").length > 3, txt(d, ".kb-mood"));
  check("облачко — цитата", (txt(d, "#kb-say").length > 3 && !/Как говорил|процитировал/.test(txt(d, "#kb-say"))), txt(d, "#kb-say"));
  const cx = doc.querySelector("details.kb-codex-box");
  check("коллекция свёрнута по умолчанию", cx && !cx.open);
  cx.querySelector("summary").click(); await sleep(200);
  check("коллекция разворачивается", cx.open && d.window.localStorage.getItem("fold:kb-codex") === "1");
  check("деление: только на последней стадии", /делится только на последней стадии|Деление \d/\d/.test(txt(d, ".kb-main")));
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
})();
