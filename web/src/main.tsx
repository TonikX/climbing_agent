import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
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
  type PlaceFilters,
} from "./api";
import * as demo from "./demo";
import { readStatisticsView, type StatisticsView } from "./statistics-view";
import "./style.css";
import { Pyramid } from "./Pyramid";
import { AttemptForm } from "./AttemptForm";
import { BelaySummary } from "./BelaySummary";
import { TrainingControls } from "./TrainingControls";
type Page = "overview" | "trainings" | "profile";
const navigation = [
  { id: "overview", label: "Обзор", icon: LayoutDashboard },
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
  not_reached: "Не долез",
  fall: "Со срывом",
  with_falls: "Со срывом",
  unknown: "Не указано",
};
const label = (v: string) => labels[v] ?? v;
const trainingPlace = (t: Training) =>
  t.locations?.map((p) => p.name).join(" · ") ||
  t.demoLocation ||
  "Место не указано";
const trainingContext = (t: Training) => {
  const regions = [
    ...new Set(t.locations?.map((p) => p.region).filter(Boolean)),
  ].join(", ");
  const sectors = t.sectors?.join(", ") || t.demoSector;
  return (
    [regions, sectors && `Секторы: ${sectors}`].filter(Boolean).join(" · ") ||
    "Регион и сектор не указаны"
  );
};
function App() {
  const params = new URLSearchParams(location.search);
  const [statisticsView, setStatisticsView] = useState<StatisticsView>(() =>
    readStatisticsView(location.search),
  );
  const advanced = statisticsView === "advanced";
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
    from: params.has("from")
      ? params.get("from")!
      : iso(new Date(today.getFullYear(), today.getMonth(), 1)),
    to: params.has("to") ? params.get("to")! : iso(today),
    grade: params.get("grade") || "",
    region: params.get("region") || "",
    areaId: params.get("area_id") || "",
  });
  const [preset, setPreset] = useState(
    params.has("from") && params.get("from") === "" && params.has("to") && params.get("to") === ""
      ? "all" : params.has("from") || params.has("to") ? "custom" : "month",
  );
  const [mobile, setMobile] = useState(false);
  const [selected, setSelected] = useState<Training | null>(null);
  const [capture, setCapture] = useState(false);
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
  const [places, setPlaces] = useState<PlaceFilters>({
    regions: [],
    areas: [],
  });
  const generation = useRef(0);
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
    if (filters.region) q.set("region", filters.region);
    if (filters.areaId) q.set("area_id", filters.areaId);
    q.set("view", statisticsView);
    history.replaceState(null, "", "?" + q);
  }, [page, filters, isDemo, statisticsView]);
  useEffect(() => {
    const ac = new AbortController();
    generation.current += 1;
    setMoreBusy(false);
    setCursor(null);
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
        const [d, t, options] = await Promise.all([
          dashboard(filters, ac.signal),
          trainingPage(filters, null, ac.signal),
          request<PlaceFilters>("/training-filters", ac.signal),
        ]);
        if (ac.signal.aborted) return;
        setUser(auth.user);
        setCsrf(auth.csrfToken);
        setData(d);
        setTrainings(t.items);
        setCursor(t.next_cursor);
        setPlaces(options);
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
    if (value === "all") {
      setFilters({ ...filters, from: "", to: "" });
      return;
    }
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
    const currentGeneration = generation.current;
    setMoreBusy(true);
    try {
      const t = await trainingPage(
        filters,
        cursor,
        new AbortController().signal,
      );
      if (currentGeneration !== generation.current) return;
      setTrainings((v) => [...v, ...t.items]);
      setCursor(t.next_cursor);
    } catch (e) {
      if (currentGeneration !== generation.current) return;
      setError(e as Error);
    } finally {
      if (currentGeneration === generation.current) setMoreBusy(false);
    }
  }
  const s = data?.summary;
  const authenticated = !!user;
  const counts = [
    ["Тренировки", s?.trainingsCount, NotebookTabs],
    ["Пролазы", s?.routesCount, Mountain],
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
                      trainings: "Твои тренировки",
                      profile: "Личный профиль",
                    }[page]}
              </h1>
              <p>
                {selected
                  ? date(selected.local_date)
                  : {
                      overview: "Всё, над чем ты работаешь, в одном месте.",
                      trainings:
                        "История выходов, маршрутов и маленьких побед.",
                      profile: "Один аккаунт для сайта и Telegram-бота.",
                    }[page]}
              </p>
            </div>
            {user && !busy ? (
              <button className="capture-open" onClick={() => setCapture(true)}>
                + Записать пролаз
              </button>
            ) : (
              <span className="heading-mark">
                <Mountain size={52} strokeWidth={1} />
              </span>
            )}
          </div>
          {user && !busy && (
            <TrainingControls
              csrf={csrf}
              demo={isDemo}
              timezone={user.timezone}
              refresh={retry}
              onChanged={() => setRetry((v) => v + 1)}
              onOpen={(t) => {
                setSelected(t);
                setPage("trainings");
              }}
            />
          )}
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
                      ["all", "Всё время"],
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
                  <div className="place-filters">
                    <label>
                      <span>Регион</span>
                      <select
                        disabled={isDemo}
                        value={filters.region}
                        onChange={(e) =>
                          setFilters({
                            ...filters,
                            region: e.target.value,
                            areaId: "",
                          })
                        }
                      >
                        <option value="">Все регионы</option>
                        {places.regions.map((region) => (
                          <option key={region} value={region}>
                            {region}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>Район</span>
                      <select
                        disabled={isDemo}
                        value={filters.areaId}
                        onChange={(e) =>
                          setFilters({ ...filters, areaId: e.target.value })
                        }
                      >
                        <option value="">Все районы</option>
                        {places.areas
                          .filter(
                            (area) =>
                              !filters.region || area.region === filters.region,
                          )
                          .map((area) => (
                            <option key={area.id} value={area.id}>
                              {area.name}
                              {!filters.region && area.region
                                ? ` · ${area.region}`
                                : ""}
                            </option>
                          ))}
                      </select>
                    </label>
                    {(filters.region || filters.areaId) && (
                      <button
                        className="text-button"
                        onClick={() =>
                          setFilters({ ...filters, region: "", areaId: "" })
                        }
                      >
                        Сбросить место
                      </button>
                    )}
                  </div>
                </div>
              )}
              {page === "overview" && !selected && (
                <div className="statistics-view">
                  <div>
                    <strong>Отображение статистики</strong>
                    <span>
                      {advanced
                        ? "Все показатели, графики и подробные таблицы"
                        : "Главное за выбранный период"}
                    </span>
                  </div>
                  <div
                    className="segments"
                    role="group"
                    aria-label="Режим статистики"
                  >
                    {(
                      [
                        ["simple", "Простой"],
                        ["advanced", "Расширенный"],
                      ] as const
                    ).map(([value, title]) => (
                      <button
                        key={value}
                        type="button"
                        className={statisticsView === value ? "chosen" : ""}
                        aria-pressed={statisticsView === value}
                        onClick={() => setStatisticsView(value)}
                      >
                        {title}
                      </button>
                    ))}
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
                            {trainingPlace(selected)} ·{" "}
                            {date(selected.local_date)}
                          </h2>
                          <p>
                            {trainingContext(selected)} ·{" "}
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
                                </div>
                                <span
                                  className={
                                    a.clean_ascent ? "badge clean" : "badge"
                                  }
                                >
                                  {a.clean_ascent === true
                                    ? "✓ Чисто"
                                    : a.reached_top === true
                                      ? a.clean_ascent === false
                                        ? "Дошёл до конца · не чисто"
                                        : "Дошёл до конца · чистота неизвестна"
                                      : a.reached_top === false
                                        ? "Не долез"
                                        : a.clean_ascent === false
                                          ? "Не чисто · результат неизвестен"
                                          : "Результат неизвестен"}
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
                            {counts.map(([title, value, Icon]) => (
                              <div
                                key={title}
                                className="kpi"
                              >
                                <div>
                                  <span>{title}</span>
                                  <Icon size={18} />
                                </div>
                                <strong>{value ?? "—"}</strong>
                                <small>
                                  За выбранный период
                                </small>
                              </div>
                            ))}
                          </div>
                          <BelaySummary summary={s} advanced={advanced} />
                          <div className="maxima">
                            <span className="max-label">ТВОЙ МАКСИМУМ</span>
                            {(advanced
                              ? [
                                  ["Пробовал", s?.maxAttemptedGrade],
                                  ["Дошёл до конца", s?.maxReachedTopGrade],
                                  ["Пролез чисто", s?.maxCompletedGrade],
                                ]
                              : [["Пролез чисто", s?.maxCompletedGrade]]
                            ).map(([title, g]) => (
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
                      {advanced &&
                        page === "overview" && (
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
                                  <ResponsiveContainer
                                    width="100%"
                                    height="100%"
                                  >
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
                            <Pyramid
                              grades={data?.grades ?? []}
                              filters={filters}
                              demo={isDemo}
                            />
                          </div>
                        )}
                      {!advanced && page === "overview" && (
                        <Pyramid grades={data?.grades ?? []} filters={filters} demo={isDemo} simple />
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
                                За выбранный период · с учётом региона, района и
                                категории
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
                              По выбранным фильтрам тренировок нет.
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
                                  <strong>{trainingPlace(t)}</strong>
                                  <span>{trainingContext(t)}</span>
                                  <span className="training-grades">
                                    Категории:{" "}
                                    {t.grades?.length
                                      ? t.grades.join(" · ")
                                      : "не указаны"}
                                  </span>
                                </div>
                                {t.duration_minutes != null && (
                                  <span className="training-duration">{t.duration_minutes} мин</span>
                                )}
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
          {capture && user && (
            <AttemptForm
              csrf={csrf}
              demo={isDemo}
              timezone={user.timezone}
              onClose={() => setCapture(false)}
              onSaved={() => {
                setCapture(false);
                setRetry((v) => v + 1);
              }}
            />
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
