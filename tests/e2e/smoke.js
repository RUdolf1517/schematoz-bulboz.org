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
function check(name, cond, extra = "") { console.log((cond ? "✅" : "❌") + " " + name + (extra ? "  — " + extra : "")); if (!cond) process.exitCode = 1; }

(async () => {
  // 1. Гость: лендинг с топом грибов
  let d = await open("/", 1500);
  check("лендинг: гриб нарисован и есть топ", !!d.window.document.querySelector("#home-art svg") && d.window.document.querySelectorAll("#home-top .kb-card, #home-top li, #home-top a").length > 0, txt(d, "#home-top").slice(0, 80));
  check("шапка: Войти, Рынок, без Q&A", !!d.window.document.querySelector("#login-btn") && !!d.window.document.querySelector('.main-nav a[href="/market"]') && !d.window.document.querySelector('a[href="/ask"], a[href="/rooms"], a[href="/debates"]'));
  check("футер", txt(d, ".site-footer").includes("разработано RUdolf1517") && txt(d, ".site-footer").includes("СукИнЭндСын"));

  // 2. Вход
  d = await open("/login?next=/market");
  check("логин: демо-аккаунты показаны", txt(d, ".demo-box").includes("admin-demo-2026"));
  const f = d.window.document.querySelector("#auth-form");
  check("логин: форма видна без капчи", f && !f.hidden && !d.window.document.querySelector("#captcha-step"));
  f.elements.login.value = "dasha"; f.elements.password.value = "demo-password";
  f.dispatchEvent(new d.window.Event("submit", { cancelable: true }));
  await sleep(900);

  // 3. Настройки профиля
  d = await open("/settings", 1500);
  let sf = d.window.document.querySelector("#settings-form");
  check("настройки: форма загрузилась", !!sf.querySelector("[name=theme]") && !!sf.querySelector("[name=pinned_kombucha_id]") && !sf.querySelector("[name=wall_closed]"));
  sf.querySelector('[name=theme][value="neon"]').click();
  sf.elements.status_text.value = "ращу легенду";
  const pin = sf.querySelector("[name=pinned_kombucha_id] option:nth-child(2)");
  if (pin) sf.elements.pinned_kombucha_id.value = pin.value;
  sf.dispatchEvent(new d.window.Event("input", { bubbles: true }));
  check("настройки: превью обновилось", !!d.window.document.querySelector("#preview .theme-neon") && txt(d, "#preview").includes("ращу легенду"));
  check("настройки: превью закреплённого гриба", !pin || !!d.window.document.querySelector("#preview .pinned-kb svg"));
  sf.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(900);
  d = await open("/u/dasha", 1500);
  check("профиль: тема и статус применились", !!d.window.document.querySelector(".profile-skin.theme-neon") && txt(d, ".status-line") === "ращу легенду");
  check("профиль: грибная статистика и подоконник", txt(d, ".stats").includes("мутаций") && d.window.document.querySelectorAll(".kb-shelf .kb-card").length >= 1);
  check("профиль: без стены и репутации", !d.window.document.querySelector("#wall") && !txt(d, "main").includes("репутация"));
  d = await open("/faq");
  const fq = d.window.document.querySelector("#faq-search");
  check("FAQ: есть вопросы", d.window.document.querySelectorAll(".faq-item").length > 2);
  fq.value = "zzzнетничего"; fq.dispatchEvent(new d.window.Event("input"));
  check("FAQ: поиск прячет всё и показывает заглушку", !d.window.document.querySelector("#faq-empty").hidden);

  // 4. Чайный гриб на главной
  d = await open("/", 1500);
  check("гриб: банка нарисована", !!d.window.document.querySelector(".kb-main .kb-svg"));
  check("гриб: пункт «Мой гриб» активен", !!d.window.document.querySelector('.main-nav a[href="/"].active'));
  d.window.document.querySelector('[data-act="tea"]').click(); await sleep(900);
  check("гриб: заварка долита, кнопка на кулдауне", d.window.document.querySelector('[data-act="tea"]')?.disabled === true);
  check("гриб: банки, коллекция из 240 мутаций по стадиям, таймер 12 ч", !!d.window.document.querySelector(".kb-jar-tab.active") && d.window.document.querySelectorAll(".kb-cx").length === 240 && d.window.document.querySelectorAll(".kb-cx-stage").length === 6 && txt(d, ".kb-next").includes("12 часов"));
  check("гриб: в шапке баланс $₽", !d.window.document.querySelector("#wood-chip").hidden && Number(txt(d, "#wood-balance")) > 0);
  d.window.document.querySelector("[data-freeze]").click(); await sleep(1200);
  check("гриб: заморожен, есть кнопки продать и обменять", !!d.window.document.querySelector(".kb-svg.frozen") && !!d.window.document.querySelector("[data-list]") && !!d.window.document.querySelector("[data-trade]"));
  globalThis.PROMPT_ANSWER = "777";
  d.window.document.querySelector("[data-list]").click(); await sleep(1200);
  globalThis.PROMPT_ANSWER = undefined;
  check("гриб: выставлен на продажу", txt(d, "[data-unlist]").includes("777"));
  d = await open("/market", 3000);
  check("рынок: мой гриб на витрине", txt(d, "#mk-list").includes("777") && txt(d, "#mk-list").includes("твой") && txt(d, "#mk-trades").includes("Входящие"));
  d = await open("/u/dasha", 1800);
  check("профиль: гриб на полке с ценой", d.window.document.querySelectorAll("#shelf-list .kb-card").length === 1 && txt(d, "#shelf-list").includes("777"));
  d = await open("/", 1500);
  d.window.document.querySelector("[data-unlist]").click(); await sleep(900);
  d.window.document.querySelector("[data-unfreeze]").click(); await sleep(1200);
  check("гриб: снят с продажи и разморожен", !d.window.document.querySelector(".kb-svg.frozen") && !!d.window.document.querySelector(".kb-actions"));
  d = await open("/wallet", 1500);
  const reasons = txt(d, "#w-rules");
  check("кошелёк: баланс, история, правила без Q&A", txt(d, "#w-balance").endsWith("$₽") && d.window.document.querySelectorAll(".wallet-row").length > 0 && !/вопрос|ответ|стен|задани/i.test(reasons), reasons.slice(0, 120));
  d = await open("/notifications", 1200);
  check("уведомления открываются", !!d.window.document.querySelector("#notifications"));
  for (const p of ["/q/1", "/ask", "/rooms", "/tasks"]) {
    const r = await fetch(BASE + p, { redirect: "manual" });
    check(`Q&A-страница ${p} удалена`, r.status === 404);
  }
  d = await open("/mod");
  check("юзеру панель модерации закрыта", txt(d, "main").includes("Нет доступа"));

  // 5. Админ
  d.window.document.querySelector("#logout-btn").click(); await sleep(700);
  d = await open("/login");
  const f2 = d.window.document.querySelector("#auth-form");
  f2.elements.login.value = "admin"; f2.elements.password.value = "admin-demo-2026";
  f2.dispatchEvent(new d.window.Event("submit", { cancelable: true }));
  await sleep(900);
  d = await open("/", 1200);
  check("админ: пункты меню", !d.window.document.querySelector("#me-admin").hidden && !d.window.document.querySelector("#me-mod").hidden);
  d = await open("/mod", 1300);
  const mq = d.window.document.querySelector("#mod-q");
  mq.value = "kotik"; mq.dispatchEvent(new d.window.Event("input")); await sleep(1300);
  check("мод-панель: поиск игрока", txt(d, "#mod-users").includes("@kotik"));
  globalThis.PROMPT_ANSWER = undefined;
  d.window.document.querySelector("[data-ban]").click(); await sleep(300);
  const bf = d.window.document.querySelector("#ban-form");
  bf.elements.reason.value = "автокликер в «Мушках»";
  bf.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(1500);
  check("мод-панель: бан выдан", txt(d, "#mod-users").includes("автокликер"));
  d.window.document.querySelector("[data-lift]").click(); await sleep(1500);
  check("мод-панель: бан снят", !!d.window.document.querySelector("[data-ban]"));
  d.window.document.querySelector('[data-tab="appeals"]').click(); await sleep(900);
  check("апелляции открываются", txt(d, "#panel").includes("Апелляций нет"));
  d = await open("/admin", 1200);
  check("админка: грибная аналитика", txt(d, "#panel").includes("Живых грибов"));
  for (const tab of ["users", "captcha", "legal", "modlog", "kombucha"]) {
    d.window.document.querySelector(`[data-tab="${tab}"]`).click(); await sleep(1200);
    check(`админка: вкладка ${tab}`, !txt(d, "#panel").includes("Не удалось") && !txt(d, "#panel").includes("Загружаем"), txt(d, "#panel").slice(0, 60));
  }
  d.window.document.querySelector('[data-tab="modlog"]').click(); await sleep(1000);
  check("лог: бан и снятие записаны", txt(d, "#panel").includes("ban.issue") && txt(d, "#panel").includes("ban.lift"));
  check("вкладок фич и комнат нет", !d.window.document.querySelector('[data-tab="features"], [data-tab="rooms"]'));
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
  if (errors.length) process.exitCode = 1;
})();
