// E2E кооперативов (jsdom): создание клуба через диалог, вступление вторым участником,
// уход за Гриб-Танком, личный кулдаун, автособытие и пост в ленте.
// Скрипт идемпотентен: старые тестовые клубы расформировывает через админский PATCH.
const { JSDOM, CookieJar, VirtualConsole } = require("jsdom");
const BASE = process.env.BASE_URL || "http://127.0.0.1:8001";
const results = [];
const check = (name, ok, extra = "") => { results.push([name, !!ok, extra]); console.log(`${ok ? "✅" : "❌"} ${name}${extra && !ok ? ` — ${extra}` : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function loginJar(username, password) {
  const r = await fetch(BASE + "/api/auth/login", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ login: username, password }),
  });
  const jar = new CookieJar();
  for (const c of r.headers.getSetCookie()) jar.setCookieSync(c, BASE);
  return { jar, status: r.status };
}

const api = async (jar, method, path, body) => {
  const r = await fetch(BASE + path, {
    method, headers: { cookie: jar.getCookieStringSync(BASE), "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  let data = null;
  try { data = JSON.parse(text); } catch (_) {}
  return { status: r.status, data };
};

async function openPage({ jar, page }) {
  const vc = new VirtualConsole();
  const errors = [];
  vc.on("jsdomError", (e) => { if (!/navigation/i.test(e.message)) errors.push(e.message); });
  const dom = await JSDOM.fromURL(BASE + page, {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, cookieJar: jar,
    virtualConsole: vc,
    beforeParse(win) {
      win.matchMedia = (q) => ({ matches: false, media: q, onchange: null,
        addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false });
      win.confirm = () => true;
      win.alert = () => {};
      win.prompt = () => "ругательства";
      win.HTMLElement.prototype.scrollIntoView = function () {};
      win.fetch = async (url, opts = {}) => {
        const abs = new URL(url, BASE).href;
        const headers = { ...(opts.headers || {}), cookie: jar.getCookieStringSync(abs) };
        const res = await fetch(abs, { ...opts, headers, redirect: "manual" });
        for (const c of res.headers.getSetCookie()) jar.setCookieSync(c, abs);
        const text = await res.text();
        return { ok: res.ok, status: res.status, json: async () => JSON.parse(text), text: async () => text };
      };
    },
  });
  return { dom, errors };
}

(async () => {
  const dasha = await loginJar("dasha", "demo-password");
  const kotik = await loginJar("kotik_na_fizmate", "demo-password");
  const admin = await loginJar("admin", "admin-demo-2026");
  check("логин dasha / kotik / admin", [dasha, kotik, admin].every((x) => x.status === 200),
    [dasha, kotik, admin].map((x) => x.status).join("/"));

  const TAG = "ТЕСТ";
  // Демо-кошелёк: создание клуба стоит 500 $₽, иначе повторный прогон упрётся в баланс.
  for (const jar of [dasha.jar, kotik.jar]) {
    const g = await api(jar, "POST", "/api/clubs/dev/grant", { amount: 2000 });
    check(`демо-пополнение кошелька (${g.status})`, g.status === 200, JSON.stringify(g.data));
  }
  // Чистим прошлые прогоны: все клубы, где есть наши участники, уводим в музей.
  {
    const list = await api(admin.jar, "GET", "/admin/clubs");
    for (const c of (list.data?.items || [])) {
      if (c.status === "active" && /ТЕСТ|Тестовый|Мемный/.test(`${c.tag} ${c.name}`)) {
        await api(admin.jar, "PATCH", `/admin/clubs/${c.id}`, { disband: true, reason: "e2e: чистый прогон" });
      }
    }
    for (const jar of [dasha.jar, kotik.jar]) {
      const mine = await api(jar, "GET", "/api/clubs/mine");
      const mineId = mine.data?.club?.id;
      if (mineId) await api(admin.jar, "PATCH", `/admin/clubs/${mineId}`, { disband: true, reason: "e2e: чистый прогон" });
      // и снимаем кулдаун выхода, иначе повторный прогон не сможет вступить заново
      await api(jar, "POST", "/api/clubs/dev/reset", {});
    }
  }

  // 1. Создание клуба через диалог на /clubs.
  {
    const { dom, errors } = await openPage({ jar: dasha.jar, page: "/clubs" });
    const win = dom.window;
    await sleep(1500);
    check("страница клубов отрисована", /Грибные кооперативы/.test(win.document.querySelector("main")?.textContent || ""));
    check("ошибок jsdom при загрузке нет", errors.length === 0, errors.join("; "));
    win.document.querySelector("#clubs-create")?.click();
    await sleep(200);
    const name = win.document.querySelector("#nc-name");
    const tag = win.document.querySelector("#nc-tag");
    const wrap = win.document.querySelector(".nc-name-wrap");
    check("диалог основания открылся", !!name && !!tag);
    check("«ООО \"…\"» — фиксированные части вокруг поля имени",
      !!wrap && /ООО\s*"/.test(wrap.textContent || "") && /"\s*$/.test((wrap.textContent || "").trim()),
      wrap?.textContent);
    if (name && tag) {
      name.value = "Тестовый";   // игрок вписывает только имя — «ООО» и кавычки подставит сервер
      tag.value = TAG;
      win.document.querySelector("#nc-emblem").value = "🍄";
      win.document.querySelector("#nc-save")?.click();
      await sleep(1800);
      const club = await api(dasha.jar, "GET", `/api/clubs/${encodeURIComponent(TAG)}`);
      check("клуб создан через UI (есть на /c/ТЕСТ)", club.status === 200 && club.data.name === 'ООО "Тестовый"', `status=${club.status}`);
      check("создатель — глава клуба", club.data?.me?.role === "leader", JSON.stringify(club.data?.me));
      check("имя обёрнуто в ООО \"…\" и тег [ЧАЙ]",
        club.data?.name === 'ООО "Тестовый"' && club.data?.tag === TAG, club.data?.name);
      check("в шапке клуба название без лишних кавычек",
        !/«ООО/.test(win.document.querySelector(".tk-hero-head h1")?.textContent || ""),
        win.document.querySelector(".tk-hero-head h1")?.textContent);
    }
    dom.window.close();
  }

  // 2. Вступление вторым участником + тег клуба у ника.
  {
    const { dom } = await openPage({ jar: kotik.jar, page: `/c/${encodeURIComponent(TAG)}` });
    const win = dom.window;
    await sleep(1500);
    const joinBtn = win.document.querySelector("#club-join");
    check("кнопка «Вступить» видна незамужнему участнику", !!joinBtn);
    joinBtn?.click();
    await sleep(1800);
    const club = await api(kotik.jar, "GET", `/api/clubs/${encodeURIComponent(TAG)}`);
    check("второй участник в клубе", club.data?.me?.member === true && club.data?.me?.role === "member", JSON.stringify(club.data?.me));
    check("участников стало двое", club.data?.members === 2, String(club.data?.members));
    dom.window.close();
  }

  // 3. Тег клуба у ника в шапке (на новой странице после вступления).
  {
    const { dom } = await openPage({ jar: kotik.jar, page: "/" });
    const win = dom.window;
    await sleep(2000);
    const name = win.document.querySelector("#me-name");
    check("тег клуба появился у ника", /\[ТЕСТ\]/.test(name?.textContent || ""), name?.textContent);
    dom.window.close();
  }

  // 4. Уход за Танком: сахар + личный кулдаун.
  {
    const { dom } = await openPage({ jar: dasha.jar, page: `/c/${encodeURIComponent(TAG)}` });
    const win = dom.window;
    await sleep(1500);
    const before = (await api(dasha.jar, "GET", `/api/clubs/${encodeURIComponent(TAG)}`)).data.tank;
    const sugar = win.document.querySelector('[data-tk="sugar"]');
    check("кнопки ухода доступны участнику", !!sugar && !sugar.disabled);
    sugar?.click();
    await sleep(1800);
    const after = (await api(dasha.jar, "GET", `/api/clubs/${encodeURIComponent(TAG)}`)).data.tank;
    check("сахар добавился Танку", after.stats.sweet > before.stats.sweet, `${before.stats.sweet} → ${after.stats.sweet}`);
    check("опыт Танка вырос", after.xp > before.xp, `${before.xp} → ${after.xp}`);
    const btn = win.document.querySelector('[data-tk="sugar"]');
    check("личный кулдаун: кнопка сахара заблокирована", btn?.disabled === true);
    check("норма дня видна в интерфейсе", /Норма дня/.test(win.document.querySelector(".tk-notes")?.textContent || ""));
    dom.window.close();
  }

  // 5. Лента: автособытие создания + пост участника + реакция.
  {
    const { dom } = await openPage({ jar: kotik.jar, page: `/c/${encodeURIComponent(TAG)}` });
    const win = dom.window;
    await sleep(1800);
    const feedText = win.document.querySelector("#club-feed")?.textContent || "";
    check("лента показывает автособытия клуба", /Кооператив/.test(feedText) && /вступил/i.test(feedText), feedText.slice(0, 120));
    const input = win.document.querySelector("#cf-text");
    check("участник может написать в ленту", !!input);
    if (input) {
      input.value = "Мы кормим Танк по расписанию 🍄";
      win.document.querySelector("#cf-send")?.click();
      await sleep(1800);
      const feed2 = win.document.querySelector("#club-feed")?.textContent || "";
      check("пост появился в ленте", /Мы кормим Танк/.test(feed2));
      const react = win.document.querySelector('[data-post-react][data-emoji="🔥"]');
      react?.click();
      await sleep(1500);
      const f = await api(kotik.jar, "GET", `/api/clubs/${encodeURIComponent(TAG)}/feed`);
      const post = (f.data?.items || []).find((p) => /Мы кормим Танк/.test(p.body || ""));
      check("реакция сохранилась", post?.reactions?.["🔥"] === 1, JSON.stringify(post?.reactions || {}));
    }
    dom.window.close();
  }

  // 6. Админка: вкладка «Клубы» видит клуб и дебаг Танка работает.
  {
    const { dom } = await openPage({ jar: admin.jar, page: "/admin?tab=clubs" });
    const win = dom.window;
    await sleep(2200);
    const panel = win.document.querySelector("#panel")?.textContent || "";
    check("админская вкладка «Клубы» открылась", /клубов|Клубы/i.test(panel), panel.slice(0, 100));
    const club = (await api(dasha.jar, "GET", `/api/clubs/${encodeURIComponent(TAG)}`)).data;
    const patched = await api(admin.jar, "PATCH", `/admin/clubs/${club.id}`, { tank: { stats: { sweet: 33 } } });
    check("админский дебаг Танка меняет показатели", patched.status === 200 && patched.data?.changed?.sweet === 33,
      JSON.stringify(patched.data));
    const after = (await api(dasha.jar, "GET", `/api/clubs/${encodeURIComponent(TAG)}`)).data.tank;
    check("новые показатели видны клубу", after.stats.sweet === 33, String(after.stats.sweet));
    dom.window.close();
  }

  const failed = results.filter(([, ok]) => !ok);
  console.log(`\n${results.length - failed.length}/${results.length} проверок пройдено`);
  process.exit(failed.length ? 1 : 0);
})();
