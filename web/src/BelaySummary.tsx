import type { Summary } from "./api";

export function BelaySummary({ summary, advanced }: { summary?: Summary; advanced: boolean }) {
  return <section className="belay-summary panel" aria-label="Пролазы по страховке">
    <div className="section-heading"><div><h2>Пролазы по страховке</h2>
      <p>Трассы, на которых достигнут конец</p></div></div>
    <div className="belay-summary-grid">
      {([["lead", "Нижняя страховка"], ["top_rope", "Верхняя страховка"]] as const).map(([key, title]) => {
        const counts = summary?.reachedByBelay?.[key];
        return <article key={key} className="belay-summary-card">
          <span>{title}</span><strong>{counts?.total ?? "—"}<small> трасс</small></strong>
          {advanced && <dl>
            <div><dt>Чисто</dt><dd>{counts?.clean ?? "—"}</dd></div>
            <div><dt>Не чисто</dt><dd>{counts?.nonClean ?? "—"}</dd></div>
            <div><dt>Неизвестно</dt><dd>{counts?.unknownClean ?? "—"}</dd></div>
          </dl>}
        </article>;
      })}
    </div>
  </section>;
}
