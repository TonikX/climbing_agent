import type { Summary } from "./api";

export function BelaySummary({
  summary,
  advanced,
}: {
  summary?: Summary;
  advanced: boolean;
}) {
  return (
    <section
      className="belay-summary panel"
      aria-label="Трассы и пролазы по страховке"
    >
      <div className="section-heading">
        <div>
          <h2>Трассы и пролазы по страховке</h2>
          <p>
            Только с достижением конца. Повторное прохождение — ещё один пролаз.
            Одна трасса может попасть в несколько групп страховки.
          </p>
        </div>
      </div>
      <div className="belay-summary-grid">
        {(
          [
            ["lead", "Нижняя страховка"],
            ["top_rope", "Верхняя страховка"],
            ["auto_belay", "Автостраховка"],
            ["bouldering", "Боулдеринг"],
            ["unknown", "Страховка не указана"],
          ] as const
        )
          .filter(
            ([key]) =>
              key === "lead" ||
              key === "top_rope" ||
              (summary?.ascentsByBelay?.[key]?.total ?? 0) > 0,
          )
          .map(([key, title]) => {
            const routes = summary?.reachedByBelay?.[key];
            const ascents = summary?.ascentsByBelay?.[key];
            return (
              <article key={key} className="belay-summary-card">
                <span>{title}</span>
                <strong>
                  {ascents?.total ?? "—"}
                  <small> пролазов</small>
                </strong>
                <p>{routes?.total ?? "—"} трасс с достижением конца</p>
                {advanced && (
                  <dl>
                    <div>
                      <dt>Чистых пролазов</dt>
                      <dd>{ascents?.clean ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>Не чисто</dt>
                      <dd>{ascents?.nonClean ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>Чистота неизвестна</dt>
                      <dd>{ascents?.unknownClean ?? "—"}</dd>
                    </div>
                  </dl>
                )}
              </article>
            );
          })}
      </div>
      <p className="capture-hint">
        Пролаз считается по отдельной сохранённой записи. Число попыток в
        объединённой записи не означает столько же достижений конца.
      </p>
    </section>
  );
}
