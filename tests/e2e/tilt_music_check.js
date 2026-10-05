// Точечная jsdom-проверка мобильного наклона: автозапуск, fallback-кнопка, iOS-разрешение.
const { JSDOM, CookieJar, VirtualConsole } = require("jsdom");
const BASE = process.env.BASE_URL || "http://127.0.0.1:8001";
const results = [];
const check = (name, ok, extra = "") => { results.push([name, !!ok, extra]); console.log(`${ok ? "✅" : "❌"} ${name}${extra && !ok ? ` — ${extra}` : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function loginJar() {
  const r = await fetch(BASE + "/api/auth/login", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ login: "dasha", password: "demo-password" }),
  });
  const jar = new CookieJar();
  for (const c of r.headers.getSetCookie()) jar.setCookieSync(c, BASE);
  return { jar, status: r.status };
}

async function openMobile({ requestPermission = null, jar } = {}) {
  const vc = new VirtualConsole();
  const errors = [];
  vc.on("jsdomError", (e) => { if (!/navigation/i.test(e.message)) errors.push(e.message); });
  const dom = await JSDOM.fromURL(BASE + "/", {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, cookieJar: jar,
    virtualConsole: vc,
    beforeParse(win) {
      win.matchMedia = (q) => ({
        matches: /pointer: coarse|hover: none|max-width/.test(q),
        media: q, onchange: null,
        addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false,
      });
      class DOE extends win.Event {}
      if (requestPermission) DOE.requestPermission = requestPermission;
      win.DeviceOrientationEvent = DOE;
      win.confirm = () => true;
      win.fetch = async (url, opts = {}) => {
        const abs = new URL(url, BASE).href;
        const headers = { ...(opts.headers || {}), cookie: jar?.getCookieStringSync(abs) || "" };
        const res = await fetch(abs, { ...opts, headers, redirect: "manual" });
        for (const c of res.headers.getSetCookie()) jar?.setCookieSync(c, abs);
        const body = await res.text();
        return { ok: res.ok, status: res.status, json: async () => JSON.parse(body), text: async () => body };
      };
    },
  });
  return { dom, errors };
}

const fireOrientation = (win, gamma) => {
  const e = new win.Event("deviceorientation");
  Object.defineProperty(e, "gamma", { value: gamma });
  win.dispatchEvent(e);
};

(async () => {
  const { jar, status } = await loginJar();
  check("логин демо-пользователя", status === 200, `status=${status}`);

  // --- 1. Android: датчик доступен без requestPermission → наклон включается сам ---
  {
    const { dom } = await openMobile({ jar });
    const win = dom.window;
    await sleep(1200);                       // страница отрисовалась, авто-включение уже сработало
    fireOrientation(win, 14);                // телефон прислал показания сразу
    await sleep(1500);                       // больше 1200 мс: проверка «датчик молчит» уже прошла
    const btn = win.document.querySelector(".kb-main [data-tilt]");
    const surface = win.document.querySelector(".kb-main .kb-liquid-surface");
    check("Android: кнопка наклона есть", !!btn);
    check("Android: наклон включился сам, без нажатия", btn?.getAttribute("aria-pressed") === "true");
    check("Android: датчик управляет жидкостью", surface?.getAttribute("transform")?.startsWith("rotate(-14 110 "),
      surface?.getAttribute("transform"));
    dom.window.close();
  }

  // --- 2. Android без показаний датчика → кнопка остаётся (fallback) ---
  {
    const { dom } = await openMobile({ jar });
    const win = dom.window;
    await sleep(3000);                       // показаний не было
    const btn = win.document.querySelector(".kb-main [data-tilt]");
    check("Android без датчика: кнопка осталась и не активна", !!btn && btn.getAttribute("aria-pressed") === "false");
    check("Android без датчика: подсказка про палец/наклон", /наклон/i.test(btn?.title || ""), btn?.title);
    dom.window.close();
  }

  // --- 3. iOS: requestPermission обязателен → кнопка, автозапуска нет ---
  {
    const { dom } = await openMobile({ jar, requestPermission: async () => "granted" });
    const win = dom.window;
    await sleep(1600);
    const btn = win.document.querySelector(".kb-main [data-tilt]");
    check("iOS: автозапуска нет, кнопка есть", !!btn && btn.getAttribute("aria-pressed") === "false");
    btn?.click();
    await sleep(200);
    check("iOS: после разрешения наклон включился", btn?.getAttribute("aria-pressed") === "true");
    fireOrientation(win, -9);
    const surface = win.document.querySelector(".kb-main .kb-liquid-surface");
    check("iOS: датчик управляет жидкостью", surface?.getAttribute("transform")?.startsWith("rotate(9 110 "), surface?.getAttribute("transform"));
    dom.window.close();
  }

  // --- 4. iOS с отказом в разрешении → подсказка про палец, без «наклон недоступен» ---
  {
    const { dom } = await openMobile({ jar, requestPermission: async () => "denied" });
    const win = dom.window;
    await sleep(1200);
    const btn = win.document.querySelector(".kb-main [data-tilt]");
    btn?.click();
    await sleep(300);
    const scene = win.document.querySelector(".kb-main .kb-scene");
    check("iOS отказ: подсказка «проведи пальцем»", /пальцем/i.test(btn?.title || ""), btn?.title);
    check("iOS отказ: нет сообщения «наклон недоступен»", !/наклон недоступен/i.test(scene?.textContent || ""));
    dom.window.close();
  }

  // --- 5. Музыки нигде нет ---
  {
    const { dom } = await openMobile({ jar });
    const html = dom.window.document.body.innerHTML + dom.window.document.head.innerHTML;
    check("нет кнопки «Выключить музыку»", !/Выключить музыку/i.test(html) && !/data-spooky-music/.test(html));
    check("нет звукового синтезатора музыки", !/spookyMusic/i.test((await fetch(BASE + "/static/app.js")).text()));
    dom.window.close();
  }

  const failed = results.filter(([, ok]) => !ok);
  console.log(`\n${results.length - failed.length}/${results.length} проверок пройдено`);
  process.exit(failed.length ? 1 : 0);
})();
