// Точечные jsdom-проверки: мобильный наклон жидкости (автозапуск/фолбэк/iOS-разрешение),
// отсутствие кнопок музыки и аватар в меню (картинка вместо буквы + фолбэк на букву).
const { JSDOM, CookieJar, VirtualConsole } = require("jsdom");
const fs = require("fs");
const path = require("path");
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

async function openMobile({ requestPermission = null, jar, page = "/" } = {}) {
  const vc = new VirtualConsole();
  const errors = [];
  vc.on("jsdomError", (e) => { if (!/navigation/i.test(e.message)) errors.push(e.message); });
  const dom = await JSDOM.fromURL(BASE + page, {
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
      win.alert = () => {};
      win.HTMLElement.prototype.scrollIntoView = function () {};
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

  // --- 6. Аватар в меню: картинка вместо буквы + фолбэк на букву ---
  {
    // Тест можно запускать повторно: сначала снимаем аватар.
    await fetch(BASE + "/api/me/profile", {
      method: "PATCH",
      headers: { cookie: jar.getCookieStringSync(BASE), "content-type": "application/json" },
      body: JSON.stringify({ avatar_url: null, avatar_frame: "none" }),
    });

    // 6.1 Без аватара в шапке — буква ника (и никакой «сломанной» картинки).
    const { dom } = await openMobile({ jar });
    const win = dom.window;
    await sleep(1200);
    let el = win.document.querySelector("#me-avatar");
    check("меню без аватара: показана буква ника",
      !!el && !el.querySelector("img") && el.textContent.trim() === "D", el?.textContent);
    dom.window.close();

    // 6.2 Загружаем картинку и ставим её аватаром (как это делает «Настройки профиля»).
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX///+/v7+jQ3Y5AAAADklEQVQI12P4AIX8EAgALgAD/aNpbtEAAAAASUVORK5CYII=",
      "base64");
    const form = new FormData();
    form.append("file", new Blob([png], { type: "image/png" }), "avatar.png");
    const up = await fetch(BASE + "/api/uploads", {
      method: "POST", headers: { cookie: jar.getCookieStringSync(BASE) }, body: form,
    });
    const upJson = await up.json();
    check("аватар: картинка загружена", up.status === 201 && !!upJson.url, `status=${up.status}`);

    const patch = await fetch(BASE + "/api/me/profile", {
      method: "PATCH",
      headers: { cookie: jar.getCookieStringSync(BASE), "content-type": "application/json" },
      body: JSON.stringify({ avatar_url: upJson.url, avatar_frame: "neon" }),
    });
    const me = await fetch(BASE + "/api/auth/me", { headers: { cookie: jar.getCookieStringSync(BASE) } });
    const meJson = await me.json();
    check("аватар: /api/auth/me отдаёт avatar_url", patch.status === 200 && meJson.user.avatar_url === upJson.url,
      `patch=${patch.status} avatar=${meJson.user?.avatar_url}`);

    // 6.3 После перезагрузки страницы меню показывает картинку с рамкой.
    const second = await openMobile({ jar });
    const win2 = second.dom.window;
    await sleep(1500);
    el = win2.document.querySelector("#me-avatar");
    const img = el?.querySelector("img");
    check("меню с аватаром: показана картинка, а не буква", !!img);
    check("меню с аватаром: тот же файл", img?.getAttribute("src") === upJson.url, img?.getAttribute("src"));
    check("меню с аватаром: применена рамка профиля", el?.classList.contains("frame-neon"), el?.className);

    // 6.4 Файл пропал (удалён/битый URL) — вместо «сломанной» картинки возвращается буква.
    const mediaName = path.basename(upJson.url);
    const mediaPath = path.join(process.cwd(), "..", "..", "var", "uploads", mediaName);
    try { fs.unlinkSync(mediaPath); } catch (_) {}
    let fallback = null;
    try {
      win2.eval(`typeof paintAvatar === "function" && paintAvatar(document.querySelector("#me-avatar"), ${JSON.stringify({ username: "dasha", avatar_url: upJson.url })});`);
      const broken = win2.document.querySelector("#me-avatar img");
      broken?.dispatchEvent(new win2.Event("error"));
      const el2 = win2.document.querySelector("#me-avatar");
      fallback = !!el2 && !el2.querySelector("img") && el2.textContent.trim() === "D";
    } catch (e) { fallback = false; }
    check("меню: битая картинка → буква, без «сломанной» иконки", fallback,
      win2.document.querySelector("#me-avatar")?.innerHTML);
    second.dom.window.close();
  }

  // --- 7. Настройки профиля: сменил аватар → шапка обновилась без перезагрузки ---
  {
    const { dom } = await openMobile({ jar, page: "/settings" });
    const win = dom.window;
    await sleep(2000);   // страница настроек подгружает профиль и превью
    const input = win.document.querySelector("#av-file");
    check("настройки: поле загрузки аватара есть", !!input);

    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX///+/v7+jQ3Y5AAAADklEQVQI12P4AIX8EAgALgAD/aNpbtEAAAAASUVORK5CYII=",
      "base64");
    const file = new win.File([png], "new-avatar.png", { type: "image/png" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input.dispatchEvent(new win.Event("change", { bubbles: true }));
    await sleep(1500);
    check("настройки: после выбора файла превью показывает картинку",
      !!win.document.querySelector("#av-prev img"));

    const form = win.document.querySelector("#settings-form");
    form.dispatchEvent(new win.Event("submit", { bubbles: true, cancelable: true }));
    await sleep(1500);
    const head = win.document.querySelector("#me-avatar img");
    check("настройки: шапка показывает новый аватар сразу, без перезагрузки", !!head,
      win.document.querySelector("#me-avatar")?.innerHTML);
    check("настройки: тот же файл, что в превью",
      head?.getAttribute("src") === win.document.querySelector("#av-prev img")?.getAttribute("src"),
      `${head?.getAttribute("src")} vs ${win.document.querySelector("#av-prev img")?.getAttribute("src")}`);
    dom.window.close();
  }

  const failed = results.filter(([, ok]) => !ok);
  console.log(`\n${results.length - failed.length}/${results.length} проверок пройдено`);
  process.exit(failed.length ? 1 : 0);
})();
