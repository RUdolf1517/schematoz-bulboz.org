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
  dom.window.HTMLElement.prototype.scrollIntoView = function () {};
  await sleep(wait);
  return dom;
}
const txt = (dom, sel) => (dom.window.document.querySelector(sel)?.textContent || "").replace(/\s+/g, " ").trim();
function check(name, cond, extra = "") { console.log((cond ? "✅" : "❌") + " " + name + (extra ? "  — " + extra : "")); if (!cond) process.exitCode = 1; }

(async () => {
  // 1. Лента анонимно: карточки, кнопка «Войти» в хедере
  let d = await open("/");
  const cards = d.window.document.querySelectorAll(".card[data-href]");
  check("лента: карточки есть", cards.length >= 5, cards.length + " шт.");
  check("хедер: кнопка «Войти»", txt(d, "#login-btn") === "Войти");
  check("карточка ведёт на вопрос", cards[0]?.dataset.href?.startsWith("/q/"), cards[0]?.dataset.href);
  check("лента: у карточек рейтинг", txt(d, ".card .q-rating").startsWith("★"));
  check("лента: обложка у вопроса", !!d.window.document.querySelector(".card-cover"));
  check("футер: ссылка на холивары после ленты", d.window.document.querySelector(".site-footer .footer-debates")?.getAttribute("href") === "/debates");
  check("футер", txt(d, ".credit").includes("разработано RUdolf1517 на основе технологий rudolfzinovev.xyz"));

  // 2. Страница вопроса анонимно
  d = await open("/q/1");
  check("вопрос: заголовок", txt(d, ".q-head h1").startsWith("Почему шарик"));
  check("вопрос: «Схема» первой", d.window.document.querySelector(".answer")?.classList.contains("best"));
  check("вопрос: призыв войти", txt(d, "#question").includes("Войди, чтобы ответить"));
  check("вопрос: markdown в ответе", !!d.window.document.querySelector(".answer .md strong"));
  check("вопрос: комментарии, модер первым", txt(d, ".answer .comment .c-meta").includes("@moder") && txt(d, ".urating.tier-mod") === "★∞");

  // 3. Вход сразу формой, без капчи
  d = await open("/login?next=/q/1");
  check("логин: демо-аккаунты показаны", txt(d, ".demo-box").includes("admin-demo-2026"));
  const f = d.window.document.querySelector("#auth-form");
  check("логин: форма видна без капчи", f && !f.hidden && !d.window.document.querySelector("#captcha-step"));
  f.elements.login.value = "dasha"; f.elements.password.value = "demo-password";
  f.dispatchEvent(new d.window.Event("submit", { cancelable: true }));
  await sleep(900);

  // 4. Даша — автор вопроса 1: видит кнопки +5/−1
  d = await open("/q/1");
  check("хедер: имя пользователя", txt(d, "#me-name") === "dasha");
  const voteVals = [...d.window.document.querySelectorAll("[data-vote]")].map((b) => b.dataset.vote);
  check("автор видит только +5 и −1", voteVals.length && voteVals.every((v) => v === "5" || v === "-1"), voteVals.join(","));
  check("подсказка автору", txt(d, ".author-hint").includes("+5"));
  // переголосуем «ну это гравитация лол»: снимаем −1 (повторный клик) и ставим +5
  let second = d.window.document.querySelectorAll(".answer")[1];
  second.querySelector('[data-vote="-1"]').click(); await sleep(900);
  d = await open("/q/1");
  second = d.window.document.querySelectorAll(".answer")[1];
  check("повторный клик снимает голос", !second.querySelector(".on-down"), txt(d, ".answer:nth-of-type(2) .score"));

  // 4б. Комментарий к ответу и апвоут вопроса
  const cf = d.window.document.querySelector(".comment-form");
  cf.elements.body.value = "**огонь**, спасибо";
  cf.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(1000);
  check("комментарий опубликован с markdown", [...d.window.document.querySelectorAll(".comment .md strong")].some((x) => x.textContent === "огонь"));
  check("свой вопрос — голосовать нельзя", !d.window.document.querySelector("[data-qvote]"));
  d = await open("/q/4");
  const before = txt(d, ".q-vote .score");
  d.window.document.querySelector('[data-qvote="1"]').click(); await sleep(1000);
  check("апвоут вопроса поднимает рейтинг", txt(d, ".q-vote .score") !== before && !!d.window.document.querySelector('[data-qvote="1"].on-up'), before + " → " + txt(d, ".q-vote .score"));
  d = await open("/ask");
  check("юзер не может создать холивар", d.window.document.querySelector("#debate-opt").disabled);
  check("форма вопроса: обложка и markdown-панель", !!d.window.document.querySelector("#cover-input") && !!d.window.document.querySelector(".md-toolbar"));
  d = await open("/debates");
  check("страница холиваров", d.window.document.querySelector('[data-tab="debates"]').classList.contains("active") && txt(d, "#feed").includes("Шаверма"));

  // 5. Даша отвечает на чужой вопрос (q4) — у неё там ±1
  d = await open("/q/4");
  const vals4 = [...d.window.document.querySelectorAll("[data-vote]")].map((b) => b.dataset.vote);
  check("не-автор видит только +1 и −1", vals4.every((v) => v === "1" || v === "-1"), vals4.join(","));
  const af = d.window.document.querySelector("#answer-form");
  af.elements.body.value = "Карточки + таймлайн, и каждый день по 20 минут.";
  af.dispatchEvent(new d.window.Event("submit", { cancelable: true }));
  await sleep(1200);
  check("ответ опубликован", txt(d, "#question").includes("Карточки + таймлайн"));

  // 5б. Редактирование своего ответа
  d = await open("/q/4");
  const mine = [...d.window.document.querySelectorAll("[data-edit-a]")];
  check("свой ответ: кнопки изменить/удалить", mine.length === 1);
  mine[0].click(); await sleep(200);
  const ef = d.window.document.querySelector("#edit-form");
  ef.elements.body.value = "Карточки + таймлайн, 20 минут в день. UPD: и пробники!";
  ef.dispatchEvent(new d.window.Event("submit", { cancelable: true })); await sleep(1000);
  check("ответ изменён, пометка «изменено»", txt(d, "#question").includes("UPD: и пробники") && txt(d, "#question").includes("изменено"));

  // 5в. Поиск и подписка
  d = await open("/search?q=шарик", 1200);
  check("поиск находит вопрос", txt(d, "#search-results").includes("Почему шарик"));
  d = await open("/u/kotik_na_fizmate");
  const fbtn = d.window.document.querySelector("#follow-btn");
  check("кнопка подписки", txt(d, "#follow-btn") === "Подписаться");
  fbtn.click(); await sleep(900);
  check("подписка оформлена", txt(d, "#follow-btn") === "Отписаться");
  d = await open("/");
  d.window.document.querySelector('[data-tab="following"]').click(); await sleep(900);
  check("вкладка «Подписки»", d.window.document.querySelectorAll("#feed .card[data-href]").length >= 1);
  d = await open("/notifications");
  check("страница уведомлений", !!d.window.document.querySelector("#read-all"));

  // 6. Холивар: голос за сторону
  d = await open("/q/2");
  d.window.document.querySelector('[data-side="b"]').click(); await sleep(900);
  d = await open("/q/2");
  check("холивар: голос засчитан", d.window.document.querySelector('[data-side="b"]').classList.contains("mine"), txt(d, ".debate-bar .bar"));

  // 7. Профиль, комнаты
  d = await open("/u/kotik_na_fizmate");
  check("профиль: бейджи", txt(d, "#profile").includes("Рабочая схема"));
  check("профиль: темы репутации", txt(d, "#profile").includes("ЕГЭ Физика"));
  d = await open("/rooms");
  const joinBtn = d.window.document.querySelector('[data-join="genshin"]');
  joinBtn.click(); await sleep(800);
  d = await open("/?");
  d.window.document.querySelector('[data-tab="my_rooms"]').click(); await sleep(900);
  check("вкладка «Мои комнаты»", txt(d, "#feed").includes("Genshin"), txt(d, "#feed").slice(0, 80));
  d = await open("/mod");
  check("юзеру панель модерации закрыта", txt(d, "main").includes("Нет доступа"));

  // 8. Выход и вход админом
  d.window.document.querySelector("#logout-btn").click(); await sleep(700);
  d = await open("/login");
  const f2 = d.window.document.querySelector("#auth-form");
  f2.elements.login.value = "admin"; f2.elements.password.value = "admin-demo-2026";
  f2.dispatchEvent(new d.window.Event("submit", { cancelable: true }));
  await sleep(900);
  d = await open("/");
  d = await open("/ask");
  check("админ может создать холивар", !d.window.document.querySelector("#debate-opt").disabled);
  check("админ: пункты меню", !d.window.document.querySelector("#me-admin").hidden && !d.window.document.querySelector("#me-mod").hidden);
  d = await open("/mod", 1300);
  check("мод-панель: жалоба на спам в очереди", txt(d, "#panel").includes("free-genshin-gems"));
  d.window.document.querySelector('[data-act="hide"]').click(); await sleep(1200);
  check("жалоба закрыта скрытием", !txt(d, "#panel").includes("free-genshin-gems"));
  d.window.document.querySelector('[data-tab="appeals"]').click(); await sleep(900);
  check("свою апелляцию админ не видит", txt(d, "#panel").includes("Апелляций нет"));
  d = await open("/admin", 1200);
  check("админка: аналитика", txt(d, "#panel").includes("Всего юзеров"));
  for (const tab of ["users", "captcha", "features", "legal", "rooms", "modlog"]) {
    d.window.document.querySelector(`[data-tab="${tab}"]`).click(); await sleep(900);
    check(`админка: вкладка ${tab}`, !txt(d, "#panel").includes("Не удалось") && !txt(d, "#panel").includes("Загружаем"), txt(d, "#panel").slice(0, 60));
  }
  check("лог: действие модерации записано", txt(d, "#panel").includes("content.hide"));
  console.log(errors.length ? "JS errors:\n" + errors.join("\n") : "JS errors: none");
  if (errors.length) process.exitCode = 1;
})();
