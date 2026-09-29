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
  const w = d.window, doc = w.document;
  // перехват: как только придёт ритм, тапаем точно в такт
  const of = w.fetch.bind(w);
  let track = null;
  w.fetch = async (...a) => {
    const r = await of(...a);
    if (String(a[0]).includes("/meditate/start")) {
      const txt = await r.text(); const j = JSON.parse(txt); track = j;
      const t0 = Date.now();
      j.beats.forEach((b) => setTimeout(() => doc.querySelector(".kb-med")?.dispatchEvent(new w.Event("pointerdown", { bubbles: true })), b + 10));
      return { ok: r.ok, status: r.status, headers: r.headers, json: async () => JSON.parse(txt), text: async () => txt };
    }
    return r;
  };
  await sleep(1500); const btn = doc.querySelector("[data-meditate]");
  check("кнопка «Медитация гриба» есть", !!btn);
  doc.querySelector("[data-meditate]").click(); await sleep(2500); console.log("   toast:", doc.querySelector(".toast")?.textContent || "-");
  check("открылся экран медитации, интерфейс скрыт", !!doc.querySelector(".kb-med") && doc.body.classList.contains("kb-med-on"));
  check("ритм пришёл с сервера", track && track.beats.length === 24, JSON.stringify(track)?.slice(0, 80));
  if (!track) { console.log(errors.join("\n")); return; }
  console.log(`   трек: «${track.title}», ${track.bpm} уд/мин, ${(track.length / 1000).toFixed(1)} с`);
  await sleep(track.length + 2500);
  const res = doc.querySelector(".kb-med-result");
  check("результат показан", !!res, doc.querySelector(".kb-med")?.textContent.slice(0, 200));
  if (res) console.log("   " + res.textContent.replace(/\s+/g, " ").trim());
  res?.querySelector("[data-close]").click(); await sleep(300);
  check("закрылось, интерфейс вернулся", !doc.querySelector(".kb-med") && !doc.body.classList.contains("kb-med-on"));
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
})();
