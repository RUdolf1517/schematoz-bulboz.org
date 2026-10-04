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
  // поддельный AudioContext: записываем каждый пузырь (время старта, частоты, длина)
  const log = []; const T0 = Date.now();
  const param = () => { const p = { v: [], setValueAtTime(x) { p.v.push(x); }, exponentialRampToValueAtTime(x) { p.v.push(x); }, value: 0 }; return p; };
  const node = () => ({ connect(n) { return n; } });
  w.AudioContext = class { constructor() { this.state = "running"; this.destination = node(); }
    get currentTime() { return (Date.now() - T0) / 1000; }
    createOscillator() { const o = { ...node(), type: "", frequency: param(), start(at) { o.at = at; }, stop(at) { log.push({ at: o.at, dur: at - o.at, f: o.frequency.v, type: o.type }); } }; return o; }
    createGain() { return { ...node(), gain: param() }; }
    createBiquadFilter() { return { ...node(), frequency: param(), type: "" }; } resume() {} };
  const of = w.fetch.bind(w); const last = {};
  w.fetch = async (...a) => { const r = await of(...a); const u = String(a[0]);
    if (/\/game\/|meditate/.test(u)) { const txt = await r.text(); try { last[u.split("/").slice(-2).join("/")] = JSON.parse(txt); } catch (_) {}
      return { ok: r.ok, status: r.status, headers: r.headers, json: async () => JSON.parse(txt), text: async () => txt }; } return r; };
  const openGame = async (code) => { await sleep(800); doc.querySelector("[data-games]").click(); await sleep(1200); doc.querySelector(`[data-game="${code}"]`).click(); await sleep(1500); };

  // 🧠 память: 2 шага, слушаем бульки
  await openGame("memory");
  check("кнопка звука есть", !!doc.querySelector(".kb-med-snd"));
  let seq = last["memory/start"].seq;
  await sleep(700 + seq.length * 600 + 300);
  const n0 = log.length;
  check("показ цепочки: короткие бульки", n0 >= 2 && log.every((x) => x.dur < 0.2), JSON.stringify(log.slice(0, 2)));
  const pads = doc.querySelectorAll("[data-pad]"); pads[seq[0]].click(); await sleep(1000);
  check("тап по банке — бульк", log.length > n0);
  seq = last["memory/step"].seq;
  await sleep(700 + seq.length * 600 + 300);
  const byPad = {}; log.forEach((x) => (byPad[Math.round(x.f[0])] = 1));
  console.log(`   коротких пузырей: ${log.length}, разных стартовых частот: ${Object.keys(byPad).length}`);
  doc.querySelector(".kb-med-snd").click(); await sleep(200);
  const muted = log.length; doc.querySelectorAll("[data-pad]")[seq[0]].click(); await sleep(300);
  check("🔇 — тишина", log.length === muted && w.localStorage.getItem("kb-mute") === "1");
  doc.querySelector(".kb-med-snd").click(); await sleep(200);
  doc.querySelector(".kb-med-x").click(); await sleep(500);

  // 🧘 медитация: протяжные бульки ровно в такт
  const L0 = log.length;
  await openGame("meditation");
  const M = last["meditate/start"];
  const tStart = (Date.now() - T0) / 1000;
  await sleep(M.length + 2500);
  const med = log.slice(L0).filter((x) => x.dur > 0.5);       // главные тоны (длинные)
  const main = med.filter((x) => x.type === "sine");
  check("медитация: протяжный бульк на каждый удар", main.length === M.beats.length, `${main.length} из ${M.beats.length}`);
  check("медитация: бульки длинные (≈1 с)", main.every((x) => x.dur > 0.9));
  const gaps = main.slice(1).map((x, i) => Math.round((x.at - main[i].at) * 1000));
  const want = M.beats.slice(1).map((b, i) => b - M.beats[i]);
  const drift = Math.max(...gaps.map((g, i) => Math.abs(g - want[i])));
  check("медитация: интервалы совпадают с ритмом (±30 мс)", drift <= 30, `drift ${drift} мс`);
  console.log(`   ${M.bpm} уд/мин, протяжных бульков: ${main.length}, макс. расхождение интервалов: ${drift} мс`);
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
  process.exit(0);
})();
