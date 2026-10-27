import { useEffect, useId, useRef, useState } from "react";
import { X, Check, Search } from "lucide-react";
import { activeTraining, request, type Training } from "./api";
import "./attempt-form.css";

export type Entry = {
  id?: string;
  name: string;
  grade?: string | null;
  parent_id?: string | null;
  location?: string;
  section?: string | null;
};
type Kind = "locations" | "sections" | "routes";
const empty: Entry = { name: "" };
const styles = [
  ["onsight", "Onsight"],
  ["flash", "Flash"],
  ["redpoint", "Red Point"],
  ["with_falls", "Со срывом"],
  ["with_hangs", "С зависанием"],
  ["not_reached", "Не долез"],
  ["unknown", "Не указан"],
];
const belays = [
  ["lead", "Нижняя"],
  ["top_rope", "Верхняя"],
  ["auto_belay", "Автостраховка"],
  ["bouldering", "Боулдеринг"],
];

export function CatalogField({
  title,
  kind,
  value,
  parent,
  onChange,
  demo,
  required = true,
}: {
  title: string;
  kind: Kind;
  value: Entry;
  parent?: string;
  onChange: (v: Entry) => void;
  demo: boolean;
  required?: boolean;
}) {
  const id = useId();
  const [items, setItems] = useState<Entry[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const [next, setNext] = useState<number | null>(null);
  useEffect(() => {
    setOffset(0);
    setItems([]);
  }, [value.name, parent]);
  useEffect(() => {
    if (!open || value.id || demo) return;
    const ac = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      setError("");
      const q = new URLSearchParams({ q: value.name, offset: String(offset) });
      // Typed route names search the full catalogue; browse stays in the sector.
      if (parent && (kind !== "routes" || !value.name.trim()))
        q.set("parent_id", parent);
      request<{ items: Entry[]; next_offset: number | null }>(
        `/catalog-search/${kind}?${q}`,
        ac.signal,
      )
        .then((r) => {
          setItems((old) => (offset ? [...old, ...r.items] : r.items));
          setNext(r.next_offset);
        })
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          if (!ac.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      ac.abort();
    };
  }, [kind, value.name, value.id, parent, open, offset, demo]);
  return (
    <div
      className="capture-catalog"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null))
          setOpen(false);
      }}
    >
      <label htmlFor={id}>
        {title} {required && <span aria-hidden="true">*</span>}
      </label>
      <div className="capture-search">
        <Search size={16} />
        <input
          id={id}
          required={required}
          maxLength={200}
          autoComplete="off"
          value={value.name}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            onChange({ name: e.target.value });
            setOpen(true);
          }}
          placeholder="Найти в каталоге или ввести своё название"
        />
        {value.id && <Check size={16} aria-label="Выбрано из каталога" />}
      </div>
      {open && !value.id && (
        <div className="capture-options">
          {loading && <p role="status">Ищем…</p>}
          {error && <p role="alert">{error}</p>}
          {!loading && !items.length && (
            <p>
              {demo
                ? "В деморежиме доступен ручной ввод."
                : "Совпадений нет. Можно сохранить своё название."}
            </p>
          )}
          {items.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => {
                onChange(v);
                setOpen(false);
              }}
            >
              <strong>
                {v.name}
                {v.grade ? ` · ${v.grade}` : ""}
              </strong>
              <small>
                {[v.location, v.section].filter(Boolean).join(" · ")}
              </small>
            </button>
          ))}
          {next !== null && !loading && (
            <button type="button" onClick={() => setOffset(next)}>
              Ещё варианты
            </button>
          )}
          {value.name.trim() && (
            <button type="button" onClick={() => setOpen(false)}>
              Использовать своё название «{value.name.trim()}»
            </button>
          )}
        </div>
      )}
      <small>
        {value.id
          ? "Выбрано из БД"
          : "Новое название сохранится в личном каталоге"}
      </small>
    </div>
  );
}

export function AttemptForm({
  csrf,
  demo,
  timezone,
  onClose,
  onSaved,
}: {
  csrf: string;
  demo: boolean;
  timezone?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [training, setTraining] = useState<Training | null>(null);
  const [ready, setReady] = useState(demo);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [area, setArea] = useState<Entry>(empty);
  const [sector, setSector] = useState<Entry>(empty);
  const [route, setRoute] = useState<Entry>(empty);
  const [grade, setGrade] = useState("");
  const [top, setTop] = useState("");
  const [clean, setClean] = useState("");
  const [style, setStyle] = useState("");
  const [belay, setBelay] = useState("");
  const [attempts, setAttempts] = useState("1");
  const [falls, setFalls] = useState("");
  const [hangs, setHangs] = useState("");
  const [notes, setNotes] = useState("");
  const [test, setTest] = useState(false);
  const [environment, setEnvironment] = useState("outdoor");
  const [date, setDate] = useState(() =>
    new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone || "Europe/Moscow",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()),
  );
  const keys = useRef(new Map<string, string>());
  const pending = useRef(false);
  const hierarchy = useRef(0);
  useEffect(() => {
    dialog.current?.showModal();
    const ac = new AbortController();
    if (!demo)
      (async () => {
        const active = await activeTraining(ac.signal);
        if (!ac.signal.aborted) setTraining(active);
        setReady(true);
      })().catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => ac.abort();
  }, [demo]);
  const nonclean =
    Number(falls) > 0 ||
    Number(hangs) > 0 ||
    style === "with_falls" ||
    style === "with_hangs" ||
    style === "not_reached" ||
    top === "false";
  const cleanStyle = ["onsight", "flash", "redpoint"].includes(style);
  useEffect(() => {
    if (nonclean) setClean("false");
    else if (cleanStyle) {
      setClean("true");
      setTop("true");
    }
  }, [nonclean, cleanStyle]);
  async function chooseRoute(v: Entry) {
    const generation = ++hierarchy.current;
    setRoute(v);
    if (!v.id || !v.parent_id) return;
    setBusy(true);
    setError("");
    try {
      const s = await request<{ id: string; name: string; areaId: string }>(
        "/catalog/sections/" + encodeURIComponent(v.parent_id),
      );
      const a = await request<Entry>(
        "/catalog/locations/" + encodeURIComponent(s.areaId),
      );
      if (generation !== hierarchy.current) return;
      setArea(a);
      setSector(s);
      setGrade(v.grade || "");
    } catch (e) {
      setRoute(empty);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function write<T>(path: string, body: unknown): Promise<T> {
    const fingerprint = path + JSON.stringify(body);
    if (!keys.current.has(fingerprint))
      keys.current.set(fingerprint, crypto.randomUUID());
    return request<T>(path, undefined, {
      method: "POST",
      csrf,
      body,
      key: keys.current.get(fingerprint),
    });
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pending.current) return;
    if (cleanStyle && (nonclean || clean === "false")) {
      setError(
        "Onsight, Flash и Red Point требуют чистого пролаза без срывов и зависаний.",
      );
      return;
    }
    if (
      !area.name.trim() ||
      !sector.name.trim() ||
      !route.name.trim() ||
      !grade.trim()
    ) {
      setError("Укажите район, сектор, трассу и категорию.");
      return;
    }
    if (demo) {
      setSaved(true);
      return;
    }
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await write("/web-attempts", {
        date,
        environment,
        training_id: training?.id || null,
        location_id: area.id || null,
        section_id: sector.id || null,
        region: area.name.trim(),
        sector: sector.name.trim(),
        route_id: route.id || null,
        name: route.name.trim(),
        grade: grade.trim(),
        reached_top: top === "true",
        clean_ascent: clean === "true",
        style,
        belay,
        attempts: Number(attempts),
        ...(falls !== "" ? { falls: Number(falls) } : {}),
        ...(hangs !== "" ? { hangs: Number(hangs) } : {}),
        notes: notes.trim() || null,
        is_test: test,
      });
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <dialog
      className="capture-dialog"
      ref={dialog}
      aria-labelledby="capture-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) (saved && !demo ? onSaved : onClose)();
      }}
    >
      <div className="capture-heading">
        <div>
          <span className="eyebrow">ЖУРНАЛ ТРЕНИРОВОК</span>
          <h2 id="capture-title">
            {saved ? "Пролаз записан" : "Записать пролаз"}
          </h2>
        </div>
        <button
          type="button"
          aria-label="Закрыть форму"
          disabled={busy}
          onClick={saved && !demo ? onSaved : onClose}
        >
          <X size={22} />
        </button>
      </div>
      {saved ? (
        <div className="capture-success">
          <Check size={40} />
          <h3>
            {route.name} · {grade}
          </h3>
          <p>
            {demo
              ? "Это демонстрация. Данные не отправлялись на сервер."
              : "Запись сохранена в вашем журнале. Она также доступна в Telegram-боте."}
          </p>
          <button className="capture-submit" onClick={demo ? onClose : onSaved}>
            Вернуться в журнал
          </button>
        </div>
      ) : (
        <form onSubmit={submit}>
          <p className="capture-intro">
            Запишите результат, пока помните детали. Поля со звёздочкой
            обязательны.
          </p>
          {demo && (
            <p className="capture-notice">
              Деморежим · сохранение только для предпросмотра
            </p>
          )}
          {error && (
            <p className="capture-error" role="alert">
              {error}
            </p>
          )}
          <fieldset disabled={busy || !ready}>
            <div className="capture-training">
              {!ready ? (
                "Проверяем текущую тренировку…"
              ) : training ? (
                <>
                  Текущая тренировка · {training.local_date}
                  <small>Пролаз добавится в активную тренировку.</small>
                </>
              ) : (
                <>
                  Новая тренировка
                  <small>Начнётся при сохранении пролаза.</small>
                  <div className="capture-grid">
                    <label>
                      Дата *
                      <input
                        required
                        type="date"
                        value={date}
                        onChange={(e) => setDate(e.target.value)}
                      />
                    </label>
                    <label>
                      Место
                      <select
                        value={environment}
                        onChange={(e) => setEnvironment(e.target.value)}
                      >
                        <option value="outdoor">Скалы</option>
                        <option value="indoor">Скалодром</option>
                      </select>
                    </label>
                  </div>
                </>
              )}
            </div>
            <h3>Трасса</h3>
            <div className="capture-grid">
              <CatalogField
                title="Район"
                kind="locations"
                value={area}
                demo={demo}
                onChange={(v) => {
                  hierarchy.current++;
                  setArea(v);
                  setSector(empty);
                  setRoute(empty);
                }}
              />
              <CatalogField
                title="Сектор"
                kind="sections"
                value={sector}
                parent={area.id}
                demo={demo}
                onChange={(v) => {
                  hierarchy.current++;
                  setSector(v);
                  setRoute(empty);
                }}
              />
              <CatalogField
                title="Название трассы"
                kind="routes"
                value={route}
                parent={sector.id}
                demo={demo}
                onChange={chooseRoute}
              />
              <label>
                Категория *
                <input
                  required
                  maxLength={30}
                  placeholder="Например, 6a+ или 6B/6B+"
                  value={grade}
                  onChange={(e) => setGrade(e.target.value)}
                />
              </label>
            </div>
            <h3>Результат</h3>
            <div className="capture-grid">
              <label>
                Дошёл до конца *
                <select
                  required
                  value={top}
                  onChange={(e) => {
                    const value = e.target.value;
                    setTop(value);
                    if (value === "false") {
                      setStyle("not_reached");
                      setClean("false");
                    } else if (style === "not_reached") setStyle("");
                  }}
                >
                  <option value="">Выберите</option>
                  <option value="true">Да</option>
                  <option value="false">Нет</option>
                </select>
              </label>
              <label>
                Пролез чисто *
                <select
                  required
                  value={clean}
                  onChange={(e) => {
                    setClean(e.target.value);
                    if (e.target.value === "true") setTop("true");
                  }}
                >
                  <option value="">Выберите</option>
                  <option value="true" disabled={nonclean}>
                    Да
                  </option>
                  <option value="false">Нет</option>
                </select>
              </label>
              <label>
                Стиль *
                <select
                  required
                  value={style}
                  onChange={(e) => {
                    const value = e.target.value;
                    setStyle(value);
                    if (value === "not_reached") {
                      setTop("false");
                      setClean("false");
                    } else if (style === "not_reached") {
                      setTop("");
                      if (cleanStyle) setClean("");
                    }
                  }}
                >
                  <option value="">Выберите</option>
                  {styles.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Тип страховки *
                <select
                  required
                  value={belay}
                  onChange={(e) => setBelay(e.target.value)}
                >
                  <option value="">Выберите</option>
                  {belays.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="capture-hint">
              Onsight / Flash / Red Point означают чистый пролаз. Срыв или
              зависание исключают чистоту.
            </p>
            <div className="capture-grid capture-counts">
              {[
                ["Попыток *", attempts, setAttempts, 1, 100],
                ["Срывов", falls, setFalls, 0, 1000],
                ["Зависаний", hangs, setHangs, 0, 1000],
              ].map(([label, value, setter, min, max]) => (
                <label key={String(label)}>
                  {String(label)}
                  <input
                    type="number"
                    min={Number(min)}
                    max={Number(max)}
                    step="1"
                    required={min === 1}
                    value={String(value)}
                    placeholder="Не указано"
                    onChange={(e) =>
                      (setter as (s: string) => void)(e.target.value)
                    }
                  />
                </label>
              ))}
            </div>
            <label>
              Комментарий
              <textarea
                maxLength={1000}
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Что получилось, над чем поработать в следующий раз…"
              />
            </label>
            <label className="capture-check">
              <input
                type="checkbox"
                checked={test}
                onChange={(e) => setTest(e.target.checked)}
              />
              Тестовый пролаз — не учитывать в статистике
            </label>
          </fieldset>
          <div className="capture-footer">
            <button type="button" disabled={busy} onClick={onClose}>
              Отмена
            </button>
            <button
              className="capture-submit"
              disabled={busy || !ready || (!demo && !csrf)}
              type="submit"
            >
              {busy ? "Сохраняем…" : "Сохранить пролаз"}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
