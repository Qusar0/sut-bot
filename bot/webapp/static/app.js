"use strict";
const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) { tg.ready(); tg.expand(); }

const INIT = tg ? tg.initData : "";
const KIND = { lecture: "ЛЕКЦИЯ", practice: "ПРАКТИКА", lab: "ЛАБОРАТОРНАЯ" };
const $ = (id) => document.getElementById(id);
const view = $("view"), strip = $("strip");

let state = { tab: "day", date: null, me: null };

async function api(path, opts = {}) {
  const headers = { "X-Telegram-Init-Data": INIT, ...(opts.headers || {}) };
  if (opts.body) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 409) throw { code: "no_group" };
  if (r.status === 403) throw { code: "no_consent" };
  if (!r.ok) throw { code: "error", status: r.status };
  return r.json();
}

function esc(s) { return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function spin() { view.innerHTML = '<div class="spin">Загрузка…</div>'; }
function lessonCard(l) {
  const meta = [l.room && "ауд. " + l.room, l.teachers].filter(Boolean).map(esc).join(" · ");
  return `<div class="card ${l.kind_key}"><div class="time">${esc(l.pair)} пара · ${l.start}–${l.end}</div>
    <div class="tag ${l.kind_key}">${KIND[l.kind_key] || esc(l.kind)}</div>
    <div class="subj">${esc(l.subject)}</div>${meta ? `<div class="meta">${meta}</div>` : ""}</div>`;
}

// --- экраны ---

async function showDay() {
  spin();
  try {
    const d = await api("/api/day" + (state.date ? "?date=" + state.date : ""));
    state.date = d.date;
    $("h-title").textContent = d.title;
    $("h-sub").textContent = d.week_label;
    strip.innerHTML = '<div class="strip">' + d.strip.map((x) =>
      `<div class="d ${x.active ? "active" : ""} ${x.count ? "" : "empty"}" data-date="${x.date}">
        <small>${x.weekday}</small><b>${x.day}</b><div class="dot"></div></div>`).join("") + "</div>";
    strip.querySelectorAll(".d").forEach((el) => el.onclick = () => { state.date = el.dataset.date; showDay(); });
    view.innerHTML = d.lessons.length ? d.lessons.map(lessonCard).join("") : '<div class="empty">Пар нет 🎉</div>';
  } catch (e) { handle(e); }
}

async function showWeek() {
  spin(); strip.innerHTML = "";
  try {
    const w = await api("/api/week" + (state.date ? "?date=" + state.date : ""));
    $("h-title").textContent = "Неделя";
    $("h-sub").textContent = w.week_label;
    const nav = `<div class="seg"><button data-d="${w.prev}">← раньше</button><button data-d="${w.next}">позже →</button></div>`;
    view.innerHTML = nav + w.days.map((day) =>
      `<div class="daytitle">${esc(day.title)}</div>` +
      (day.lessons.length ? day.lessons.map(lessonCard).join("") : '<div class="note">пар нет</div>')).join("");
    view.querySelectorAll(".seg button").forEach((b) => b.onclick = () => { state.date = b.dataset.d; showWeek(); });
  } catch (e) { handle(e); }
}

async function showSubjects() {
  spin(); strip.innerHTML = "";
  $("h-title").textContent = "Предметы"; $("h-sub").textContent = "текущий семестр";
  try {
    const d = await api("/api/subjects");
    view.innerHTML = d.subjects.map((s) => {
      const pct = s.total ? Math.round(100 * s.passed / s.total) : 0;
      return `<div class="row" data-name="${esc(s.name)}"><div style="flex:1">
        <div>${esc(s.name)}</div><div class="bar"><i style="width:${pct}%"></i></div></div>
        <div class="prog">${s.passed}/${s.total}</div></div>`;
    }).join("") || '<div class="empty">Нет данных</div>';
    view.querySelectorAll(".row").forEach((r) => r.onclick = () => showSubject(r.dataset.name));
  } catch (e) { handle(e); }
}

async function showSubject(name) {
  spin();
  try {
    const d = await api("/api/subject?name=" + encodeURIComponent(name));
    $("h-title").textContent = name;
    $("h-sub").textContent = d.teachers.join(", ");
    backButton(showSubjects);
    const kinds = d.by_kind.map((k) => `<span class="pill">${KIND[k.kind_key]}: ${k.passed}/${k.total}</span>`).join("");
    const rows = d.lessons.map((l) =>
      `<div class="card ${l.kind_key}" style="padding:8px 12px">
        <span class="time">${l.done ? "✅" : "▫️"} ${l.date.slice(8)}.${l.date.slice(5, 7)} · ${l.start}</span>
        <span class="tag ${l.kind_key}" style="margin-left:6px">${KIND[l.kind_key][0]}</span>
        ${l.room ? `<span class="meta"> · ${esc(l.room)}</span>` : ""}</div>`).join("");
    view.innerHTML = `<div class="note">Всего ${d.total} · прошло ${d.passed} · впереди ${d.total - d.passed}</div>
      <div>${kinds}</div>${rows}`;
  } catch (e) { handle(e); }
}

async function showSearch() {
  strip.innerHTML = ""; $("h-title").textContent = "Поиск"; $("h-sub").textContent = "преподаватель или аудитория";
  view.innerHTML = '<input id="q" placeholder="Фамилия или номер аудитории" autocomplete="off"><div id="res"></div>';
  const q = $("q"), res = $("res");
  q.focus();
  let timer;
  q.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (q.value.trim().length < 2) { res.innerHTML = ""; return; }
      try {
        const d = await api("/api/search?q=" + encodeURIComponent(q.value.trim()));
        res.innerHTML = d.teachers.map((t) => `<div class="row" data-k="teacher" data-id="${t.id}">👩‍🏫 ${esc(t.name)}</div>`).join("") +
          d.rooms.map((r) => `<div class="row" data-k="room" data-id="${r.id}">🚪 ${esc(r.name)}</div>`).join("") ||
          '<div class="note">Ничего не найдено</div>';
        res.querySelectorAll(".row").forEach((el) => el.onclick = () => showEntity(el.dataset.k, el.dataset.id));
      } catch (e) { handle(e); }
    }, 300);
  };
}

async function showEntity(kind, id, date) {
  spin();
  try {
    const d = await api(`/api/entity/${kind}/${id}` + (date ? "?date=" + date : ""));
    $("h-title").textContent = d.title; $("h-sub").textContent = "";
    backButton(showSearch);
    let profileBtn = "";
    if (kind === "teacher") profileBtn = `<div class="seg"><button id="prof">👤 Профиль преподавателя</button></div>`;
    const nav = `<div class="seg"><button data-d="${d.prev}">← неделя</button><button data-d="${d.next}">неделя →</button></div>`;
    const body = d.days.map((day) => `<div class="daytitle">${esc(day.title)}</div>` +
      (day.slots.length ? day.slots.map((s) => {
        const extra = [s.room, s.groups.join(", "), s.teachers].filter(Boolean).map(esc).join(" · ");
        return `<div class="card ${s.kind_key}" style="padding:8px 12px"><span class="time">${s.start}</span>
          <span class="subj" style="display:inline"> ${esc(s.subject)}</span><div class="meta">${extra}</div></div>`;
      }).join("") : '<div class="note">занятий нет</div>')).join("");
    view.innerHTML = profileBtn + nav + (d.partial ? '<div class="note">Полное расписание только на текущую и следующую неделю.</div>' : "") + body;
    view.querySelectorAll(".seg button[data-d]").forEach((b) => b.onclick = () => showEntity(kind, id, b.dataset.d));
    if (kind === "teacher") $("prof").onclick = () => showProfile(id);
  } catch (e) { handle(e); }
}

async function showProfile(id) {
  spin();
  try {
    const p = await api(`/api/teacher/${id}/profile`);
    backButton(() => showEntity("teacher", id));
    if (!p.found) { view.innerHTML = `<div class="empty">На сайте sut.ru нет страницы этого преподавателя.</div>`; return; }
    $("h-title").textContent = p.name; $("h-sub").textContent = p.position;
    const contacts = Object.entries(p.contacts).map(([k, v]) => `<div class="meta">${esc(k)}: ${esc(v)}</div>`).join("");
    const interests = p.interests.length ? `<div class="note">Научные интересы: ${esc(p.interests.join(", "))}</div>` : "";
    view.innerHTML = (p.photo ? `<img class="avatar" src="${esc(p.photo)}">` : "") +
      `<div class="subj">${esc(p.name)}</div><div class="note">${esc(p.position)}</div>${contacts}${interests}` +
      (p.education ? `<div class="note">Образование: ${esc(p.education)}</div>` : "") +
      `<p><a href="${esc(p.url)}" target="_blank">Страница на sut.ru</a></p>`;
  } catch (e) { handle(e); }
}

async function showSettings() {
  spin(); strip.innerHTML = "";
  $("h-title").textContent = "Настройки"; $("h-sub").textContent = state.me.group ? state.me.group.name : "";
  const s = state.me.settings;
  const toggles = [
    ["notify_tomorrow", "Расписание на завтра"],
    ["notify_week", "Расписание на неделю"],
    ["notify_changes", "Изменения в расписании"],
    ["morning_digest", "Утренняя сводка"],
    ["quiet_hours", "Тихие часы (ночью без звука)"],
  ];
  const lkBtn = `<div class="row" id="lk-open"><span>🏛 Личный кабинет</span><span class="prog">оценки, отметка →</span></div>`;
  view.innerHTML = lkBtn + toggles.map(([f, t]) =>
    `<div class="toggle"><span>${t}</span><div class="sw ${s[f] ? "on" : ""}" data-f="${f}"><i></i></div></div>`).join("") +
    `<div class="toggle"><span>Напоминание перед парой</span><select id="rm" style="width:auto">
      ${[0, 5, 10, 15, 30].map((m) => `<option value="${m}" ${s.remind_minutes === m ? "selected" : ""}>${m ? m + " мин" : "выкл"}</option>`).join("")}</select></div>
    <div class="note">Группа: ${state.me.group ? esc(state.me.group.name) : "не выбрана"} — <a id="chg">сменить</a></div>`;
  view.querySelectorAll(".sw").forEach((sw) => sw.onclick = async () => {
    const f = sw.dataset.f; s[f] = !s[f]; sw.classList.toggle("on");
    await api("/api/settings", { method: "POST", body: JSON.stringify({ [f]: s[f] }) });
    if (tg) tg.HapticFeedback.selectionChanged();
  });
  $("rm").onchange = async (e) => { s.remind_minutes = +e.target.value; await api("/api/settings", { method: "POST", body: JSON.stringify({ remind_minutes: s.remind_minutes }) }); };
  $("chg").onclick = chooseGroup;
  $("lk-open").onclick = showLK;
}

// --- личный кабинет ---

const LK_SECTIONS = [
  ["diary", "📔 Дневник"], ["messages", "💬 Сообщения"], ["files", "📁 Файлы группы"],
  ["record_book", "📒 Зачётка"], ["debts", "⚠️ Задолженности"], ["rating", "🏆 Рейтинг"],
  ["scholarships", "💰 Стипендии"], ["orders", "📑 Приказы"], ["plan", "📚 Учебный план"],
];

async function showLK() {
  spin(); strip.innerHTML = ""; backButton(() => switchTab("settings"));
  $("h-title").textContent = "Личный кабинет"; $("h-sub").textContent = "lk.sut.ru";
  let st;
  try { st = await api("/api/lk/status"); } catch (e) { return handle(e); }
  if (!st.linked) { lkLinkForm(); return; }
  $("h-sub").textContent = st.fio + " · " + st.group;
  const warn = st.status === "auth_failed" ? '<div class="note">⚠️ Пароль не подошёл — переподключите кабинет.</div>' : "";
  const sections = LK_SECTIONS.map(([k, t]) => `<div class="row" data-sec="${k}">${t}</div>`).join("");
  view.innerHTML = warn +
    `<div class="row" id="lk-att"><span>✅ Отметиться на паре</span></div>` +
    `<div class="toggle"><span>Автоотметка <span class="note">(бот жмёт кнопку сам)</span></span>
       <div class="sw ${st.auto_attendance ? "on" : ""}" id="lk-auto"><i></i></div></div>` +
    sections +
    `<div class="row" id="lk-unlink"><span>🔌 Отключить кабинет</span></div>`;
  view.querySelectorAll("[data-sec]").forEach((r) => r.onclick = () => lkSection(r.dataset.sec, r.textContent));
  $("lk-att").onclick = lkAttendance;
  $("lk-unlink").onclick = async () => {
    if (tg && !(await new Promise((res) => tg.showConfirm("Отключить кабинет и удалить его данные?", res)))) return;
    await api("/api/lk/unlink", { method: "POST", body: "{}" }); showLK();
  };
  $("lk-auto").onclick = async (e) => {
    const sw = e.currentTarget, on = !sw.classList.contains("on");
    if (on && tg && !(await new Promise((res) => tg.showConfirm(
      "Включить автоотметку? Бот будет сам нажимать «Начать занятие». Ответственность за правила вуза о посещаемости на вас.", res)))) return;
    sw.classList.toggle("on", on);
    await api("/api/lk/auto", { method: "POST", body: JSON.stringify({ on }) });
  };
}

function lkLinkForm() {
  view.innerHTML = `<div class="note">Подключите lk.sut.ru — и в приложении будут оценки, сообщения, файлы, долги и отметка на паре. Пароль хранится в зашифрованном виде.</div>
    <input id="lk-login" placeholder="Логин (студенческий e-mail)" autocomplete="username">
    <input id="lk-pass" type="password" placeholder="Пароль" autocomplete="current-password" style="margin-top:8px">
    <div class="seg"><button id="lk-go">Подключить</button></div>
    <div class="note" id="lk-err"></div>`;
  $("lk-go").onclick = async () => {
    const login = $("lk-login").value.trim(), password = $("lk-pass").value;
    if (!login || !password) return;
    $("lk-go").textContent = "Проверяю…"; $("lk-err").textContent = "";
    try {
      const d = await api("/api/lk/link", { method: "POST", body: JSON.stringify({ login, password }) });
      if (d.ok) { showLK(); } else { $("lk-err").textContent = d.error; $("lk-go").textContent = "Подключить"; }
    } catch (e) { $("lk-err").textContent = "Не удалось подключить."; $("lk-go").textContent = "Подключить"; }
  };
}

async function lkSection(name, title) {
  spin(); backButton(showLK); $("h-title").textContent = title;
  try {
    const d = await api("/api/lk/section?name=" + name);
    view.innerHTML = `<div class="card" style="border:none">${d.html}</div>`;
  } catch (e) {
    view.innerHTML = e.code === "no_group" ? "" : '<div class="empty">Раздел недоступен.</div>';
  }
}

async function lkAttendance() {
  spin(); backButton(showLK); $("h-title").textContent = "Отметка на паре";
  try {
    const d = await api("/api/lk/attendance");
    if (!d.lessons.length) { view.innerHTML = '<div class="empty">Сегодня пар нет.</div>'; return; }
    view.innerHTML = '<div class="note">Кнопка активна за 10 минут до пары. Отметка — действие в ЛК от вашего имени.</div>' +
      d.lessons.map((l) => {
        const st = l.started ? "✅ отмечено" : l.ready ? "" : "⏳ рано";
        const btn = (!l.started && l.ready) ? `<button class="mk" data-rasp="${l.rasp}">Отметиться</button>` : `<span class="prog">${st}</span>`;
        return `<div class="row"><div><div>${esc(l.subject)}</div><div class="prog">${esc(l.time)} · ${esc(l.room)}</div></div>${btn}</div>`;
      }).join("");
    view.querySelectorAll(".mk").forEach((b) => b.onclick = async () => {
      b.textContent = "…"; b.disabled = true;
      try { await api("/api/lk/mark", { method: "POST", body: JSON.stringify({ rasp: b.dataset.rasp }) });
        if (tg) tg.HapticFeedback.notificationOccurred("success"); lkAttendance();
      } catch (e) { b.textContent = "Ошибка"; }
    });
  } catch (e) { view.innerHTML = '<div class="empty">Расписание ЛК недоступно.</div>'; }
}

async function chooseGroup() {
  spin(); backButton(showSettings);
  $("h-title").textContent = "Выбор группы";
  view.innerHTML = '<input id="gq" placeholder="Номер группы, напр. ИСТ-2633" autocomplete="off"><div id="gres"></div>';
  const gq = $("gq"), gres = $("gres"); gq.focus();
  let timer;
  gq.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const d = await api("/api/groups?q=" + encodeURIComponent(gq.value.trim()));
      gres.innerHTML = d.groups.map((g) => `<div class="row" data-id="${g.id}">${esc(g.name)} <span class="prog">${esc(g.faculty)}</span></div>`).join("");
      gres.querySelectorAll(".row").forEach((r) => r.onclick = async () => {
        await api("/api/group", { method: "POST", body: JSON.stringify({ group_id: +r.dataset.id }) });
        state.me = await api("/api/me"); state.date = null; switchTab("day");
      });
    }, 300);
  };
}

// --- навигация ---

function backButton(fn) {
  if (!tg) return;
  tg.BackButton.show();
  tg.BackButton.onClick(function h() { tg.BackButton.offClick(h); tg.BackButton.hide(); fn(); });
}

const TABS = { day: showDay, week: showWeek, subjects: showSubjects, search: showSearch, settings: showSettings };
function switchTab(tab) {
  state.tab = tab;
  if (tg) tg.BackButton.hide();
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  TABS[tab]();
}
document.querySelectorAll("nav button").forEach((b) => b.onclick = () => switchTab(b.dataset.tab));

function handle(e) {
  if (e.code === "no_group") { view.innerHTML = '<div class="empty">Сначала выберите группу.</div>'; chooseGroup(); return; }
  if (e.code === "no_consent") { view.innerHTML = '<div class="empty">Откройте бота и примите документы, затем вернитесь.</div>'; return; }
  view.innerHTML = '<div class="empty">Не удалось загрузить. Попробуйте позже.</div>';
}

(async () => {
  try {
    state.me = await api("/api/me");
    if (!state.me.consent) { view.innerHTML = '<div class="empty">Откройте бота командой /start и примите документы, затем вернитесь в приложение.</div>'; strip.innerHTML = ""; return; }
    if (!state.me.group) { chooseGroup(); return; }
    switchTab("day");
  } catch (e) { handle(e); }
})();
