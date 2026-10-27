import { useEffect, useRef, useState, type FormEvent } from "react";
import { editAttempt, request, type Attempt, type Training } from "./api";
import { CatalogField, type Entry } from "./AttemptForm";
import "./training-controls.css";

const styles = [
  ["unknown", "Не указан"],
  ["onsight", "Onsight"],
  ["flash", "Flash"],
  ["redpoint", "Red Point"],
  ["with_falls", "Со срывом"],
  ["with_hangs", "С зависанием"],
  ["not_reached", "Не долез"],
];
const belays = [
  ["lead", "Нижняя"],
  ["top_rope", "Верхняя"],
  ["auto_belay", "Автостраховка"],
  ["bouldering", "Боулдеринг"],
];
const fact = (value: boolean | null) => (value === null ? "" : String(value));

export function AttemptEdit({
  training,
  attempt,
  csrf,
  demo,
  onClose,
  onSaved,
}: {
  training: Training;
  attempt: Attempt;
  csrf: string;
  demo: boolean;
  onClose: () => void;
  onSaved: (training: Training) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const locked = useRef(false);
  const keys = useRef(new Map<string, string>());
  const [name, setName] = useState(attempt.route_snapshot.name ?? "");
  const [grade, setGrade] = useState(attempt.route_snapshot.grade ?? "");
  const [top, setTop] = useState(fact(attempt.reached_top));
  const [clean, setClean] = useState(fact(attempt.clean_ascent));
  const [style, setStyle] = useState(attempt.style);
  const [belay, setBelay] = useState(attempt.belay);
  const [falls, setFalls] = useState(attempt.falls?.toString() ?? "");
  const [hangs, setHangs] = useState(attempt.hangs?.toString() ?? "");
  const [notes, setNotes] = useState(attempt.notes ?? "");
  const [test, setTest] = useState(attempt.is_test);
  const [area, setArea] = useState<Entry>({
    name: demo ? (training.demoLocation ?? "") : "",
  });
  const [sector, setSector] = useState<Entry>({
    name: demo ? (training.demoSector ?? "") : "",
  });
  const [placeChanged, setPlaceChanged] = useState(false);
  const [loading, setLoading] = useState(!demo);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [placeError, setPlaceError] = useState("");
  const [retry, setRetry] = useState(0);
  const nonclean =
    top === "false" ||
    Number(falls) > 0 ||
    Number(hangs) > 0 ||
    ["with_falls", "with_hangs", "not_reached"].includes(style);
  useEffect(() => {
    dialog.current?.showModal();
    if (demo) return;
    const ac = new AbortController();
    setLoading(true);
    setPlaceError("");
    const areaId = attempt.route_snapshot.areaId;
    const sectorId = attempt.route_snapshot.sectorId;
    Promise.all([
      areaId
        ? request<Entry>(
            `/catalog/locations/${encodeURIComponent(areaId)}`,
            ac.signal,
          )
        : null,
      sectorId
        ? request<Entry>(
            `/catalog/sections/${encodeURIComponent(sectorId)}`,
            ac.signal,
          )
        : null,
    ])
      .then(([a, s]) => {
        if (ac.signal.aborted) return;
        if (a) setArea(a);
        if (s) setSector(s);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setPlaceError(e.message);
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort();
  }, [attempt.id, demo, retry]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (locked.current) return;
    if (
      (clean === "true" && nonclean) ||
      (["onsight", "flash", "redpoint"].includes(style) &&
        (nonclean || clean !== "true" || top !== "true"))
    ) {
      setError(
        "Срыв, зависание или недостижение конца исключают чистый пролаз и Onsight / Flash / Red Point.",
      );
      return;
    }
    if (placeChanged && (!area.name.trim() || !sector.name.trim())) {
      setError("Для изменения места укажите район и сектор.");
      return;
    }
    const values = {
      name: name.trim(),
      grade: grade.trim(),
      reached_top: top === "true",
      clean_ascent: clean === "true",
      style,
      belay,
      falls: falls === "" ? null : Number(falls),
      hangs: hangs === "" ? null : Number(hangs),
      notes: notes.trim() || null,
      is_test: test,
    };
    const before = {
      name: attempt.route_snapshot.name ?? "",
      grade: attempt.route_snapshot.grade ?? "",
      reached_top: attempt.reached_top,
      clean_ascent: attempt.clean_ascent,
      style: attempt.style,
      belay: attempt.belay,
      falls: attempt.falls,
      hangs: attempt.hangs,
      notes: attempt.notes,
      is_test: attempt.is_test,
    };
    const changes: Record<string, unknown> = {};
    for (const key of Object.keys(values) as (keyof typeof values)[]) {
      if (values[key] !== before[key]) changes[key] = values[key];
    }
    if (placeChanged)
      Object.assign(changes, {
        region: area.name.trim(),
        sector: sector.name.trim(),
      });
    if (!Object.keys(changes).length) {
      onClose();
      return;
    }
    const body = { ...changes, expected_version: training.version };
    const fingerprint = JSON.stringify(body);
    if (!keys.current.has(fingerprint))
      keys.current.set(fingerprint, crypto.randomUUID());
    locked.current = true;
    setSaving(true);
    setError("");
    try {
      if (demo) {
        const attempts = training.attempts.map((a) =>
          a.id !== attempt.id
            ? a
            : {
                ...a,
                ...values,
                route_snapshot: {
                  ...a.route_snapshot,
                  name: values.name,
                  grade: values.grade,
                },
              },
        );
        onSaved({
          ...training,
          attempts,
          version: training.version + 1,
          grades: [
            ...new Set(
              attempts
                .filter((a) => !a.is_test)
                .map((a) => a.route_snapshot.grade ?? ""),
            ),
          ].filter(Boolean),
        });
      } else {
        // Reload canonical domain values; the backend can normalize category and style.
        onSaved(
          await editAttempt(
            training.id,
            attempt.id,
            body,
            csrf,
            keys.current.get(fingerprint)!,
          ),
        );
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      locked.current = false;
      setSaving(false);
    }
  }
  function chooseStyle(value: string) {
    setStyle(value);
    if (["onsight", "flash", "redpoint"].includes(value)) {
      setTop("true");
      setClean("true");
    } else if (value === "not_reached") {
      setTop("false");
      setClean("false");
    } else if (["with_falls", "with_hangs"].includes(value)) setClean("false");
  }
  return (
    <dialog
      className="training-dialog"
      ref={dialog}
      aria-labelledby="edit-attempt-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!locked.current) onClose();
      }}
    >
      <form onSubmit={save}>
        <h2 id="edit-attempt-title">Изменить пролаз</h2>
        <p>
          Попытка №{attempt.sequence} · {training.local_date}
        </p>
        {demo && <p>Демонстрация · изменения не сохраняются на сервере.</p>}
        <fieldset disabled={saving} className="training-edit-fields">
          <label>
            Название трассы
            <input
              required
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Категория
            <input
              required
              maxLength={30}
              value={grade}
              placeholder="Например, 6a+"
              onChange={(e) => setGrade(e.target.value)}
            />
          </label>
          <details>
            <summary>Район и сектор</summary>
            {loading ? (
              <p role="status">Загружаем место…</p>
            ) : placeError ? (
              <p role="alert">
                {placeError}
                <button type="button" onClick={() => setRetry((v) => v + 1)}>
                  Повторить
                </button>
              </p>
            ) : (
              <>
                <CatalogField
                  title="Район"
                  kind="locations"
                  value={area}
                  demo={demo}
                  required={placeChanged}
                  onChange={(value) => {
                    setArea(value);
                    setSector({ name: "" });
                    setPlaceChanged(true);
                  }}
                />
                <CatalogField
                  title="Сектор"
                  kind="sections"
                  value={sector}
                  parent={area.id}
                  demo={demo}
                  required={placeChanged}
                  onChange={(value) => {
                    setSector(value);
                    setPlaceChanged(true);
                  }}
                />
              </>
            )}
          </details>
          <label>
            Дошёл до конца
            <select
              required
              value={top}
              onChange={(e) => {
                setTop(e.target.value);
                if (e.target.value === "false") {
                  setClean("false");
                  setStyle("not_reached");
                } else if (style === "not_reached") setStyle("unknown");
              }}
            >
              <option value="">Уточните</option>
              <option value="true">Да</option>
              <option value="false">Нет</option>
            </select>
          </label>
          <label>
            Пролез чисто
            <select
              required
              value={clean}
              onChange={(e) => {
                setClean(e.target.value);
                if (e.target.value === "true") setTop("true");
              }}
            >
              <option value="">Уточните</option>
              <option value="true" disabled={nonclean}>
                Да
              </option>
              <option value="false">Нет</option>
            </select>
          </label>
          <label>
            Стиль
            <select
              required
              value={styles.some(([value]) => value === style) ? style : ""}
              onChange={(e) => chooseStyle(e.target.value)}
            >
              <option value="">Уточните стиль</option>
              {styles.map(([value, title]) => (
                <option key={value} value={value}>
                  {title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Страховка
            <select
              required
              value={belay}
              onChange={(e) => setBelay(e.target.value)}
            >
              <option value="unknown">Уточните страховку</option>
              {belays.map(([value, title]) => (
                <option key={value} value={value}>
                  {title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Срывов
            <input
              type="number"
              min={0}
              max={1000}
              step={1}
              value={falls}
              onChange={(e) => {
                setFalls(e.target.value);
                if (Number(e.target.value) > 0) {
                  setClean("false");
                  setStyle("with_falls");
                }
              }}
              placeholder="Не указано"
            />
          </label>
          <label>
            Зависаний
            <input
              type="number"
              min={0}
              max={1000}
              step={1}
              value={hangs}
              onChange={(e) => {
                setHangs(e.target.value);
                if (Number(e.target.value) > 0) {
                  setClean("false");
                  if (!(Number(falls) > 0)) setStyle("with_hangs");
                }
              }}
              placeholder="Не указано"
            />
          </label>
          <label>
            Заметки
            <textarea
              maxLength={1000}
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          <label className="attempt-edit-test">
            <input
              type="checkbox"
              checked={test}
              onChange={(e) => setTest(e.target.checked)}
            />
            Тестовый пролаз (исключить из статистики)
          </label>
        </fieldset>
        {error && (
          <p role="alert" className="training-error">
            {error}
          </p>
        )}
        <div className="training-buttons">
          <button type="button" disabled={saving} onClick={onClose}>
            Отмена
          </button>
          <button
            type="submit"
            className="training-primary"
            disabled={saving || (!demo && !csrf) || !belays.some(([value]) => value === belay)}
          >
            {saving ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
