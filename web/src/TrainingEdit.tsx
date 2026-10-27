import { useEffect, useRef, useState, type FormEvent } from "react";
import { request, type Training } from "./api";
import "./training-controls.css";

export function TrainingEdit({
  training,
  csrf,
  demo,
  onClose,
  onSaved,
}: {
  training: Training;
  csrf: string;
  demo: boolean;
  onClose: () => void;
  onSaved: (training: Training) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const locked = useRef(false);
  const keys = useRef(new Map<string, string>());
  const [date, setDate] = useState(training.local_date);
  const [environment, setEnvironment] = useState(training.environment);
  const [duration, setDuration] = useState(
    training.duration_minutes?.toString() ?? "",
  );
  const [physical, setPhysical] = useState(training.physical_state ?? "");
  const [notes, setNotes] = useState(training.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (locked.current) return;
    const body = {
      expected_version: training.version,
      date,
      environment,
      duration_minutes: duration === "" ? null : Number(duration),
      physical_state: physical.trim() || null,
      notes: notes.trim() || null,
    };
    const fingerprint = JSON.stringify(body);
    if (!keys.current.has(fingerprint))
      keys.current.set(fingerprint, crypto.randomUUID());
    locked.current = true;
    setSaving(true);
    setError("");
    try {
      const updated = demo
        ? {
            ...training,
            ...body,
            local_date: date,
            version: training.version + 1,
          }
        : await request<Training>(
            `/trainings/${encodeURIComponent(training.id)}`,
            undefined,
            {
              method: "PATCH",
              csrf,
              body,
              key: keys.current.get(fingerprint),
            },
          );
      onSaved(updated);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      locked.current = false;
      setSaving(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="training-dialog"
      aria-labelledby="edit-training-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!locked.current) onClose();
      }}
    >
      <form onSubmit={save}>
        <h2 id="edit-training-title">Изменить тренировку</h2>
        <p>
          Изменения даты учтутся в статистике. Характеристики отдельных пролазов
          сохранятся.
        </p>
        {demo && <p>Демонстрация · изменения не сохраняются на сервере.</p>}
        <fieldset disabled={saving} className="training-edit-fields">
          <label>
            Дата
            <input
              type="date"
              required
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
          <label>
            Тип места
            <select
              value={environment}
              onChange={(e) => setEnvironment(e.target.value)}
            >
              <option value="outdoor">Скалы</option>
              <option value="indoor">Скалодром</option>
              <option value="unknown">Не указан</option>
            </select>
          </label>
          <label>
            Длительность, минут
            <input
              type="number"
              min="1"
              max="10080"
              step="1"
              value={duration}
              placeholder="Не указана"
              onChange={(e) => setDuration(e.target.value)}
            />
          </label>
          <label>
            Самочувствие
            <textarea
              maxLength={2000}
              rows={2}
              value={physical}
              onChange={(e) => setPhysical(e.target.value)}
            />
          </label>
          <label>
            Заметки
            <textarea
              maxLength={10000}
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
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
            disabled={saving || (!demo && !csrf)}
          >
            {saving ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
