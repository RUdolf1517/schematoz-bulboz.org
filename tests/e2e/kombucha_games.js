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
  d = await open("/kombucha", 2500);
  const w = d.window, doc = w.document;
  const of = w.fetch.bind(w); const last = {};
  w.fetch = async (...a) => {
    const r = await of(...a); const u = String(a[0]);
    if (/\/game\/|\/games/.test(u)) { const txt = await r.text(); try { last[u.split("/").slice(-2).join("/")] = JSON.parse(txt); } catch (_) {}
      return { ok: r.ok, status: r.status, headers: r.headers, json: async () => JSON.parse(txt), text: async () => txt }; }
    return r;
  };
  const openGame = async (code) => {
    await sleep(800); doc.querySelector("[data-games]").click(); await sleep(1200);
    const card = doc.querySelector(`[data-game="${code}"]`); card.click(); await sleep(1500);
  };
  const result = async (name, maxMs) => {
    const t = Date.now(); while (!doc.querySelector(".kb-med-result") && Date.now() - t < maxMs) await sleep(300);
    const res = doc.querySelector(".kb-med-result");
    check(`${name}: результат`, !!res, doc.querySelector(".kb-game")?.textContent.slice(0, 160));
    if (res) { console.log("   " + res.textContent.replace(/\s+/g, " ").replace("Готово", "").trim()); res.querySelector("[data-close]").click(); await sleep(500); }
    check(`${name}: закрылась`, !doc.querySelector(".kb-game") && !doc.body.classList.contains("kb-med-on"));
  };
  // меню
  doc.querySelector("[data-games]").click(); await sleep(1200);
  check("меню: 5 игр", doc.querySelectorAll("[data-game]").length === 5);
  doc.querySelector("#modal").click(); await sleep(400);             // клик по фону закрывает меню
  check("меню закрывается", doc.querySelector("#modal").hidden);

  // 🫖 налей: ищем идеальный момент по тем же формулам (тряска метки + пульс струи + пена)
  await openGame("pour");
  const P = last["pour/start"];
  check("налей: старт, 6 раундов с помехами", !!P && P.rounds.length === 6 && P.rounds[5].mods.length === 4, JSON.stringify(P?.rounds.map((r) => r.mods)));
  const lv = (rd, ms) => { const t = ms / 1000; let l = rd.rate * t + rd.accel * t * t; if (rd.pulse) l += rd.rate * rd.pulse.p * (Math.sin(rd.pulse.w * t - Math.PI / 2) + 1) / rd.pulse.w; return l; };
  const tg = (rd, ms) => rd.shake ? rd.target + rd.shake.amp * Math.sin(2 * Math.PI * ms / rd.shake.period + rd.shake.phase) : rd.target;
  let sawDark = false, sawMods = 0;
  for (const rd of P.rounds) {
    let best = 0, be = 9;
    for (let ms = 0; ms < 8000; ms += 2) { if (lv(rd, ms) >= 1) break; const e = Math.abs(lv(rd, ms) * (1 + (rd.foam?.f || 0)) - tg(rd, ms)); if (e < be) { be = e; best = ms; } }
    sawMods += doc.querySelectorAll(".kb-pour-mod").length === rd.mods.length ? 1 : 0;
    const g = doc.querySelector(".kb-game");
    g.dispatchEvent(new w.Event("pointerdown", { bubbles: true }));
    if (rd.dark && best > rd.dark.at + 150) { await sleep(rd.dark.at + 100); sawDark ||= !!doc.querySelector(".kb-pour-dark.on") || true; await sleep(best - rd.dark.at - 100); }
    else await sleep(best);
    g.dispatchEvent(new w.Event("pointerup", { bubbles: true })); await sleep(1500);
  }
  check("налей: плашки помех показаны", sawMods === 6);
  await result("налей", 8000);

  // 🧠 память: 3 верных шага, потом ошибка
  await openGame("memory");
  let seq = last["memory/start"].seq;
  for (let step = 0; step < 4; step++) {
    await sleep(700 + seq.length * 600 + 400);
    const pads = doc.querySelectorAll("[data-pad]");
    const inp = step < 3 ? seq : [...seq.slice(0, -1), (seq[seq.length - 1] + 1) % 4];
    for (const p of inp) { pads[p].click(); await sleep(150); }
    await sleep(900);
    if (step < 3) seq = last["memory/step"].seq;
  }
  await result("память", 8000);

  // 🍬 сахар: тапаем только сахар
  await openGame("sugar");
  const L = last["sugar/start"].length; const t0 = Date.now();
  while (Date.now() - t0 < L + 500) { doc.querySelectorAll(".kb-drop").forEach((b) => { if (b.textContent === "🍬") b.dispatchEvent(new w.Event("pointerdown", { bubbles: true })); }); await sleep(150); }
  await result("сахар", 8000);

  // 🪰 мушки: сбиваем всех
  await openGame("flies");
  const FL = last["flies/start"].length; const t1 = Date.now();
  while (Date.now() - t1 < FL + 500 && !doc.querySelector(".kb-med-result")) { doc.querySelectorAll(".kb-fly:not(.swat)").forEach((b) => b.dispatchEvent(new w.Event("pointerdown", { bubbles: true }))); await sleep(150); }
  await result("мушки", 8000);
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
  process.exit(0);
})();
