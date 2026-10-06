// Точечные jsdom-проверки: мобильный наклон жидкости (автозапуск/фолбэк/iOS-разрешение),
// отсутствие кнопок музыки, аватар в меню (картинка вместо буквы + фолбэк на букву)
// и «идеальный коридор» показателей гриба (зелёные зоны, плашка, множитель опыта).
// Секция коридора сама задаёт состояние гриба dasha через админский PATCH — можно запускать на любой базе.
const { JSDOM, CookieJar, VirtualConsole } = require("jsdom");
const fs = require("fs");
const path = require("path");
const BASE = process.env.BASE_URL || "http://127.0.0.1:8001";
const results = [];
const check = (name, ok, extra = "") => { results.push([name, !!ok, extra]); console.log(`${ok ? "✅" : "❌"} ${name}${extra && !ok ? ` — ${extra}` : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function loginJar(username = "dasha", password = "demo-password") {
  const r = await fetch(BASE + "/api/auth/login", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ login: username, password }),
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

  // --- 8. Коридор показателей: зелёные зоны, плашка, множитель опыта ---
  {
    // Состояние гриба dasha задаём сами (админский PATCH заодно снимает кулдауны) — проверки детерминированы.
    const admin = await loginJar("admin", "admin-demo-2026");
    check("коридор: админ вошёл для настройки состояния", admin.status === 200, `status=${admin.status}`);
    const dashaHeaders = { cookie: jar.getCookieStringSync(BASE) };
    const before = await (await fetch(BASE + "/api/kombucha", { headers: dashaHeaders })).json();
    const kid = before.items[0].id;
    const patch = async (stats) => {
      const r = await fetch(BASE + `/admin/kombucha/${kid}`, {
        method: "PATCH",
        headers: { cookie: admin.jar.getCookieStringSync(BASE), "content-type": "application/json" },
        body: JSON.stringify({ stats }),
      });
      return r.status;
    };
    check("коридор: админский PATCH состояния гриба", await patch({ sweet: 60, tea: 70, clean: 90, happy: 75 }) === 200);

    // 8.1 Контракт API: диапазоны и признак «в коридоре».
    const state = await (await fetch(BASE + "/api/kombucha", { headers: dashaHeaders })).json();
    const k = state.items[0];
    check("коридор: API отдаёт ranges/off/ok", k?.corridor?.ok === true && k?.corridor?.off.length === 0, JSON.stringify(k?.corridor));
    const wantRanges = { sweet: [55, 70], tea: [65, 85], clean: [80, 100], happy: [70, 100] };
    const gotRanges = k?.corridor?.ranges || {};
    check("коридор: диапазоны сахара 55–70, заварки 65–85, чистоты от 80, настроения от 70",
      Object.keys(wantRanges).every((key) => JSON.stringify(gotRanges[key]) === JSON.stringify(wantRanges[key])),
      JSON.stringify(gotRanges));
    check("коридор: надписи «показатели упадут через … раз в 12 часов» больше нет",
      !/Показатели упадут|раз в 12 часов/.test(await (await fetch(BASE + "/static/app.js")).text()));

    const { dom } = await openMobile({ jar });
    const win = dom.window;
    await sleep(1500);
    const toasts = [];
    const origToast = win.toast;
    win.toast = (msg, err) => { toasts.push(String(msg)); return origToast(msg, err); };

    // 8.2 На каждой полоске — зелёная подложка ровно по диапазону с сервера, оранжевых нет.
    const bars = [...win.document.querySelectorAll(".kb-stats .kb-bar")];
    const zones = bars.map((bar) => { const z = bar.querySelector(".kb-zone"); return z ? { left: z.style.left, width: z.style.width } : null; });
    check("коридор: зелёная зона на всех 4 полосках", zones.length === 4 && zones.every(Boolean), JSON.stringify(zones));
    check("коридор: зона сахара 55–70% ширины",
      zones[0]?.left === "55%" && zones[0]?.width === "15%", JSON.stringify(zones[0]));
    check("коридор: в коридоре оранжевых полосок нет", bars.every((b) => !b.classList.contains("off")));
    // 8.3 Плашка под показателями.
    const banner = win.document.querySelector(".kb-corridor");
    check("коридор: плашка подтверждает идеальный коридор и ×1",
      !!banner && /Идеальный коридор/.test(banner.textContent) && /×1\b/.test(banner.textContent), banner?.textContent);
    // 8.4 Тексты опыта.
    check("коридор: «+8 опыта» в коридоре", String(win.eval("xpLabel(8, 1)")) === "+8 опыта");
    check("коридор: «+4 опыта (×0.5 — вне коридора)» вне коридора",
      String(win.eval("xpLabel(4, 0.5)")) === "+4 опыта (×0.5 — вне коридора)");
    check("коридор: плашка называет «пересластил» при перекорме",
      /пересластил/.test(String(win.eval('corridorMarkup({ok:false,off:["sweet"],ranges:{sweet:[55,70]}},{sweet:95})'))));
    check("коридор: плашка называет «мало сахара» при недоборе",
      /мало сахара/.test(String(win.eval('corridorMarkup({ok:false,off:["sweet"],ranges:{sweet:[55,70]}},{sweet:40})'))));

    // 8.5 Живое действие вне коридора: сахар 60 -> 85, опыт 8 × 0.5 = 4.
    const sugar = win.document.querySelector('.kb-main [data-act="sugar"]');
    check("коридор: кнопка сахара доступна после сброса кулдаунов", !!sugar && !sugar.disabled);
    sugar?.click();
    await sleep(1200);
    check("коридор: тост после перекорма — «+4 опыта (×0.5 — вне коридора)»",
      toasts.includes("+4 опыта (×0.5 — вне коридора)"), JSON.stringify(toasts));
    const banner2 = win.document.querySelector(".kb-corridor");
    check("коридор: после перекорма плашка ругается и показывает ×0.5",
      /пересластил/.test(banner2?.textContent || "") && /×0\.5/.test(banner2?.textContent || ""), banner2?.textContent);
    const sugarBar = [...win.document.querySelectorAll(".kb-stats .kb-bar")][0];
    check("коридор: полоска сахара стала оранжевой", sugarBar?.classList.contains("off"));
    // 8.6 Возвращаем коридор и проверяем полный опыт: пет 2 × 1 = 2.
    check("коридор: возврат в коридор через админский PATCH", await patch({ sweet: 55, tea: 70, clean: 90, happy: 75 }) === 200);
    win.document.querySelector('.kb-main [data-act="pet"]')?.click();
    await sleep(1200);
    check("коридор: тост в коридоре — «+2 опыта»", toasts.includes("+2 опыта"), JSON.stringify(toasts));
    dom.window.close();

    // 8.7 Админская дебаг-панель показывает состояние коридора.
    const adm = await openMobile({ jar: admin.jar, page: "/admin?tab=kombucha" });
    await sleep(2500);
    const awin = adm.dom.window;
    const userForm = awin.document.querySelector("#kbd-user");        // пусто — «мои грибы»; открываем гриб dasha
    if (userForm) {
      userForm.elements.u.value = "dasha";
      userForm.dispatchEvent(new awin.Event("submit", { bubbles: true, cancelable: true }));
      await sleep(1800);
    }
    const panelText = awin.document.querySelector("#panel")?.textContent || "";
    check("коридор: админская панель мутаций видит состояние коридора",
      /коридоре/.test(panelText) && /×[01]/.test(panelText) && /Бульбоз|Медузий|Блинчик/.test(panelText),
      panelText.slice(0, 160));
    adm.dom.window.close();
  }

  const failed = results.filter(([, ok]) => !ok);
  console.log(`\n${results.length - failed.length}/${results.length} проверок пройдено`);
  process.exit(failed.length ? 1 : 0);
})();
