import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Utterance = { start: number; end: number; text: string };
type Transcript = { segments: Utterance[]; utterances?: Utterance[] };
type Result = { transcript: Transcript; elapsed_s: number } | { error: string };
type Variant = { id: string; label: string; description: string };
type Results = Record<string, Result | null>;
const emptyResults: Results = {};
const windowSeconds = 30;

function groupByTime(result: Result | null | undefined) {
  const groups = new Map<number, Utterance[]>();
  if (!result || !("transcript" in result)) return groups;
  for (const line of result.transcript.utterances ?? result.transcript.segments) {
    const start = Math.floor(line.start / windowSeconds) * windowSeconds;
    const group = groups.get(start) ?? [];
    group.push(line);
    groups.set(start, group);
  }
  return groups;
}

function formatTime(seconds: number) {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [runVariants, setRunVariants] = useState<Variant[]>([]);
  const [activeVariant, setActiveVariant] = useState<string | null>(null);
  const [loadError, setLoadError] = useState("");
  const [playbackError, setPlaybackError] = useState("");
  const [recording, setRecording] = useState<string | null>(null);
  const [results, setResults] = useState<Results>(emptyResults);
  const player = useRef<HTMLAudioElement>(null);
  const groups = Object.fromEntries(runVariants.map(({ id }) => [id, groupByTime(results[id])]));
  const intervals = [...new Set(Object.values(groups).flatMap((group) => [...group.keys()]))].sort((a, b) => a - b);

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/variants").then(async (response) => {
      if (!response.ok) throw new Error("Не удалось загрузить варианты. Обновите страницу.");
      const items: Variant[] = await response.json();
      if (!cancelled) {
        setVariants(items);
        setSelected(items.map(({ id }) => id));
      }
    }).catch(() => {
      if (!cancelled) setLoadError("Не удалось загрузить варианты. Обновите страницу.");
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    return () => {
      if (recording) URL.revokeObjectURL(recording);
    };
  }, [recording]);

  async function transcribe(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy || !selected.length) return;
    const models = variants.filter(({ id }) => selected.includes(id));
    setRunVariants(models);

    setBusy(true);
    setPlaybackError("");
    setResults(emptyResults);
    setRecording(URL.createObjectURL(file));

    for (const { id } of models) {
      setActiveVariant(id);
      const body = new FormData();
      body.set("file", file);
      let result: Result;
      try {
        const response = await fetch(`/api/transcribe/${encodeURIComponent(id)}`, { method: "POST", body });
        if (!response.ok) {
          const failure: { detail?: unknown } | null = await response.json().catch(() => null);
          const message = typeof failure?.detail === "string" ? failure.detail : "Не удалось распознать запись.";
          throw new Error(message);
        }
        const payload: { transcript: Transcript; elapsed_s: number } = await response.json();
        result = payload;
      } catch (problem) {
        result = { error: problem instanceof TypeError
          ? "Не удалось связаться с сервисом."
          : problem instanceof Error ? problem.message : "Не удалось распознать запись." };
      }
      setResults((previous) => ({ ...previous, [id]: result }));
    }
    setActiveVariant(null);
    setBusy(false);
  }

  function playFrom(seconds: number) {
    const audio = player.current;
    if (!audio) return;
    setPlaybackError("");
    audio.currentTime = Math.max(0, seconds - 0.3);
    void audio.play().catch((problem: DOMException) => {
      if (problem.name !== "AbortError") setPlaybackError("Браузер не смог воспроизвести запись.");
    });
  }

  return (
    <main>
      <h1>Сравнение расшифровок</h1>

      <form className="upload" onSubmit={transcribe}>
        <label htmlFor="recording">Файл записи</label>
        <div className="upload-row">
          <input
            id="recording"
            type="file"
            accept=".mp3,.wav,.ogg,.m4a,.flac,.webm"
            disabled={busy}
            aria-describedby="formats"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setPlaybackError("");
              setRecording(null);
              setResults(emptyResults);
              setRunVariants([]);
            }}
          />
          <button className="submit" type="submit" disabled={!file || busy || !selected.length}>
            {busy ? "Распознаём…" : "Расшифровать"}
          </button>
        </div>
        <p className="hint" id="formats">MP3, WAV, OGG, M4A, FLAC, WebM</p>
        <fieldset className="variant-picker" disabled={busy}>
          <legend>Варианты для сравнения</legend>
          {variants.map(({ id, label, description }) => (
            <label className="variant-option" key={id}>
              <input type="checkbox" checked={selected.includes(id)} onChange={(event) => {
                setSelected((previous) => event.target.checked
                  ? [...previous, id] : previous.filter((value) => value !== id));
              }} />
              <span><strong>{label}</strong><span className="variant-description">{description}</span></span>
            </label>
          ))}
        </fieldset>
        {loadError && <p className="hint error" role="alert">{loadError}</p>}
        <p className="hint">{variants.length ? `Выбрано: ${selected.length}. ` : "Загружаем варианты… "}Прогоны идут по очереди; готовые тексты появляются сразу.</p>
      </form>

      {recording && (
        <div className="result" aria-label="Сравнение моделей">
          <div className="comparison-controls">
            <audio
              ref={player}
              src={recording}
              controls
              preload="metadata"
              aria-label="Запись звонка"
              onError={() => setPlaybackError("Браузер не смог открыть запись.")}
            />
            {playbackError && <p className="hint error" role="alert">{playbackError}</p>}
          </div>
          <div className="comparison-scroll" tabIndex={0} aria-label="Расшифровки, прокрутка по горизонтали">
          <div className="comparison-content" style={{ "--columns": runVariants.length } as CSSProperties}>
            <div className="comparison-grid model-headings">
              {runVariants.map(({ id, label, description }) => {
                const result = results[id];
                const error = result && "error" in result ? result.error : "";
                return (
                  <div key={id}>
                    <h2>{label}</h2>
                    <p className="variant-description">{description}</p>
                    <p className={`model-status${error ? " error" : ""}`} role={error ? "alert" : "status"}>
                      {error || (!result ? activeVariant === id ? "Распознаём…" : "В очереди"
                        : "transcript" in result
                          ? `${groups[id].size ? "Готово" : "Речь не распознана"} · ${result.elapsed_s.toFixed(1)} с`
                          : "") }
                    </p>
                  </div>
                );
              })}
            </div>
          {intervals.map((start) => (
            <section className="comparison-window" key={start} aria-label={formatTime(start)}>
              <button className="timecode window-time" onClick={() => playFrom(start)} type="button">
                {formatTime(start)}–{formatTime(start + windowSeconds)}
              </button>
              <div className="comparison-grid">
                {runVariants.map(({ id, label }) => (
                  <div className="model-column" key={id} aria-label={label}>
                    <h3 className="mobile-label">{label}</h3>
                    {groups[id].has(start) ? (
                      <ol className="transcript" role="list">
                        {groups[id].get(start)?.map((line, index) => (
                          <li key={`${line.start}-${index}`}>
                            <button className="timecode" type="button" onClick={() => playFrom(line.start)}
                              aria-label={`Воспроизвести с ${formatTime(line.start)}`}>
                              {formatTime(line.start)}
                            </button>
                            <span>{line.text}</span>
                          </li>
                        ))}
                      </ol>
                    ) : <span className="empty-interval" aria-label="Нет текста в этом интервале">—</span>}
                  </div>
                ))}
              </div>
            </section>
          ))}
          </div>
          </div>
        </div>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
