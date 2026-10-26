"use client";
import { useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
  Filter,
} from "lucide-react";
import { category, type Category, type XEvent } from "@/lib/xray-state";
export const eventTime = (value: string) =>
  new Date(value).toISOString().replace("T", " ").replace("Z", " UTC");
export function XrayTimeline({
  events,
  position,
  live,
  playing,
  speed,
  onSpeed,
  onPlay,
  onPause,
  onSeek,
  correlation,
  actorFilter,
  onClearActor,
  onSelect,
}: {
  events: XEvent[];
  position: number;
  live: boolean;
  playing: boolean;
  speed: number;
  onSpeed: (v: number) => void;
  onPlay: () => void;
  onPause: () => void;
  onSeek: (v: number) => void;
  correlation: string | null;
  actorFilter: string | null;
  onClearActor: () => void;
  onSelect: (e: XEvent) => void;
}) {
  const [filter, setFilter] = useState<Category | "All">("All"),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(0);
  const filtered = useMemo(
    () =>
      events.filter(
        (e) =>
          (filter === "All" || category(e) === filter) &&
          (!correlation || e.correlation_id === correlation) &&
          (!actorFilter ||
            e.source === actorFilter ||
            e.destination === actorFilter ||
            semanticActor(e) === actorFilter) &&
          (!query || e.correlation_id.includes(query)),
      ),
    [events, filter, correlation, query, actorFilter],
  );
  const maxPage = Math.max(0, Math.ceil(filtered.length / 40) - 1),
    currentPage = Math.min(page, maxPage),
    rows = filtered.slice(currentPage * 40, currentPage * 40 + 40);
  const current = events[position];
  return (
    <section className="xray-timeline" aria-label="X-Ray execution timeline">
      <div className="xray-timeline-heading">
        <div>
          <span className="xray-eyebrow">EXECUTION TIMELINE</span>
          <h2>Every transition has a record.</h2>
        </div>
        <span className="xray-muted">
          {position + 1} / {events.length} recorded security events · sequence{" "}
          {current?.sequence ?? "—"}
        </span>
      </div>
      <div className="xray-transport">
        <button
          aria-label="Restart replay"
          disabled={live || !events.length}
          onClick={() => {
            onPause();
            onSeek(-1);
          }}
        >
          <RotateCcw size={15} />
        </button>
        <button
          aria-label="Previous recorded event"
          disabled={live || position < 0}
          onClick={() => {
            onPause();
            onSeek(position - 1);
          }}
        >
          <SkipBack size={15} />
        </button>
        <button
          className="xray-play"
          aria-label={playing ? "Pause replay" : "Play replay"}
          disabled={live || !events.length}
          onClick={playing ? onPause : onPlay}
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button
          aria-label="Next recorded event"
          disabled={live || position >= events.length - 1}
          onClick={() => {
            onPause();
            onSeek(position + 1);
          }}
        >
          <SkipForward size={15} />
        </button>
        <label className="xray-speed">
          <span className="sr-only">Replay speed</span>
          <select
            aria-label="Replay speed"
            value={speed}
            disabled={live}
            onChange={(e) => onSpeed(Number(e.target.value))}
          >
            {[0.5, 1, 2, 4].map((n) => (
              <option key={n} value={n}>
                {n}×
              </option>
            ))}
          </select>
        </label>
        <input
          className="xray-scrubber"
          aria-label="Replay playhead"
          type="range"
          min={0}
          max={events.length}
          value={position + 1}
          disabled={live || !events.length}
          onChange={(e) => {
            onPause();
            onSeek(Number(e.target.value) - 1);
          }}
        />
        <time className="xray-play-time">
          {current ? eventTime(current.timestamp) : "Before first recorded event"}
        </time>
      </div>
      <p className="xray-time-note">
        {live
          ? "Live state follows server sequence. Select Recorded replay to inspect past transitions."
          : "Presentation time: idle gaps above 1.5 s compressed; minimum event dwell 60 ms. Original timestamps and recorded latency are unchanged. Sequence gaps can reflect restricted or unrecorded events."}
      </p>
      <div className="xray-timeline-filters">
        <Filter size={14} />
        <label>
          <span className="sr-only">Event category</span>
          <select
            aria-label="Event category"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value as Category | "All");
              setPage(0);
            }}
          >
            {[
              "All",
              "Case",
              "Policy",
              "Guard",
              "Inference",
              "Infrastructure",
              "Lifecycle",
              "Other",
            ].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <input
          aria-label="Filter correlation ID"
          placeholder="Filter correlation ID…"
          value={query}
          maxLength={36}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
        />
        {actorFilter && <button onClick={onClearActor}>Clear node filter</button>}
        <span>{filtered.length} matching · filters do not alter playback</span>
        <div className="xray-pagination">
          <button
            aria-label="Previous timeline page"
            disabled={!currentPage}
            onClick={() => setPage(Math.max(0, currentPage - 1))}
          >
            <ChevronLeft size={14} />
          </button>
          <span>
            {currentPage + 1}/{maxPage + 1}
          </span>
          <button
            aria-label="Next timeline page"
            disabled={currentPage >= maxPage}
            onClick={() => setPage(currentPage + 1)}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
      <div className="xray-marker-strip" aria-label="Recorded event markers">
        {rows.map((e) => (
          <button
            key={e.event_id}
            className={`xray-marker xray-category-${category(e).toLowerCase()} ${current?.event_id === e.event_id ? "xray-marker-current" : ""}`}
            aria-label={`Seek to event ${e.sequence}: ${e.event_type}`}
            title={`#${e.sequence} ${e.event_type}`}
            onClick={() => onSelect(e)}
          />
        ))}
      </div>
      <div className="xray-event-list" role="group" aria-label="Recorded forensic events">
        {rows.map((e) => (
          <button
            key={e.event_id}
            className={`xray-event-row ${current?.event_id === e.event_id ? "xray-event-selected" : ""}`}
            aria-label={`Inspect event ${e.sequence}: ${e.event_type}`}
            onClick={() => onSelect(e)}
          >
            <code>#{e.sequence}</code>
            <span className={`xray-category-pill xray-category-${category(e).toLowerCase()}`}>
              {category(e)}
            </span>
            <strong>{e.event_type}</strong>
            <span>
              {e.permitted_metadata.case_index != null
                ? `Case ${e.permitted_metadata.case_index + 1}`
                : e.permitted_metadata.probe_id || "Evaluation"}
            </span>
            <code>{e.correlation_id.slice(0, 8)}</code>
            <time>{e.timestamp.slice(11, 23)}</time>
          </button>
        ))}
      </div>
      {!rows.length && (
        <p className="xray-empty-inline">No permitted events match these filters.</p>
      )}
    </section>
  );
}
export function semanticActor(event: XEvent): string {
  const t = event.event_type;
  if (t.startsWith("MODEL_")) return "MODEL_WORKER";
  if (t === "INPUT_GUARD_EVALUATED") return "BLUE_INPUT_GUARD";
  if (t === "OUTPUT_GUARD_EVALUATED") return "BLUE_OUTPUT_GUARD";
  if (t === "ATTACK_CASE_STARTED" || t === "RESULT_RELEASED") return "RED_RUNNER";
  return "REFERENCE_MONITOR";
}
