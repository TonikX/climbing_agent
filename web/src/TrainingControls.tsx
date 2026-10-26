import { useEffect, useRef, useState } from "react";
import { activeTraining, request, type Training } from "./api";
import * as fixtures from "./demo";
import "./training-controls.css";

export function TrainingControls({
  csrf,
  demo,
  timezone,
  refresh,
  onChanged,
  onOpen,
}: {
  csrf: string;
  demo: boolean;
  timezone: string;
  refresh: number;
  onChanged: () => void;
  onOpen: (training: Training) => void;
}) {
  const [active, setActive] = useState<Training | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"start" | "finish" | null>(null);
  const [date, setDate] = useState(() =>
    new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()),
  );
  const [environment, setEnvironment] = useState("outdoor");
  const [retry, setRetry] = useState(0);
  const modal = useRef<HTMLDialogElement>(null);
  const locked = useRef(false);
  const keys = useRef(new Map<string, string>());
  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setError("");
    const load = demo
      ? Promise.resolve(
          fixtures.trainings.find((t) => t.status === "active") || null,
        )
      : activeTraining(ac.signal);
    load
      .then((t) => {
        if (!ac.signal.aborted) setActive(t);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort();
  }, [demo, refresh, retry]);
  useEffect(() => {
    if (mode) modal.current?.showModal();
  }, [mode]);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setSaving(true);
    setError("");
    const path =
      mode === "start"
        ? "/trainings"
        : `/trainings/${encodeURIComponent(active!.id)}/finish`;
    const body = mode === "start" ? { date, environment } : {};
    const fingerprint = path + JSON.stringify(body);
    if (!keys.current.has(fingerprint))
      keys.current.set(fingerprint, crypto.randomUUID());
    try {
      if (demo) {
        setActive(
          mode === "start"
            ? {
                ...fixtures.trainings[0],
                id: "demo-current",
                local_date: date,
                status: "active",
                attempts: [],
              }
            : null,
        );
        setMode(null);
      } else {
        await request(path, undefined, {
          method: "POST",
          csrf,
          body,
          key: keys.current.get(fingerprint),
        });
        setMode(null);
        onChanged();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      locked.current = false;
      setSaving(false);
    }
  }
  return (
    <section className="training-controls" aria-label="Управление тренировкой">
      <div>
        <strong>
          {loading
            ? "Проверяем тренировку…"
            : active
              ? "Тренировка идёт"
              : "Нет активной тренировки"}
        </strong>
        {active && !loading && (
          <small>
            {active.local_date} · {active.attempts.length} записей
          </small>
        )}
        {demo && <small>Демонстрация · изменения не сохраняются</small>}
      </div>
      {!loading && (
        <div className="training-buttons">
          {active ? (
            <>
              <button onClick={() => onOpen(active)}>Текущая тренировка</button>
              <button
                disabled={saving}
                onClick={() => {
                  setError("");
                  setMode("finish");
                }}
              >
                Завершить тренировку
              </button>
            </>
          ) : (
            <button
              className="training-primary"
              disabled={saving || !!error || (!demo && !csrf)}
              onClick={() => {
                keys.current.clear();
                setMode("start");
              }}
            >
              Начать тренировку
            </button>
          )}
        </div>
      )}
      {error && !mode && (
        <div role="alert" className="training-error">
          {error}{" "}
          <button onClick={() => setRetry((v) => v + 1)}>
            Повторить проверку
          </button>
        </div>
      )}
      {mode && (
        <dialog
          className="training-dialog"
          ref={modal}
          aria-labelledby="training-dialog-title"
          onCancel={(e) => {
            e.preventDefault();
            if (!saving) {
              setMode(null);
              setError("");
            }
          }}
        >
          <form onSubmit={save}>
            <h2 id="training-dialog-title">
              {mode === "start" ? "Начать тренировку" : "Завершить тренировку?"}
            </h2>
            {mode === "start" ? (
              <>
                <p>
                  Тренировка появится в журнале сразу. Пролазы можно добавить
                  позже на сайте или через бота.
                </p>
                <label>
                  Дата
                  <input
                    type="date"
                    required
                    value={date}
                    disabled={saving}
                    onChange={(e) => setDate(e.target.value)}
                  />
                </label>
                <label>
                  Место
                  <select
                    value={environment}
                    disabled={saving}
                    onChange={(e) => setEnvironment(e.target.value)}
                  >
                    <option value="outdoor">Скалы</option>
                    <option value="indoor">Скалодром</option>
                  </select>
                </label>
              </>
            ) : (
              <p>
                Тренировка за {active?.local_date} будет завершена. Если бот ещё
                обрабатывает записи, сначала дождитесь их сохранения.
              </p>
            )}
            {error && (
              <p role="alert" className="training-error">
                {error}
              </p>
            )}
            <div className="training-buttons">
              <button
                type="button"
                disabled={saving}
                onClick={() => {
                  setMode(null);
                  setError("");
                }}
              >
                Отмена
              </button>
              <button
                className="training-primary"
                disabled={saving}
                type="submit"
              >
                {saving
                  ? "Сохраняем…"
                  : mode === "start"
                    ? "Начать тренировку"
                    : "Завершить"}
              </button>
            </div>
          </form>
        </dialog>
      )}
    </section>
  );
}
