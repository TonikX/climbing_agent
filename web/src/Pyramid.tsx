import { useEffect, useRef, useState } from "react";
import {
  gradeAscents,
  type Filters,
  type Grade,
  type GradeAscentsPage,
  type PyramidBucket,
} from "./api";
import { demoPyramidPage } from "./pyramidDemo";
import "./pyramid.css";

const buckets: { id: PyramidBucket; name: string; color: string }[] = [
  { id: "onsight", name: "Onsight", color: "#1b8972" },
  { id: "flash", name: "Flash", color: "#c3972c" },
  { id: "redpoint", name: "Red Point", color: "#b7476c" },
  { id: "top_rope", name: "Верхняя (стиль)", color: "#5282a7" },
  { id: "other_clean", name: "Другой чистый", color: "#8b7d9f" },
  { id: "not_clean", name: "Без чистого пролаза", color: "#b8c0ad" },
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
    style: PyramidBucket | null;
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
          demoPyramidPage(grades, selection.grade, selection.style, offset),
        )
      : gradeAscents(
          filters,
          selection.grade,
          selection.style,
          offset,
          ac.signal,
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
  function choose(grade: string, style: PyramidBucket | null) {
    setPage(null);
    setOffset(0);
    setSelection({ grade, style });
    setFocusDetails(true);
  }
  const maximum = Math.max(1, ...grades.map((g) => g.routesCount ?? 0));
  return (
    <section className="panel pyramid-panel">
      <div className="section-heading">
        <div>
          <h2>Пирамида категорий</h2>
          <p>Выходы на трассы · выберите категорию или стиль</p>
        </div>
      </div>
      <p className="pyramid-note">
        Один выход на трассу — один сегмент. Стиль определяется по первому
        чистому пролазу в этой группе попыток. Повторы в другой тренировке
        считаются отдельно.
      </p>
      <div className="pyramid-legend">
        {buckets.map((b) => (
          <span key={b.id}>
            <i style={{ background: b.color }} />
            {b.name}
          </span>
        ))}
      </div>
      {!grades.length ? (
        <p className="empty">В выбранном периоде нет реальных пролазов.</p>
      ) : (
        grades.map((g) => (
          <div className="pyramid-row" key={g.grade}>
            <button
              className="pyramid-grade"
              onClick={() => choose(g.grade, null)}
              aria-label={`${g.grade}: все выходы, ${g.routesCount ?? 0}`}
              aria-pressed={selection?.grade === g.grade && !selection.style}
            >
              {g.grade}
              <small>{exits(g.routesCount ?? 0)}</small>
            </button>
            <div className="pyramid-body">
              <div className="pyramid-track">
                <div
                  className="pyramid-stack"
                  style={{
                    width: `${((g.routesCount ?? 0) / maximum) * 100}%`,
                  }}
                >
                  {buckets.map((b) => {
                    const count = g.pyramid?.[b.id] ?? 0;
                    return count > 0 ? (
                      <button
                        key={b.id}
                        style={{ flex: count, background: b.color }}
                        onClick={() => choose(g.grade, b.id)}
                        aria-label={`${g.grade}, ${b.name}: ${count}`}
                        title={`${b.name}: ${count}`}
                      />
                    ) : null;
                  })}
                </div>
              </div>
              <div className="pyramid-counts">
                {buckets.map((b) => (
                  <button
                    disabled={!g.pyramid?.[b.id]}
                    key={b.id}
                    onClick={() => choose(g.grade, b.id)}
                    aria-pressed={
                      selection?.grade === g.grade && selection.style === b.id
                    }
                  >
                    <i style={{ background: b.color }} />
                    {b.name}: <strong>{g.pyramid?.[b.id] ?? 0}</strong>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))
      )}
      <p className="pyramid-note">
        «Верхняя» здесь — сохранённый стиль. Страховка указана отдельно в
        записях. «Без чистого пролаза» включает попытки с неизвестной чистотой.
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
                {buckets.find((b) => b.id === selection.style)?.name ??
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
                    {names[a.style] ?? a.style} · страховка:{" "}
                    {names[a.belay] ?? a.belay}
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
