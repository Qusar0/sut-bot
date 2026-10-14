"use strict";
const tg = window.Telegram ? window.Telegram.WebApp : null;
// часть методов WebApp есть не во всех клиентах (старый Telegram Desktop) — не роняем из-за них весь скрипт
if (tg) { try { tg.ready(); } catch (_) {} try { tg.expand(); } catch (_) {} }

const INIT = tg ? tg.initData : "";
const KIND = { lecture: "ЛЕКЦИЯ", practice: "ПРАКТИКА", lab: "ЛАБОРАТОРНАЯ" };
const $ = (id) => document.getElementById(id);
const view = $("view"), strip = $("strip");

let state = { tab: "home", date: null, me: null };

// свайп влево/вправо на экране дня = листание дней
let _swipeX = 0;
view.addEventListener("touchstart", (e) => { _swipeX = e.changedTouches[0].clientX; }, { passive: true });
view.addEventListener("touchend", (e) => {
  if (state.tab !== "day" || !state.date) return;
  const dx = e.changedTouches[0].clientX - _swipeX;
  if (Math.abs(dx) > 55) { state.date = shiftDay(state.date, dx < 0 ? 1 : -1); showDay(); }
}, { passive: true });

async function api(path, opts = {}) {
  // initData читаем заново каждый раз: на части клиентов она появляется не сразу после загрузки
  const headers = { "X-Telegram-Init-Data": (tg && tg.initData) || INIT, ...(opts.headers || {}) };
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

function nowHM() { const n = new Date(); return n.getHours() * 60 + n.getMinutes(); }
function toMin(hm) { const [h, m] = hm.split(":").map(Number); return h * 60 + m; }
// сдвиг даты на ±1 день с пропуском воскресенья (в расписании его нет), переходит и на соседнюю неделю
function shiftDay(iso, delta) {
  const dt = new Date(iso + "T00:00:00");
  dt.setDate(dt.getDate() + delta);
  if (dt.getDay() === 0) dt.setDate(dt.getDate() + (delta > 0 ? 1 : -1));
  return dt.getFullYear() + "-" + String(dt.getMonth() + 1).padStart(2, "0") + "-" + String(dt.getDate()).padStart(2, "0");
}

// показ/скрытие шапок
function chrome({ hero = false, header = false, showStrip = false } = {}) {
  $("top").innerHTML = "";
  $("hdr").style.display = header ? "" : "none";
  if (!showStrip) strip.innerHTML = "";
}

// группируем подгруппы одной пары (одно время) в один блок
function groupSlots(lessons) {
  const map = new Map();
  for (const l of lessons) {
    const k = l.pair + "|" + l.start + "|" + l.end;
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(l);
  }
  return [...map.values()];
}

function slotFoot(slot, isToday) {
  if (!isToday) return "";
  const s = toMin(slot[0].start), e = toMin(slot[0].end), n = nowHM();
  if (n < s && s - n <= 90) return `<div class="foot soon">⏳ через ${s - n} мин</div>`;
  if (n >= s && n < e) return `<div class="foot now">● идёт · ещё ${e - n} мин</div>`;
  return "";
}

// карточка слота: кружок пары + одна карточка со всеми подгруппами
function daySlot(slot, isToday) {
  const first = slot[0];
  const cnt = first.of ? `<span class="count">${first.num} из ${first.of}</span>` : "";
  const foot = slotFoot(slot, isToday);
  const parts = slot.map((l, i) => {
    const rows = [
      l.teachers && `<div class="lrow">👤 ${esc(l.teachers)}</div>`,
      l.room && `<div class="lrow">📍 ${esc(l.room)}</div>`,
    ].filter(Boolean).join("");
    return `${i ? '<div class="divider"></div>' : ""}<div class="subj">${esc(l.subject)}</div>${rows}`;
  }).join("");
  return `<div class="tl ${first.kind_key} ${foot.includes("now") ? "active" : ""}">
    <div class="tlleft"><div class="circle">${esc(first.pair)}</div><div class="tltime">${first.start}<br><span>${first.end}</span></div></div>
    <div class="tlcard"><div class="tlhead"><span class="tag ${first.kind_key}">${KIND[first.kind_key] || esc(first.kind)}</span>${cnt}</div>
      ${parts}${foot}</div></div>`;
}

// --- экраны ---

async function showDay() {
  chrome({ header: true, showStrip: true }); spin();
  try {
    const d = await api("/api/day" + (state.date ? "?date=" + state.date : ""));
    state.date = d.date;
    $("h-title").textContent = d.title;
    $("h-sub").textContent = d.week_label;
    strip.innerHTML = '<div class="strip">'
      + '<div class="d nav" data-nav="-1">‹</div>'
      + d.strip.map((x) => {
        const bars = (x.kinds || []).map((k) => `<i class="bar ${k}"></i>`).join("") || '<i class="bar none"></i>';
        return `<div class="d ${x.active ? "active" : ""}" data-date="${x.date}">
          <small>${x.weekday}</small><b>${x.day}</b><div class="bars">${bars}</div></div>`;
      }).join("")
      + '<div class="d nav" data-nav="1">›</div>'
      + "</div>";
    strip.querySelectorAll(".d").forEach((el) => el.onclick = () => {
      state.date = el.dataset.nav ? shiftDay(state.date, +el.dataset.nav) : el.dataset.date;
      showDay();
    });
    const isToday = d.date === state.me.today;
    const slots = groupSlots(d.lessons);
    view.innerHTML = slots.length ? slots.map((s) => daySlot(s, isToday)).join("") : '<div class="empty">Пар нет 🎉</div>';
  } catch (e) { handle(e); }
}

// --- главная (hero) ---

async function showHome() {
  chrome({ hero: true }); spin();
  try {
    const d = await api("/api/day");
    const name = (tg && tg.initDataUnsafe.user && tg.initDataUnsafe.user.first_name) || "";
    const slots = groupSlots(d.lessons);
    const n = nowHM();
    let cur = null, kind = "";
    for (const s of slots) {
      const st = toMin(s[0].start), e = toMin(s[0].end);
      if (n < e) { cur = s; kind = n >= st ? "now" : "next"; break; }
    }
    let heroCard = '<div class="nowcard"><div class="subj">На сегодня пар больше нет 🎉</div></div>';
    if (cur) {
      const l = cur[0], st = toMin(l.start), e = toMin(l.end);
      const pct = kind === "now" ? Math.round(100 * (n - st) / (e - st)) : 0;
      const label = kind === "now" ? `идёт · ещё ${e - n} мин` : `через ${st - n} мин`;
      const subj = cur.length > 1 ? l.subject.replace(/\s*\(\d+\)$/, "") : l.subject;
      heroCard = `<div class="nowcard">
        <div class="bdg"><span class="pill">${KIND[l.kind_key] || esc(l.kind)} · пара ${esc(l.pair)}</span><span>${label}</span></div>
        <div class="subj">${esc(subj)}</div>
        <div class="prog"><i style="width:${pct}%"></i><b style="left:${pct}%"></b></div>
        <div class="ends"><span>${l.start}</span><span>${l.end}</span></div>
        <div class="info"><span class="chip">📍 ${esc(l.room || "—")}</span><span class="chip">👤 ${esc(l.teachers || "—")}</span></div></div>`;
    }
    $("top").innerHTML = `<div class="hero">
      <div class="top"><div><div class="greet">Привет${name ? ", " + esc(name) : ""}! 👋</div>
        <div class="meta">${esc(d.title)} · ${state.me.group ? esc(state.me.group.name) : ""}</div></div>
        <div class="ava">🎓</div></div>
      <div class="search" id="h-search">🔎 Группа, преподаватель, аудитория…</div>
      ${heroCard}</div>`;
    $("h-search").onclick = () => switchTab("search");
    const tiles = [
      ["📚", "Предметы", () => switchTab("subjects")],
      ["🚪", "Аудитории", () => switchTab("search")],
      ["👩‍🏫", "Преподаватели", () => switchTab("search")],
      ["📅", "Неделя", () => { state.view = "week"; switchTab("day"); showWeek(); }],
    ];
    view.innerHTML = `<div class="block">Быстрый доступ</div>
      <div class="big" id="h-lk"><div><b>Личный кабинет</b><div class="hint">оценки, сообщения, отметка</div></div><div class="ic">🎓</div></div>
      <div class="tiles">${tiles.map((t, i) => `<div class="tile" data-i="${i}"><div class="ti">${t[0]}</div><div class="tt">${t[1]}</div></div>`).join("")}</div>`;
    $("h-lk").onclick = () => { switchTab("settings"); setTimeout(showLK, 0); };
    view.querySelectorAll(".tile").forEach((el) => el.onclick = () => tiles[+el.dataset.i][2]());
  } catch (e) { handle(e); }
}

async function showWeek() {
  chrome({ header: true }); spin();
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
  chrome({ header: true }); spin();
  $("h-title").textContent = "Предметы"; $("h-sub").textContent = "текущий семестр";
  try {
    const d = await api("/api/subjects");
    view.innerHTML = d.subjects.map((s) => {
      const pct = s.total ? Math.round(100 * s.passed / s.total) : 0;
      return `<div class="row" data-name="${esc(s.name)}"><div style="flex:1">
        <div>${esc(s.name)}</div><div class="pbar"><i style="width:${pct}%"></i></div></div>
        <div class="rowprog">${s.passed}/${s.total}</div></div>`;
    }).join("") || '<div class="empty">Нет данных</div>';
    view.querySelectorAll(".row").forEach((r) => r.onclick = () => showSubject(r.dataset.name));
  } catch (e) { handle(e); }
}

async function showSubject(name) {
  chrome({ header: true }); spin();
  try {
    const d = await api("/api/subject?name=" + encodeURIComponent(name));
    $("h-title").textContent = name;
    $("h-sub").textContent = d.teachers.join(", ");
    backButton(showSubjects);
    const kinds = d.by_kind.map((k) => `<span class="pill2">${KIND[k.kind_key]}: ${k.passed}/${k.total}</span>`).join("");
    const rows = d.lessons.map((l) =>
      `<div class="card ${l.kind_key}" style="padding:8px 12px">
        <span class="time">${l.done ? "✅" : "▫️"} ${l.date.slice(8)}.${l.date.slice(5, 7)} · ${l.start}</span>
        <span class="tag ${l.kind_key}" style="margin-left:6px">${KIND[l.kind_key][0]}</span>
        ${l.room ? `<span class="meta"> · ${esc(l.room)}</span>` : ""}</div>`).join("");
    view.innerHTML = `<div class="seg"><button class="primary" id="go-diary">📔 Оценки и посещаемость</button></div>
      <div class="note">Всего ${d.total} · прошло ${d.passed} · впереди ${d.total - d.passed}</div>
      <div>${kinds}</div>${rows}`;
    $("go-diary").onclick = () => openSubjectDiary(name, () => showSubject(name));
  } catch (e) { handle(e); }
}

function _normSubject(s) {
  return (s || "").toLowerCase().replace(/ё/g, "е").replace(/\s*\(\d+\)$/, "").replace(/\s+/g, " ").trim();
}

async function openSubjectDiary(name, back) {
  chrome({ header: true }); spin(); backButton(back);
  $("h-title").textContent = name; $("h-sub").textContent = "дневник";
  try {
    const d = await api("/api/lk/diary");
    const n = _normSubject(name);
    const subj = d.subjects.find((s) => _normSubject(s.name) === n) ||
      d.subjects.find((s) => _normSubject(s.name).includes(n) || n.includes(_normSubject(s.name)));
    if (!subj) { view.innerHTML = '<div class="empty">По этому предмету в дневнике пока нет отметок.</div>'; return; }
    lkSubjectDiary(subj, back);
  } catch (e) {
    if (e.code === "no_group") {  // раздел ЛК вернул 409 — кабинет не подключён
      view.innerHTML = '<div class="empty">Подключите личный кабинет, чтобы видеть оценки и посещаемость.</div>' +
        '<div class="seg"><button class="primary" id="go-lk">🏛 Подключить кабинет</button></div>';
      $("go-lk").onclick = () => { switchTab("settings"); setTimeout(showLK, 0); };
    } else {
      view.innerHTML = '<div class="empty">Дневник недоступен.</div>';
    }
  }
}

// переключатель «Мои / Все»
function segment(mine, onMine, onAll) {
  return `<div class="seg"><button class="${mine ? "primary" : ""}" data-s="mine">${onMine}</button>` +
    `<button class="${mine ? "" : "primary"}" data-s="all">${onAll}</button></div>`;
}

function teacherRow(t) {
  const sub = t.subjects ? `<div class="rowprog" style="white-space:normal">${esc(t.subjects)}</div>` : "";
  return `<div class="row" data-k="teacher" data-id="${t.id}"><div style="flex:1"><div>👩‍🏫 ${esc(t.name)}</div>${sub}</div><span class="hint">→</span></div>`;
}
function roomRow(r) {
  const extra = r.count ? `<span class="rowprog">${r.count} зан.</span>` : '<span class="hint">→</span>';
  return `<div class="row" data-k="room" data-id="${r.id}"><span>🚪 ${esc(r.name)}</span>${extra}</div>`;
}

// единый поиск: преподаватели и аудитории двумя блоками; по умолчанию — «мои»
async function showSearch() {
  chrome({ header: true }); $("h-title").textContent = "Поиск"; $("h-sub").textContent = "преподаватель или аудитория";
  view.innerHTML = '<input id="q" placeholder="Фамилия или номер аудитории" autocomplete="off"><div id="res"></div>';
  const q = $("q"), res = $("res");
  const bind = () => res.querySelectorAll(".row").forEach((el) => el.onclick = () => showEntity(el.dataset.k, el.dataset.id));

  async function showMine() {
    try {
      const [t, r] = await Promise.all([api("/api/my-teachers"), api("/api/my-rooms")]);
      let html = "";
      if (t.teachers.length) html += '<div class="block">Мои преподаватели</div>' + t.teachers.map(teacherRow).join("");
      if (r.rooms.length) html += '<div class="block">Мои аудитории</div>' + r.rooms.slice(0, 12).map(roomRow).join("");
      res.innerHTML = html || '<div class="note">Не удалось собрать списки.</div>';
      bind();
    } catch (e) { res.innerHTML = ""; }
  }
  showMine();

  let timer;
  q.oninput = () => {
    clearTimeout(timer);
    const val = q.value.trim();
    if (val.length < 1) { showMine(); return; }
    if (val.length < 2) { return; }
    timer = setTimeout(async () => {
      try {
        const d = await api("/api/search?q=" + encodeURIComponent(val));
        let html = "";
        if (d.teachers.length) html += '<div class="block">Преподаватели</div>' + d.teachers.map(teacherRow).join("");
        if (d.rooms.length) html += '<div class="block">Аудитории</div>' + d.rooms.map(roomRow).join("");
        res.innerHTML = html || '<div class="note">Ничего не найдено</div>';
        bind();
      } catch (e) { handle(e); }
    }, 300);
  };
}

const showRooms = showSearch;  // плитка «Аудитории» ведёт в общий поиск

async function showEntity(kind, id, date) {
  chrome({ header: true }); spin();
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
  chrome({ header: true }); spin();
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
  chrome({ header: true }); spin();
  $("h-title").textContent = "Настройки"; $("h-sub").textContent = state.me.group ? state.me.group.name : "";
  const s = state.me.settings;
  const toggles = [
    ["notify_tomorrow", "Расписание на завтра"],
    ["notify_week", "Расписание на неделю"],
    ["notify_changes", "Изменения в расписании"],
    ["morning_digest", "Утренняя сводка"],
    ["quiet_hours", "Тихие часы (ночью без звука)"],
  ];
  const lkBtn = `<div class="row" id="lk-open"><span>🏛 Личный кабинет</span><span class="rowprog">оценки, отметка →</span></div>`;
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
  chrome({ header: true }); spin(); backButton(() => switchTab("settings"));
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
  view.querySelectorAll("[data-sec]").forEach((r) => r.onclick = () => (r.dataset.sec === "diary" ? lkDiary() : r.dataset.sec === "messages" ? lkMessages() : r.dataset.sec === "record_book" ? lkRecordBook() : lkSection(r.dataset.sec, r.textContent)));
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

function markChip(v) {
  const t = v.toLowerCase();
  const cls = /\d/.test(v) ? "g" : t.includes("н") ? "a" : "e";
  return `<span class="mk-chip ${cls}">${esc(v)}</span>`;
}

async function lkDiary() {
  chrome({ header: true }); spin(); backButton(showLK); $("h-title").textContent = "📔 Дневник";
  try {
    const d = await api("/api/lk/diary");
    if (!d.subjects.length) { view.innerHTML = '<div class="empty">Оценок и отметок пока нет.</div>'; return; }
    view.innerHTML = d.subjects.map((s, i) => {
      const g = s.grades.length ? `<span class="rowprog">оценки: ${s.grades.join(" ")}</span>` : "";
      const a = s.absences ? `<span class="rowprog" style="color:var(--lab)">Н ×${s.absences}</span>` : "";
      return `<div class="row" data-i="${i}"><div style="flex:1"><div>${esc(s.name)}</div>
        <div style="margin-top:4px">${g} ${a}</div></div><span class="hint">→</span></div>`;
    }).join("");
    view.querySelectorAll(".row").forEach((r) => r.onclick = () => lkSubjectDiary(d.subjects[+r.dataset.i]));
  } catch (e) { view.innerHTML = e.code === "no_group" ? "" : '<div class="empty">Дневник недоступен.</div>'; }
}

function lkSubjectDiary(s, back) {
  chrome({ header: true }); backButton(back || lkDiary); $("h-title").textContent = s.name; $("h-sub").textContent = "дневник";
  const summary = `<div class="note">Оценок: ${s.grades.length} · пропусков (Н): ${s.absences}</div>`;
  const rows = s.entries.map((e) => {
    const [y, m, dd] = e.date.split("-");
    return `<div class="row" style="cursor:default"><span>${dd}.${m}</span>${markChip(e.value)}</div>`;
  }).join("");
  view.innerHTML = summary + rows;
}

async function lkMessages() {
  chrome({ header: true }); spin(); backButton(showLK); $("h-title").textContent = "💬 Сообщения"; $("h-sub").textContent = "";
  try {
    const d = await api("/api/lk/messages");
    if (!d.messages.length) { view.innerHTML = '<div class="empty">Сообщений нет.</div>'; return; }
    view.innerHTML = d.messages.map((m, i) => {
      const date = m.date ? m.date.slice(8, 10) + "." + m.date.slice(5, 7) : "";
      const files = m.files.length ? " 📎" : "";
      return `<div class="row" data-i="${i}"><div style="flex:1"><div>${esc(m.sender)}${files}</div>
        <div class="rowprog" style="white-space:normal">${esc(m.subject)}</div></div><span class="hint">${date} →</span></div>`;
    }).join("");
    view.querySelectorAll(".row").forEach((r) => r.onclick = () => lkThread(d.messages[+r.dataset.i]));
  } catch (e) { view.innerHTML = e.code === "no_group" ? "" : '<div class="empty">Сообщения недоступны.</div>'; }
}

async function lkThread(m) {
  chrome({ header: true }); spin(); backButton(lkMessages);
  $("h-title").textContent = esc(m.subject); $("h-sub").textContent = esc(m.sender);
  try {
    const t = await api("/api/lk/thread?id=" + m.id);
    const bubbles = [];
    if (t.body) bubbles.push(`<div class="bubble in"><div class="who">${esc(m.sender)}</div>${esc(t.body)}</div>`);
    for (const h of t.history) {
      bubbles.push(`<div class="bubble in"><div class="who">${esc(h.who)} · ${esc(h.date)}</div>${esc(h.text)}</div>`);
    }
    const files = m.files.map((f) => `<div><a href="${esc(f.url)}" target="_blank">📎 ${esc(f.name)}</a></div>`).join("");
    const reply = t.can_reply
      ? `<div class="replybox"><textarea id="reply" placeholder="Ответ преподавателю…" rows="2"></textarea>
         <button class="mk" id="send">Отправить</button></div>`
      : '<div class="note">На это сообщение нельзя ответить.</div>';
    view.innerHTML = `<div class="chat">${bubbles.join("") || '<div class="note">Текст недоступен.</div>'}${files}</div>${reply}`;
    if (t.can_reply) {
      $("send").onclick = async () => {
        const text = $("reply").value.trim();
        if (!text) return;
        if (tg && !(await new Promise((r) => tg.showConfirm("Отправить ответ преподавателю от вашего имени?", r)))) return;
        $("send").textContent = "…"; $("send").disabled = true;
        try {
          await api("/api/lk/reply", { method: "POST", body: JSON.stringify({ id: m.id, text }) });
          if (tg) tg.HapticFeedback.notificationOccurred("success");
          lkThread(m);
        } catch (e) { $("send").textContent = "Ошибка"; $("send").disabled = false; }
      };
    }
  } catch (e) { view.innerHTML = '<div class="empty">Переписка недоступна.</div>'; }
}

async function lkRecordBook() {
  chrome({ header: true }); spin(); backButton(showLK); $("h-title").textContent = "📒 Зачётка"; $("h-sub").textContent = "";
  try {
    const d = await api("/api/lk/record-book");
    if (!d.semesters.length) { view.innerHTML = '<div class="empty">Данных нет.</div>'; return; }
    let openIdx = d.semesters.findIndex((s) => s.done < s.total);
    if (openIdx < 0) openIdx = d.semesters.length - 1;  // всё сдано — последний
    view.innerHTML = d.semesters.map((sem, i) => {
      const open = i === openIdx;  // текущий (первый незавершённый) семестр раскрыт
      const items = sem.subjects.map((s) => {
        const mark = s.done
          ? `<span class="mk-chip ${/\d/.test(s.grade) ? "g" : "e"}">${esc(s.grade)}</span>`
          : `<span class="rowprog">${esc(s.control) || "ещё будет"}</span>`;
        return `<div class="rb-item"><span>${s.done ? "✅" : "▫️"} ${esc(s.name)}</span>${mark}</div>`;
      }).join("");
      return `<div class="rb-sem">
        <div class="rb-head" data-i="${i}"><div><b>${esc(sem.title)}</b>
          <div class="rowprog">сдано ${sem.done} из ${sem.total}</div></div><span class="chev">${open ? "▾" : "▸"}</span></div>
        <div class="rb-body" data-body="${i}" style="display:${open ? "block" : "none"}">${items}</div></div>`;
    }).join("");
    view.querySelectorAll(".rb-head").forEach((h) => h.onclick = () => {
      const b = view.querySelector(`[data-body="${h.dataset.i}"]`);
      const open = b.style.display === "none";
      b.style.display = open ? "block" : "none";
      h.querySelector(".chev").textContent = open ? "▾" : "▸";
    });
  } catch (e) { view.innerHTML = e.code === "no_group" ? "" : '<div class="empty">Зачётка недоступна.</div>'; }
}

async function lkSection(name, title) {
  chrome({ header: true }); spin(); backButton(showLK); $("h-title").textContent = title;
  try {
    const d = await api("/api/lk/section?name=" + name);
    view.innerHTML = `<div class="card" style="border:none">${d.html}</div>`;
  } catch (e) {
    view.innerHTML = e.code === "no_group" ? "" : '<div class="empty">Раздел недоступен.</div>';
  }
}

async function lkAttendance() {
  chrome({ header: true }); spin(); backButton(showLK); $("h-title").textContent = "Отметка на паре";
  try {
    const d = await api("/api/lk/attendance");
    if (!d.lessons.length) { view.innerHTML = '<div class="empty">Сегодня пар нет.</div>'; return; }
    view.innerHTML = '<div class="note">Кнопка активна за 10 минут до пары. Отметка — действие в ЛК от вашего имени.</div>' +
      d.lessons.map((l) => {
        const st = l.started ? "✅ отмечено" : l.ready ? "" : "⏳ рано";
        const btn = (!l.started && l.ready) ? `<button class="mk" data-rasp="${l.rasp}">Отметиться</button>` : `<span class="rowprog">${st}</span>`;
        return `<div class="row"><div><div>${esc(l.subject)}</div><div class="rowprog">${esc(l.time)} · ${esc(l.room)}</div></div>${btn}</div>`;
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
  chrome({ header: true }); spin(); backButton(showSettings);
  $("h-title").textContent = "Выбор группы";
  view.innerHTML = '<input id="gq" placeholder="Номер группы, напр. ИСТ-2633" autocomplete="off"><div id="gres"></div>';
  const gq = $("gq"), gres = $("gres"); gq.focus();
  let timer;
  gq.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const d = await api("/api/groups?q=" + encodeURIComponent(gq.value.trim()));
      gres.innerHTML = d.groups.map((g) => `<div class="row" data-id="${g.id}">${esc(g.name)} <span class="rowprog">${esc(g.faculty)}</span></div>`).join("");
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

const TABS = { home: showHome, day: showDay, week: showWeek, subjects: showSubjects, search: showSearch, settings: showSettings };
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
  // ждём, пока Telegram отдаст initData (иногда появляется на несколько сотен мс позже загрузки)
  for (let i = 0; i < 20 && tg && !tg.initData; i++) await new Promise((r) => setTimeout(r, 50));
  try {
    state.me = await api("/api/me");
    if (!state.me.consent) { view.innerHTML = '<div class="empty">Откройте бота командой /start и примите документы, затем вернитесь в приложение.</div>'; strip.innerHTML = ""; return; }
    if (!state.me.group) { chooseGroup(); return; }
    switchTab("home");
  } catch (e) { handle(e); }
})();
