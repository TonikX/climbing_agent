import { useEffect, useRef, useState } from "react";
import {
  gradeAscents,
  type Filters,
  type Grade,
  type GradeAscentsPage,
  type AscentStyle,
} from "./api";
import { demoPyramidPage } from "./pyramidDemo";
import "./pyramid.css";

const buckets: { id: AscentStyle; name: string }[] = [
  { id: "onsight", name: "Onsight" },
  { id: "flash", name: "Flash" },
  { id: "redpoint", name: "Red Point" },
  { id: "with_falls", name: "Со срывом" },
  { id: "with_hangs", name: "С зависанием" },
  { id: "unknown", name: "Не указан" },
];
const belays = [
  { id: "lead", name: "Нижняя" },
  { id: "top_rope", name: "Верхняя" },
  { id: "auto_belay", name: "Автостраховка" },
  { id: "bouldering", name: "Без страховки / боулдеринг" },
  { id: "unknown", name: "Не указана" },
];
const names: Record<string, string> = {
  lead: "Нижняя",
  top_rope: "Верхняя",
  auto_belay: "Автостраховка",
  bouldering: "Боулдеринг",
  unknown: "Не указано",
  onsight: "Onsight",
  flash: "Flash",
  redpoint: "Red Point",
  with_falls: "Со срывом",
  with_hangs: "С зависанием",
};
const day = (value: string) =>
  new Date(value + "T12:00:00").toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
const exits = (count: number) =>
  `${count} ${{ one: "выход", few: "выхода", many: "выходов", other: "выхода", zero: "выходов", two: "выхода" }[new Intl.PluralRules("ru").select(count)]}`;
export function Pyramid({
  grades,
  filters,
  demo,
}: {
  grades: Grade[];
  filters: Filters;
  demo: boolean;
}) {
  const [selection, setSelection] = useState<{
    grade: string;
    style: AscentStyle | null;
    belay?: string;
  } | null>(null);
  const [page, setPage] = useState<GradeAscentsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const details = useRef<HTMLElement | null>(null);
  const [focusDetails, setFocusDetails] = useState(false);
  useEffect(() => {
    setSelection(null);
    setPage(null);
    setOffset(0);
  }, [filters]);
  useEffect(() => {
    if (!selection) return;
    const ac = new AbortController();
    setBusy(true);
    setError(null);
    if (offset === 0) setPage(null);
    const promise = demo
      ? Promise.resolve(
          demoPyramidPage(
            grades,
            selection.grade,
            selection.style,
            offset,
            selection.belay,
          ),
        )
      : gradeAscents(
          filters,
          selection.grade,
          selection.style,
          offset,
          ac.signal,
          selection.belay,
        );
    promise
      .then((next) => {
        if (!ac.signal.aborted)
          setPage((prev) =>
            offset > 0 && prev
              ? { ...next, items: [...prev.items, ...next.items] }
              : next,
          );
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!ac.signal.aborted) setBusy(false);
      });
    return () => ac.abort();
  }, [selection, filters, demo, grades, offset, retry]);
  useEffect(() => {
    if (focusDetails && selection) {
      details.current?.focus();
      details.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      setFocusDetails(false);
    }
  }, [focusDetails, selection]);
  function choose(grade: string, style: AscentStyle | null, belay?: string) {
    setPage(null);
    setOffset(0);
    setSelection({ grade, style, belay });
    setFocusDetails(true);
  }
  return (
    <section className="panel pyramid-panel">
      <div className="section-heading">
        <div>
          <h2>Категории, стили и страховка</h2>
          <p>Нажмите число, чтобы открыть соответствующие пролазы</p>
        </div>
      </div>
      <p className="pyramid-note">
        Один выход на трассу учитывается один раз: по первому чистому пролазу, а
        если его не было — по последней попытке. Стиль и страховка считаются
        отдельно.
      </p>
      {!grades.length ? (
        <p className="empty">Нет реальных пролазов за выбранный период.</p>
      ) : (
        <div className="table-wrap">
          <table className="category-style-table">
            <thead>
              <tr>
                <th>Категория</th>
                <th>Выходы</th>
                <th>Чисто</th>
                <th>Стиль</th>
                <th>Тип страховки</th>
              </tr>
            </thead>
            <tbody>
              {grades.map((g) => (
                <tr key={g.grade}>
                  <td>
                    <button
                      className="pyramid-grade"
                      onClick={() => choose(g.grade, null)}
                    >
                      {g.grade}
                    </button>
                  </td>
                  <td>{g.routesCount ?? 0}</td>
                  <td>{g.completedRoutes ?? 0}</td>
                  <td>
                    <div className="pyramid-counts">
                      {buckets.map((b) => (
                        <button
                          key={b.id}
                          disabled={!g.styles?.[b.id]}
                          aria-label={`${g.grade}, ${b.name}: ${g.styles?.[b.id] ?? 0}`}
                          onClick={() => choose(g.grade, b.id)}
                        >
                          {b.name}: <strong>{g.styles?.[b.id] ?? 0}</strong>
                        </button>
                      ))}
                    </div>
                  </td>
                  <td>
                    <div className="pyramid-counts">
                      {belays.map((b) => (
                        <button
                          key={b.id}
                          disabled={!g.belays?.[b.id]}
                          aria-label={`${g.grade}, страховка ${b.name}: ${g.belays?.[b.id] ?? 0}`}
                          onClick={() => choose(g.grade, null, b.id)}
                        >
                          {b.name}: <strong>{g.belays?.[b.id] ?? 0}</strong>
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="pyramid-note">
        В старых записях «Верхняя» могла быть сохранена как стиль. Здесь такой
        стиль показан как «Не указан», а страховка берётся из отдельного поля
        записи. Данные не изменяются.
      </p>
      {selection && (
        <section
          ref={details}
          tabIndex={-1}
          className="pyramid-details"
          aria-label="Пролазы выбранной категории"
        >
          <div className="section-heading">
            <div>
              <h2>
                {selection.grade} ·{" "}
                {(selection.belay
                  ? `Страховка: ${belays.find((b) => b.id === selection.belay)?.name}`
                  : buckets.find((b) => b.id === selection.style)?.name) ??
                  "Все стили"}
              </h2>
              <p>
                {page ? `${exits(page.total)} на трассы` : "Загружаем записи…"}{" "}
                · тот же период и фильтры
              </p>
            </div>
            <button className="text-button" onClick={() => setSelection(null)}>
              Закрыть
            </button>
          </div>
          {busy && <p role="status">Загрузка…</p>}
          {error && (
            <div role="alert">
              <p>{error}</p>
              <button
                className="secondary-button"
                onClick={() => setRetry((v) => v + 1)}
              >
                Повторить
              </button>
            </div>
          )}
          {!busy && !error && page?.items.length === 0 && (
            <p className="empty">Записей нет.</p>
          )}
          {page?.items.map((item) => (
            <article
              className="pyramid-ascent"
              key={item.trainingId + item.routeSessionKey}
            >
              <div className="section-heading">
                <div>
                  <h3>
                    {item.route.name ?? "Без названия"}{" "}
                    <span className="grade-chip">
                      {item.route.grade ?? "—"}
                    </span>
                  </h3>
                  <p>
                    {day(item.date)} ·{" "}
                    {[
                      item.location?.region,
                      item.location?.name,
                      item.sector?.name,
                    ]
                      .filter(Boolean)
                      .join(" · ") || "Место не указано"}
                  </p>
                </div>
                <span className={item.cleanAscent ? "badge clean" : "badge"}>
                  {item.cleanAscent
                    ? "Чисто"
                    : item.reachedTop
                      ? "Дошёл до конца"
                      : item.reachedTop === false
                        ? "Не долез"
                        : "Результат не уточнён"}
                </span>
              </div>
              <p className="pyramid-note">
                Стиль: {names[item.style] ?? item.style} · Страховка:{" "}
                {names[item.belay] ?? item.belay} · Попыток:{" "}
                {item.attemptsCount}
              </p>
              <details>
                <summary>Все попытки этого выхода</summary>
                {item.attempts.map((a) => (
                  <div className="pyramid-attempt" key={a.id}>
                    №{a.sequence} · попыток: {a.attempts} ·{" "}
                    {a.style === "top_rope"
                      ? "Не указан (старая запись)"
                      : (names[a.style] ?? a.style)}{" "}
                    · страховка: {names[a.belay] ?? a.belay}
                    <br />
                    Дошёл:{" "}
                    {a.reached_top === null
                      ? "не уточнено"
                      : a.reached_top
                        ? "да"
                        : "нет"}{" "}
                    · Чисто:{" "}
                    {a.clean_ascent === null
                      ? "не уточнено"
                      : a.clean_ascent
                        ? "да"
                        : "нет"}{" "}
                    · Срывы: {a.falls ?? "—"} · Зависания: {a.hangs ?? "—"}
                    {a.notes && <p>{a.notes}</p>}
                  </div>
                ))}
              </details>
            </article>
          ))}
          {page?.nextOffset != null && (
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => setOffset(page.nextOffset!)}
            >
              Показать ещё
            </button>
          )}
        </section>
      )}
    </section>
  );
}
