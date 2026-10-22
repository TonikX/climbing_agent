import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
} from "recharts";
import {
  Mountain,
  LayoutDashboard,
  ChartNoAxesCombined,
  NotebookTabs,
  UserRound,
  ArrowUpRight,
  ChevronRight,
  ArrowLeft,
  Check,
  Flame,
  Flag,
  Menu,
  X,
  ExternalLink,
} from "lucide-react";
import {
  dashboard,
  request,
  trainingPage,
  type Filters,
  type Training,
  type Summary,
  type Grade,
  type Period,
  type User,
  type BrowserSession,
} from "./api";
import * as demo from "./demo";
import "./style.css";
type Page = "overview" | "progress" | "trainings" | "profile";
const navigation = [
  { id: "overview", label: "Обзор", icon: LayoutDashboard },
  { id: "progress", label: "Прогресс", icon: ChartNoAxesCombined },
  { id: "trainings", label: "Тренировки", icon: NotebookTabs },
  { id: "profile", label: "Профиль", icon: UserRound },
] as const;
const date = (value: string) =>
  new Intl.DateTimeFormat("ru", { day: "numeric", month: "long" }).format(
    new Date(value + "T12:00:00"),
  );
const month = (value: string) =>
  new Intl.DateTimeFormat("ru", { month: "short" })
    .format(new Date(value + "-01T12:00:00"))
    .replace(".", "");
const labels: Record<string, string> = {
  lead: "Нижняя",
  toprope: "Верхняя",
  top_rope: "Верхняя",
  auto_belay: "Автостраховка",
  bouldering: "Боулдеринг",
  flash: "Flash",
  onsight: "Onsight",
  redpoint: "Red Point",
  hang: "С зависанием",
  with_hangs: "С зависанием",
  fall: "Со срывом",
  with_falls: "Со срывом",
  unknown: "Не указано",
};
const label = (v: string) => labels[v] ?? v;
function App() {
  const params = new URLSearchParams(location.search);
  const [isDemo, setDemo] = useState(params.get("demo") === "1");
  const [page, setPage] = useState<Page>(
    (navigation.some((n) => n.id === params.get("page"))
      ? params.get("page")
      : "overview") as Page,
  );
  const today = new Date();
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const [filters, setFilters] = useState<Filters>({
    from:
      params.get("from") ||
      iso(new Date(today.getFullYear(), today.getMonth(), 1)),
    to: params.get("to") || iso(today),
    grade: params.get("grade") || "",
  });
  const [preset, setPreset] = useState("month");
  const [mobile, setMobile] = useState(false);
  const [selected, setSelected] = useState<Training | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [csrf, setCsrf] = useState("");
  const [loginEnabled, setLoginEnabled] = useState(false);
  const [authError] = useState(params.get("auth_error"));
  const authMessages: Record<string, string> = {
    expired: "Время входа истекло. Попробуйте ещё раз.",
    failed: "Telegram не подтвердил вход. Попробуйте ещё раз.",
    cancelled: "Вход отменён.",
    approval: "Сначала запросите доступ через бота и дождитесь подтверждения.",
  };
  const [data, setData] = useState<{
    summary: Summary;
    grades: Grade[];
    periods: Period[];
  } | null>(null);
  const [trainings, setTrainings] = useState<Training[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [moreBusy, setMoreBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (isDemo) return;
    const ac = new AbortController();
    request<{ telegramLoginEnabled: boolean }>("/auth/config", ac.signal)
      .then((c) => setLoginEnabled(c.telegramLoginEnabled))
      .catch(() => setLoginEnabled(false));
    return () => ac.abort();
  }, [isDemo, retry]);
  useEffect(() => {
    const q = new URLSearchParams({ page, from: filters.from, to: filters.to });
    if (isDemo) q.set("demo", "1");
    if (filters.grade) q.set("grade", filters.grade);
    history.replaceState(null, "", "?" + q);
  }, [page, filters, isDemo]);
  useEffect(() => {
    const ac = new AbortController();
    setBusy(true);
    setError(null);
    setSelected(null);
    setData(null);
    setTrainings([]);
    setUser(null);
    setCsrf("");
    if (isDemo) {
      setUser({
        name: "Александр",
        timezone: "Europe/Moscow",
        status: "active",
      });
      setData({
        summary: demo.summary,
        grades: demo.grades,
        periods: demo.periods,
      });
      setTrainings(demo.trainings);
      setCursor(null);
      setBusy(false);
      return () => ac.abort();
    }
    request<BrowserSession>("/auth/session", ac.signal)
      .then(async (auth) => {
        const [d, t] = await Promise.all([
          dashboard(filters, ac.signal),
          trainingPage(null, ac.signal),
        ]);
        if (ac.signal.aborted) return;
        setUser(auth.user);
        setCsrf(auth.csrfToken);
        setData(d);
        setTrainings(t.items);
        setCursor(t.next_cursor);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e);
      })
      .finally(() => {
        if (!ac.signal.aborted) setBusy(false);
      });
    return () => ac.abort();
  }, [isDemo, filters, retry]);
  async function logout(all = false) {
    setMoreBusy(true);
    try {
      await request<void>(
        all ? "/auth/logout-all" : "/auth/logout",
        undefined,
        { method: "POST", csrf },
      );
      setUser(null);
      setData(null);
      setTrainings([]);
      setCsrf("");
      setRetry((v) => v + 1);
    } catch (e) {
      setError(e as Error);
    } finally {
      setMoreBusy(false);
    }
  }
  function navigate(p: Page) {
    setPage(p);
    setSelected(null);
    setMobile(false);
  }
  function choosePeriod(value: string) {
    setPreset(value);
    if (value === "custom") return;
    const end = new Date();
    const start = new Date(end);
    if (value === "month") start.setDate(1);
    if (value === "week")
      start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    if (value === "year") {
      start.setMonth(0, 1);
    }
    setFilters({ ...filters, from: iso(start), to: iso(end) });
  }
  async function loadMore() {
    if (!cursor) return;
    setMoreBusy(true);
    try {
      const t = await trainingPage(cursor, new AbortController().signal);
      setTrainings((v) => [...v, ...t.items]);
      setCursor(t.next_cursor);
    } catch (e) {
      setError(e as Error);
    } finally {
      setMoreBusy(false);
    }
  }
  const s = data?.summary;
  const authenticated = !!user;
  const counts = [
    ["Тренировки", s?.trainingsCount, NotebookTabs],
    ["Выходы на трассы", s?.routesCount, Mountain],
    ["Попытки", s?.attemptsCount, Flame],
    ["Дошёл до конца", s?.reachedTopRoutes, Flag],
    ["Чистые пролазы", s?.completedRoutes, Check],
  ] as const;
  return (
    <div className="shell">
      <aside className={mobile ? "sidebar open" : "sidebar"}>
        <a className="brand" href="?page=overview">
          <span className="brand-icon">
            <Mountain size={26} />
          </span>
          <span>
            climbing<span className="brand-sub">JOURNAL</span>
          </span>
        </a>
        <button
          className="mobile-close icon-button"
          aria-label="Закрыть меню"
          onClick={() => setMobile(false)}
        >
          <X />
        </button>
        <div className="nav-label">ЛИЧНЫЙ КАБИНЕТ</div>
        <nav aria-label="Основная навигация">
          {navigation.map((n) => (
            <button
              key={n.id}
              className={page === n.id ? "nav-item active" : "nav-item"}
              onClick={() => navigate(n.id)}
            >
              <n.icon size={20} />
              {n.label}
              {page === n.id && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="bot-card">
            <Mountain size={23} />
            <strong>
              Каждый пролаз —<br />
              часть твоего пути.
            </strong>
            <p>Записывай тренировки в Telegram, следи за прогрессом здесь.</p>
            <a
              href="https://t.me/anton_climbing_bot"
              target="_blank"
              rel="noreferrer"
            >
              Открыть бота <ArrowUpRight size={16} />
            </a>
          </div>
          <button className="account" onClick={() => navigate("profile")}>
            <span className="avatar">{user?.name[0] ?? "Г"}</span>
            <span>
              <strong>{user?.name ?? "Гость"}</strong>
              <small>{isDemo ? "Демо-профиль" : "Личный журнал"}</small>
            </span>
            <ChevronRight size={16} />
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            aria-label="Открыть меню"
            onClick={() => setMobile(true)}
          >
            <Menu />
          </button>
          <span>
            Личный журнал{" "}
            <span className="crumb">
              / {navigation.find((n) => n.id === page)?.label}
            </span>
          </span>
          <div className="top-actions">
            <span className="privacy">
              <span /> Только ваши данные
            </span>
            <a
              href="https://t.me/anton_climbing_bot"
              target="_blank"
              rel="noreferrer"
            >
              Telegram <ExternalLink size={14} />
            </a>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">ТВОЙ ПУТЬ НАВЕРХ</div>
              <h1>
                {selected
                  ? "Тренировка"
                  : {
                      overview: "За каждым пролазом — прогресс.",
                      progress: "Выше. Увереннее. Чище.",
                      trainings: "Твои тренировки",
                      profile: "Личный профиль",
                    }[page]}
              </h1>
              <p>
                {selected
                  ? date(selected.local_date)
                  : {
                      overview: "Всё, над чем ты работаешь, в одном месте.",
                      progress: "Посмотри, как меняются твои результаты.",
                      trainings:
                        "История выходов, маршрутов и маленьких побед.",
                      profile: "Один аккаунт для сайта и Telegram-бота.",
                    }[page]}
              </p>
            </div>
            <span className="heading-mark">
              <Mountain size={52} strokeWidth={1} />
            </span>
          </div>
          {isDemo && (
            <div className="demo-banner">
              <span>
                <strong>Демонстрационный журнал</strong> · Пример интерфейса, не
                ваши тренировки. Фильтры не изменяют пример.
              </span>
              <button onClick={() => setDemo(false)}>
                Перейти к своим данным <ArrowUpRight size={14} />
              </button>
            </div>
          )}
          {!busy && error && !authenticated ? (
            <section className="login-card">
              <span className="large-icon">
                <Mountain size={40} />
              </span>
              <div className="eyebrow">CLIMBING JOURNAL</div>
              <h2>Твой журнал. Твой прогресс.</h2>
              <p>
                {authError && authMessages[authError]
                  ? authMessages[authError]
                  : error.message}
              </p>
              <p className="muted">
                {loginEnabled
                  ? "Войдите через Telegram. Откроется тот же личный журнал, что и в боте. Доступ требует подтверждения владельцем."
                  : "Веб-вход временно недоступен. Тренировки и статистика доступны в боте."}
              </p>
              {loginEnabled && (
                <a
                  className="primary-button"
                  href="/api/v1/auth/telegram/start"
                >
                  Войти через Telegram <ArrowUpRight size={17} />
                </a>
              )}
              <a
                className="primary-button"
                href="https://t.me/anton_climbing_bot"
              >
                Открыть Telegram <ArrowUpRight size={17} />
              </a>
              <button
                className="secondary-button"
                onClick={() => setDemo(true)}
              >
                Посмотреть демонстрацию
              </button>
              <button
                className="text-button"
                onClick={() => setRetry((v) => v + 1)}
              >
                Повторить подключение
              </button>
            </section>
          ) : (
            <>
              {page !== "profile" && !selected && (
                <div className="filterbar">
                  <div className="segments" aria-label="Период">
                    {[
                      ["week", "Неделя"],
                      ["month", "Месяц"],
                      ["year", "Год"],
                      ["custom", "Свой период"],
                    ].map(([id, title]) => (
                      <button
                        key={id}
                        disabled={isDemo}
                        className={preset === id ? "chosen" : ""}
                        onClick={() => choosePeriod(id)}
                      >
                        {title}
                      </button>
                    ))}
                  </div>
                  <div className="date-filters">
                    <label>
                      <span className="sr-only">Начало периода</span>
                      <input
                        disabled={isDemo}
                        type="date"
                        value={filters.from}
                        max={filters.to}
                        onChange={(e) => {
                          setPreset("custom");
                          setFilters({ ...filters, from: e.target.value });
                        }}
                      />
                    </label>
                    <span>—</span>
                    <label>
                      <span className="sr-only">Конец периода</span>
                      <input
                        disabled={isDemo}
                        type="date"
                        value={filters.to}
                        min={filters.from}
                        onChange={(e) => {
                          setPreset("custom");
                          setFilters({ ...filters, to: e.target.value });
                        }}
                      />
                    </label>
                    <label>
                      <span className="sr-only">Категория</span>
                      <select
                        disabled={isDemo}
                        value={filters.grade}
                        onChange={(e) =>
                          setFilters({ ...filters, grade: e.target.value })
                        }
                      >
                        <option value="">Все категории</option>
                        {[
                          "5A",
                          "5B",
                          "5C",
                          "6A",
                          "6A+",
                          "6B",
                          "6B/6B+",
                          "6B+",
                          "6C",
                          "6C+",
                          "7A",
                          "7A+",
                          "7B",
                          "7C",
                          "8A",
                          "8B",
                          "8C",
                          "9A",
                        ].map((g) => (
                          <option key={g}>{g}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                </div>
              )}
              {busy ? (
                <div role="status" className="loading">
                  <span className="spinner" /> Загружаем журнал…
                </div>
              ) : (
                <>
                  {error && (
                    <div role="alert" className="demo-banner">
                      {error.message}
                      <button onClick={() => setRetry((v) => v + 1)}>
                        Повторить
                      </button>
                    </div>
                  )}
                  {selected ? (
                    <section className="panel detail">
                      <button
                        className="text-button back"
                        onClick={() => setSelected(null)}
                      >
                        <ArrowLeft size={16} /> К тренировкам
                      </button>
                      <div className="section-heading">
                        <div>
                          <h2>
                            {selected.demoLocation ?? "Тренировка"} ·{" "}
                            {date(selected.local_date)}
                          </h2>
                          <p>
                            {selected.demoSector ??
                              "Места указаны в данных попыток"}{" "}
                            ·{" "}
                            {selected.duration_minutes === null
                              ? "Длительность не указана"
                              : selected.duration_minutes + " мин"}
                          </p>
                        </div>
                        <span className="badge">
                          {selected.status === "active"
                            ? "Идёт сейчас"
                            : "Завершена"}
                        </span>
                      </div>
                      {selected.attempts.filter((a) => !a.is_test).length ===
                      0 ? (
                        <p className="empty">Реальных попыток пока нет.</p>
                      ) : (
                        selected.attempts
                          .filter((a) => !a.is_test)
                          .map((a) => (
                            <article className="attempt" key={a.id}>
                              <div className="attempt-title">
                                <span className="grade-chip">
                                  {a.route_snapshot.grade ?? "—"}
                                </span>
                                <div>
                                  <h3>
                                    {a.route_snapshot.name ?? "Без названия"}
                                  </h3>
                                  <small>
                                    Запись №{a.sequence} · попыток: {a.attempts}
                                  </small>
                                </div>
                                <span
                                  className={
                                    a.clean_ascent ? "badge clean" : "badge"
                                  }
                                >
                                  {a.clean_ascent
                                    ? "✓ Чисто"
                                    : a.reached_top
                                      ? "Дошёл до конца"
                                      : a.reached_top === null
                                        ? "Результат не уточнён"
                                        : "Не завершена"}
                                </span>
                              </div>
                              <dl className="attempt-fields">
                                <div>
                                  <dt>Стиль</dt>
                                  <dd>{label(a.style)}</dd>
                                </div>
                                <div>
                                  <dt>Страховка</dt>
                                  <dd>{label(a.belay)}</dd>
                                </div>
                                <div>
                                  <dt>Срывы / зависания</dt>
                                  <dd>
                                    {a.falls ?? "—"} / {a.hangs ?? "—"}
                                  </dd>
                                </div>
                                <div>
                                  <dt>Чистота</dt>
                                  <dd>
                                    {a.clean_ascent === null
                                      ? "Не уточнена"
                                      : a.clean_ascent
                                        ? "Да"
                                        : "Нет"}
                                  </dd>
                                </div>
                              </dl>
                              {a.notes && (
                                <p className="attempt-note">{a.notes}</p>
                              )}
                            </article>
                          ))
                      )}
                    </section>
                  ) : (
                    <>
                      {page === "overview" && (
                        <>
                          <div className="kpis">
                            {counts.map(([title, value, Icon], i) => (
                              <div
                                key={title}
                                className={"kpi " + (i === 4 ? "accent" : "")}
                              >
                                <div>
                                  <span>{title}</span>
                                  <Icon size={18} />
                                </div>
                                <strong>{value ?? "—"}</strong>
                                <small>
                                  {i === 1
                                    ? "Выходы на трассы за период"
                                    : i === 4
                                      ? "Без срывов и зависаний"
                                      : "За выбранный период"}
                                </small>
                              </div>
                            ))}
                          </div>
                          <div className="maxima">
                            <span className="max-label">ТВОЙ МАКСИМУМ</span>
                            {[
                              ["Пробовал", s?.maxAttemptedGrade],
                              ["Дошёл до конца", s?.maxReachedTopGrade],
                              ["Пролез чисто", s?.maxCompletedGrade],
                            ].map(([title, g]) => (
                              <div key={title}>
                                <span>{title}</span>
                                <strong>{g ?? "—"}</strong>
                              </div>
                            ))}
                            <Mountain
                              className="max-mountain"
                              size={62}
                              strokeWidth={1}
                            />
                          </div>
                        </>
                      )}
                      {(page === "overview" || page === "progress") && (
                        <div className="charts">
                          <section className="panel">
                            <div className="section-heading">
                              <div>
                                <h2>Движение вверх</h2>
                                <p>
                                  До 6 последних месяцев с тренировками в
                                  периоде
                                </p>
                              </div>
                              <ChartNoAxesCombined size={20} />
                            </div>
                            <div className="legend">
                              <span>
                                <i /> Попытки
                              </span>
                              <span>
                                <i className="light" /> Чистые пролазы
                              </span>
                            </div>
                            {!data?.periods.length ? (
                              <p className="empty">
                                В выбранном периоде тренировок нет.
                              </p>
                            ) : (
                              <div className="chart">
                                <ResponsiveContainer width="100%" height="100%">
                                  <AreaChart
                                    data={[...data.periods]
                                      .reverse()
                                      .map((p) => ({
                                        ...p,
                                        name: month(p.period),
                                      }))}
                                    margin={{
                                      top: 10,
                                      right: 12,
                                      left: -24,
                                      bottom: 0,
                                    }}
                                  >
                                    <defs>
                                      <linearGradient
                                        id="fade"
                                        x1="0"
                                        y1="0"
                                        x2="0"
                                        y2="1"
                                      >
                                        <stop
                                          offset="0%"
                                          stopColor="#24664f"
                                          stopOpacity={0.18}
                                        />
                                        <stop
                                          offset="100%"
                                          stopColor="#24664f"
                                          stopOpacity={0}
                                        />
                                      </linearGradient>
                                    </defs>
                                    <CartesianGrid
                                      vertical={false}
                                      stroke="#edf0eb"
                                    />
                                    <XAxis
                                      dataKey="name"
                                      axisLine={false}
                                      tickLine={false}
                                      tick={{ fill: "#808982", fontSize: 12 }}
                                    />
                                    <YAxis
                                      axisLine={false}
                                      tickLine={false}
                                      allowDecimals={false}
                                      tick={{ fill: "#808982", fontSize: 12 }}
                                    />
                                    <Tooltip />
                                    <Area
                                      name="Попытки"
                                      type="monotone"
                                      dataKey="attemptsCount"
                                      stroke="#24664f"
                                      fill="url(#fade)"
                                      strokeWidth={2.5}
                                    />
                                    <Area
                                      name="Чистые пролазы"
                                      type="monotone"
                                      dataKey="completedRoutes"
                                      stroke="#a4b970"
                                      fill="transparent"
                                      strokeWidth={2.5}
                                    />
                                  </AreaChart>
                                </ResponsiveContainer>
                              </div>
                            )}
                            <details>
                              <summary>Показать данные таблицей</summary>
                              <div className="table-wrap">
                                <table>
                                  <thead>
                                    <tr>
                                      <th>Месяц</th>
                                      <th>Попытки</th>
                                      <th>Чисто</th>
                                      <th>Максимум чисто</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {data?.periods.map((p) => (
                                      <tr key={p.period}>
                                        <td>{p.period}</td>
                                        <td>{p.attemptsCount ?? "—"}</td>
                                        <td>{p.completedRoutes ?? "—"}</td>
                                        <td>{p.maxCompletedGrade ?? "—"}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </details>
                          </section>
                          <section className="panel">
                            <div className="section-heading">
                              <div>
                                <h2>Твои категории</h2>
                                <p>Выходы на трассы · порядок из журнала</p>
                              </div>
                              <Mountain size={20} />
                            </div>
                            {!data?.grades.length ? (
                              <p className="empty">
                                Пока нет данных по категориям.
                              </p>
                            ) : (
                              <div className="chart">
                                <ResponsiveContainer width="100%" height="100%">
                                  <BarChart
                                    data={data.grades}
                                    margin={{
                                      top: 20,
                                      right: 5,
                                      left: -27,
                                      bottom: 0,
                                    }}
                                  >
                                    <CartesianGrid
                                      vertical={false}
                                      stroke="#edf0eb"
                                    />
                                    <XAxis
                                      dataKey="grade"
                                      tickLine={false}
                                      axisLine={false}
                                      tick={{ fontSize: 11, fill: "#808982" }}
                                    />
                                    <YAxis
                                      allowDecimals={false}
                                      tickLine={false}
                                      axisLine={false}
                                      tick={{ fontSize: 12, fill: "#808982" }}
                                    />
                                    <Tooltip />
                                    <Bar
                                      name="Выходы на трассы"
                                      dataKey="routesCount"
                                      fill="#bdd0bc"
                                      radius={[5, 5, 0, 0]}
                                      maxBarSize={32}
                                    />
                                    <Bar
                                      name="Чисто"
                                      dataKey="completedRoutes"
                                      fill="#24664f"
                                      radius={[5, 5, 0, 0]}
                                      maxBarSize={32}
                                    />
                                  </BarChart>
                                </ResponsiveContainer>
                              </div>
                            )}
                            <div className="legend">
                              <span>
                                <i className="pale" /> Выходы на трассы
                              </span>
                              <span>
                                <i /> Чисто
                              </span>
                            </div>
                          </section>
                        </div>
                      )}
                      {page === "progress" && (
                        <section className="panel">
                          <div className="section-heading">
                            <div>
                              <h2>Категории в деталях</h2>
                              <p>
                                Статистика рассчитывается на сервере, тестовые
                                записи исключены
                              </p>
                            </div>
                          </div>
                          <div className="table-wrap">
                            <table>
                              <thead>
                                <tr>
                                  <th>Категория</th>
                                  <th>Выходы на трассы</th>
                                  <th>Попытки</th>
                                  <th>Чисто</th>
                                </tr>
                              </thead>
                              <tbody>
                                {data?.grades.map((g) => (
                                  <tr key={g.grade}>
                                    <td>
                                      <span className="grade-chip">
                                        {g.grade}
                                      </span>
                                    </td>
                                    <td>{g.routesCount ?? "—"}</td>
                                    <td>{g.attemptsCount ?? "—"}</td>
                                    <td>{g.completedRoutes ?? "—"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </section>
                      )}
                      {(page === "overview" || page === "trainings") && (
                        <section className="panel training-panel">
                          <div className="section-heading">
                            <div>
                              <h2>
                                {page === "overview"
                                  ? "Последние тренировки"
                                  : "Журнал тренировок"}
                              </h2>
                              <p>
                                История всех дат · фильтры выше относятся к
                                статистике
                              </p>
                            </div>
                            {page === "overview" && (
                              <button
                                className="text-button"
                                onClick={() => navigate("trainings")}
                              >
                                Весь журнал <ArrowUpRight size={16} />
                              </button>
                            )}
                          </div>
                          {trainings.length === 0 ? (
                            <p className="empty">
                              Тренировок пока нет. Первую можно записать в
                              Telegram.
                            </p>
                          ) : (
                            (page === "overview"
                              ? trainings.slice(0, 3)
                              : trainings
                            ).map((t) => (
                              <button
                                className="training-row"
                                key={t.id}
                                onClick={() => {
                                  setSelected(t);
                                  setPage("trainings");
                                }}
                              >
                                <span className="date-tile">
                                  <strong>
                                    {Number(t.local_date.slice(-2))}
                                  </strong>
                                  <small>
                                    {month(t.local_date.slice(0, 7))}
                                  </small>
                                </span>
                                <div className="training-name">
                                  <strong>
                                    {t.demoLocation ??
                                      (t.environment === "outdoor"
                                        ? "Тренировка на скалах"
                                        : "Тренировка")}
                                  </strong>
                                  <span>
                                    {t.demoSector ??
                                      "Открыть попытки и характеристики"}
                                  </span>
                                </div>
                                <span className="training-duration">
                                  {t.duration_minutes === null
                                    ? "—"
                                    : t.duration_minutes + " мин"}
                                </span>
                                <span
                                  className={
                                    "badge " +
                                    (t.status === "active" ? "clean" : "")
                                  }
                                >
                                  {t.status === "active"
                                    ? "Идёт сейчас"
                                    : "Завершена"}
                                </span>
                                <ChevronRight size={18} />
                              </button>
                            ))
                          )}
                          {page === "trainings" && cursor && (
                            <button
                              className="secondary-button load-more"
                              disabled={moreBusy}
                              onClick={loadMore}
                            >
                              {moreBusy ? "Загрузка…" : "Загрузить ещё"}
                            </button>
                          )}
                        </section>
                      )}
                      {page === "profile" && (
                        <section className="panel profile">
                          <span className="avatar big">{user?.name[0]}</span>
                          <h2>{user?.name}</h2>
                          <dl>
                            <dt>Часовой пояс</dt>
                            <dd>{user?.timezone}</dd>
                            <dt>Доступ</dt>
                            <dd>
                              {user?.status === "active"
                                ? "Подтверждён"
                                : user?.status}
                            </dd>
                            <dt>Источник данных</dt>
                            <dd>
                              {isDemo
                                ? "Демонстрационный пример"
                                : "Личный журнал PostgreSQL"}
                            </dd>
                          </dl>
                          <p className="muted">
                            Запись и редактирование тренировок доступны в
                            Telegram.
                          </p>
                          <a
                            className="primary-button"
                            href="https://t.me/anton_climbing_bot"
                          >
                            Открыть бота <ArrowUpRight size={16} />
                          </a>
                          {isDemo && (
                            <button
                              className="secondary-button"
                              onClick={() => setDemo(false)}
                            >
                              Выйти из демонстрации
                            </button>
                          )}
                          {!isDemo && (
                            <div>
                              <button
                                className="secondary-button"
                                disabled={moreBusy}
                                onClick={() => logout()}
                              >
                                Выйти
                              </button>
                              <button
                                className="text-button"
                                disabled={moreBusy}
                                onClick={() => logout(true)}
                              >
                                Выйти со всех устройств
                              </button>
                            </div>
                          )}
                        </section>
                      )}
                    </>
                  )}
                </>
              )}
            </>
          )}
          <footer>
            <span>
              CLIMBING JOURNAL <span className="footer-dot">·</span> Свой темп.
              Свой маршрут.
            </span>
            <span>
              {isDemo
                ? "Демонстрационные данные"
                : (user?.timezone ?? "Личная статистика")}{" "}
              <span className="footer-dot">·</span> Без LLM при просмотре
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
