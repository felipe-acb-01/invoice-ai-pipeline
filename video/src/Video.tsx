// The 70-second product video. No voice: the story is told by captions over the real demo screens
// (captured from the live demo at 1920×1080) and two generic animations (an inbox and a spreadsheet).
import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import boxes from "../public/boxes.json";

const C = {
  bg: "#F5F6F8",
  surface: "#FFFFFF",
  ink: "#17202B",
  muted: "#5C6774",
  line: "#E2E5EA",
  accent: "#1C4E80",
  accentSoft: "#E6EEF7",
  ok: "#0F6A47",
  okSoft: "#E3F4EC",
  warn: "#9A5B00",
  warnSoft: "#FDF1DD",
  night: "#0F1720",
  nightText: "#D7E0EA",
  nightMuted: "#9AA6B2",
  nightSubtle: "#6F7C88",
  nightChip: "#1B2A38",
  nightChipText: "#CFE0F1",
  sky: "#9CC3E8",
  sheetHead: "#F1F3F6",
  rowHover: "#FBFCFD",
  shadow: "rgba(23,32,43,.12)",
  shadowDark: "rgba(15,23,32,.32)",
};
const FONT = '"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif';
const ease = Easing.bezier(0.33, 0, 0.2, 1);

type Box = { x: number; y: number; width: number; height: number };
const B = boxes as Record<string, Box>;
const center = (b: Box) => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 });

// ── Timeline (frames at 30 fps) ──────────────────────────────────────────────
const S = {
  title: { from: 0, len: 120 },
  inbox: { from: 110, len: 250 },
  run: { from: 350, len: 250 },
  queue: { from: 590, len: 360 },
  iva: { from: 940, len: 420 },
  photo: { from: 1350, len: 330 },
  stats: { from: 1670, len: 300 },
  end: { from: 1960, len: 180 },
};
export const TOTAL = S.end.from + S.end.len;

// ── Building blocks ──────────────────────────────────────────────────────────

/** Fades a scene in and out over its edges, with a slight rise. */
const Scene: React.FC<{ len: number; children: React.ReactNode; bg?: string }> = ({ len, children, bg = C.bg }) => {
  const f = useCurrentFrame();
  const opacity = interpolate(f, [0, 12, len - 12, len], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const rise = interpolate(f, [0, 14], [18, 0], { extrapolateRight: "clamp", easing: ease });
  return (
    <AbsoluteFill style={{ background: bg, opacity, transform: `translateY(${rise}px)`, fontFamily: FONT }}>
      {children}
    </AbsoluteFill>
  );
};

/** A caption card. `at` is the frame it appears; it stays until the scene ends. */
const Caption: React.FC<{ at: number; until?: number; children: React.ReactNode; place?: "top" | "bottom" }> = ({
  at,
  until = 99999,
  children,
  place = "top",
}) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inP = spring({ frame: f - at, fps, config: { damping: 200 } });
  const out = interpolate(f, [until, until + 10], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  if (f < at) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 96,
        [place]: 72,
        maxWidth: 1180,
        background: C.night,
        color: "#fff",
        padding: "22px 32px",
        borderRadius: 14,
        fontSize: 46,
        fontWeight: 600,
        letterSpacing: "-0.01em",
        lineHeight: 1.2,
        opacity: inP * out,
        transform: `translateY(${(1 - inP) * (place === "top" ? -16 : 16)}px)`,
        boxShadow: `0 12px 40px ${C.shadowDark}`,
      }}
    >
      {children}
    </div>
  );
};

type Cam = { f: number; x: number; y: number; s: number };

/** A screenshot under a moving camera: keyframes give the point to center and the zoom. */
const Screen: React.FC<{ src: string; cams: Cam[]; children?: React.ReactNode }> = ({ src, cams, children }) => {
  const f = useCurrentFrame();
  const frames = cams.map((c) => c.f);
  const pick = (k: "x" | "y" | "s") =>
    cams.length === 1
      ? cams[0][k]
      : interpolate(f, frames, cams.map((c) => c[k]), { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const s = pick("s");
  const x = pick("x");
  const y = pick("y");
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: C.bg }}>
      <div
        style={{
          position: "absolute",
          width: 1920,
          height: 1080,
          transformOrigin: "0 0",
          transform: `translate(${960 - x * s}px, ${540 - y * s}px) scale(${s})`,
        }}
      >
        <Img src={staticFile(`shots/${src}`)} style={{ width: 1920, height: 1080 }} />
        {children}
      </div>
    </AbsoluteFill>
  );
};

/** A pointer that glides between points (in screenshot coordinates) and clicks. */
const Cursor: React.FC<{ path: { f: number; x: number; y: number; click?: boolean }[]; until?: number }> = ({ path, until = 99999 }) => {
  const f = useCurrentFrame();
  if (f < path[0].f) return null;
  const fade = interpolate(f, [until, until + 8], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fs = path.map((p) => p.f);
  const x = interpolate(f, fs, path.map((p) => p.x), { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const y = interpolate(f, fs, path.map((p) => p.y), { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const clicks = path.filter((p) => p.click);
  return (
    <>
      {clicks.map((c, i) => {
        const t = f - c.f;
        if (t < 0 || t > 18) return null;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: c.x - 4 - t * 1.6,
              top: c.y - 4 - t * 1.6,
              width: 8 + t * 3.2,
              height: 8 + t * 3.2,
              borderRadius: "50%",
              border: `3px solid ${C.accent}`,
              opacity: 1 - t / 18,
            }}
          />
        );
      })}
      <svg style={{ position: "absolute", left: x, top: y, opacity: fade }} width="26" height="34" viewBox="0 0 26 34">
        <path d="M2 2 L2 28 L9 21 L14 32 L19 30 L14 19 L24 19 Z" fill={C.ink} stroke="#fff" strokeWidth="2.2" strokeLinejoin="round" />
      </svg>
    </>
  );
};

/** Two screenshots of the same screen, crossfading at frame `at` (e.g. before and after a click). */
const Swap: React.FC<{ a: string; b: string; at: number }> = ({ a, b, at }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [at, at + 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <>
      <Img src={staticFile(`shots/${a}`)} style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080 }} />
      <Img src={staticFile(`shots/${b}`)} style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, opacity: o }} />
    </>
  );
};

const Highlight: React.FC<{ box: Box; at: number; until: number }> = ({ box, at, until }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [at, at + 10, until, until + 10], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        left: box.x - 10,
        top: box.y - 10,
        width: box.width + 20,
        height: box.height + 20,
        borderRadius: 12,
        border: `4px solid ${C.accent}`,
        opacity: o,
      }}
    />
  );
};

// ── Scenes ───────────────────────────────────────────────────────────────────

const Title: React.FC = () => {
  const f = useCurrentFrame();
  const words = ["Invoices in.", "Approved data out.", "Nobody types."];
  return (
    <Scene len={S.title.len} bg={C.night}>
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: 160, gap: 6 }}>
        {words.map((w, i) => {
          const o = interpolate(f, [10 + i * 16, 24 + i * 16], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          return (
            <div key={w} style={{ color: i === 2 ? C.sky : "#fff", fontSize: 104, fontWeight: 700, letterSpacing: "-0.03em", opacity: o, transform: `translateX(${(1 - o) * -24}px)` }}>
              {w}
            </div>
          );
        })}
        <div style={{ color: C.nightMuted, fontSize: 34, marginTop: 28, opacity: interpolate(f, [62, 78], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
          An invoice pipeline with Claude, plain rules and a person who approves.
        </div>
      </AbsoluteFill>
    </Scene>
  );
};

const MAILS = [
  { from: "billing@northwind-cleaning.example", subject: "Invoice INV-2026-0790", file: "INV-2026-0790.pdf" },
  { from: "facturacion@soporte-andino.example", subject: "Factura electrónica N° 827", file: "factura-827.pdf" },
  { from: "accounts@harborlegal.example", subject: "Photo of our invoice", file: "IMG_2041.jpg" },
  { from: "receipts@atlas-telecom.example", subject: "Payment received, thank you", file: "receipt.pdf" },
];

const Clip: React.FC = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={C.muted} strokeWidth="2" strokeLinecap="round">
    <path d="M21 11.5 12.5 20a5 5 0 0 1-7-7l9-9a3.3 3.3 0 0 1 4.7 4.7l-9 9a1.7 1.7 0 0 1-2.4-2.4l8.3-8.3" />
  </svg>
);

const Inbox: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <Scene len={S.inbox.len}>
      <Caption at={8}>Invoices arrive by email: PDFs, scans, phone photos.</Caption>
      <div style={{ position: "absolute", left: 360, top: 260, width: 1200, background: C.surface, borderRadius: 16, border: `1px solid ${C.line}`, boxShadow: `0 20px 60px ${C.shadow}`, overflow: "hidden" }}>
        <div style={{ padding: "22px 30px", borderBottom: `1px solid ${C.line}`, display: "flex", justifyContent: "space-between", fontSize: 26 }}>
          <strong>Accounts payable inbox</strong>
          <span style={{ color: C.muted }}>{Math.min(4, Math.max(0, Math.floor((f - 30) / 28) + 1))} new</span>
        </div>
        {MAILS.map((m, i) => {
          const p = spring({ frame: f - 30 - i * 28, fps, config: { damping: 18, stiffness: 120 } });
          return (
            <div key={m.file} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 20, padding: "22px 30px", borderBottom: `1px solid ${C.line}`, opacity: p, transform: `translateY(${(1 - p) * -30}px)`, background: i === 0 ? C.rowHover : C.surface }}>
              <div>
                <div style={{ fontSize: 24, fontWeight: 600 }}>{m.from}</div>
                <div style={{ fontSize: 24, color: C.muted }}>{m.subject}</div>
              </div>
              <div style={{ alignSelf: "center", display: "flex", gap: 10, alignItems: "center", border: `1px solid ${C.line}`, borderRadius: 999, padding: "8px 16px", fontSize: 22, color: C.ink }}>
                <Clip /> {m.file}
              </div>
            </div>
          );
        })}
      </div>
    </Scene>
  );
};

// Real output of `python -m invoice_pipeline run` on the demo inbox (Claude Haiku 5.5).
const RUN = [
  "$ python -m invoice_pipeline run",
  "Gmail: 5 new messages, 5 attachments",
  "5 files: 4 queued for approval (1 with alerts), 0 could not be read, 1 not an invoice · US$ 0.0027",
  "Approval emails sent: 4",
];

const Run: React.FC = () => {
  const f = useCurrentFrame();
  const typed = Math.max(0, Math.floor((f - 24) * 1.4));
  return (
    <Scene len={S.run.len}>
      <Caption at={8}>Claude reads each one. Plain rules check the numbers.</Caption>
      <div style={{ position: "absolute", left: 96, top: 300, width: 1728, background: C.night, borderRadius: 16, padding: "40px 46px", fontFamily: '"SF Mono", Menlo, monospace', fontSize: 24, lineHeight: 1.75, color: C.nightText, boxShadow: `0 24px 70px ${C.shadowDark}` }}>
        <div style={{ color: C.sky }}>{RUN[0].slice(0, typed)}</div>
        {RUN.slice(1).map((line, i) => {
          const o = interpolate(f, [70 + i * 30, 78 + i * 30], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          return <div key={line} style={{ opacity: o }}>{line}</div>;
        })}
        <div style={{ marginTop: 26, display: "flex", gap: 14, fontFamily: FONT, fontSize: 24, opacity: interpolate(f, [170, 182], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
          {["Lines add up", "Tax matches", "No duplicates", "Is it an invoice?"].map((t) => (
            <span key={t} style={{ background: C.nightChip, color: C.nightChipText, borderRadius: 999, padding: "8px 18px" }}>{t}</span>
          ))}
        </div>
      </div>
    </Scene>
  );
};

const Queue: React.FC = () => {
  const closer = center(B.queue_closer);
  const row = center(B.queue_iva_row);
  return (
    <Scene len={S.queue.len}>
      <Screen
        src="queue.png"
        cams={[
          { f: 0, x: 960, y: 540, s: 1.0 },
          { f: 40, x: 960, y: 540, s: 1.18 },
          { f: 120, x: 960, y: closer.y + 150, s: 1.38 },
          { f: 200, x: 960, y: closer.y + 150, s: 1.38 },
          { f: 270, x: row.x + 420, y: row.y - 60, s: 1.45 },
        ]}
      >
        <Highlight box={B.queue_closer} at={120} until={210} />
        <Cursor path={[{ f: 230, x: row.x + 260, y: row.y + 120 }, { f: 290, x: row.x, y: row.y, click: true }, { f: 360, x: row.x, y: row.y }]} />
      </Screen>
      <Caption at={20} until={200} place="bottom">One approval queue. Every invoice goes through it.</Caption>
      <Caption at={212} place="bottom">The ones that need a closer look are marked.</Caption>
    </Scene>
  );
};

const NOTE = "IVA is $1.000 too high. Asked the vendor for a corrected invoice.";

const Iva: React.FC = () => {
  const f = useCurrentFrame();
  const alert = center(B.iva_alert);
  const note = B.iva_note;
  const reject = center(B.iva_reject);
  const typed = Math.max(0, Math.floor((f - 205) * 1.1));
  return (
    <Scene len={S.iva.len}>
      <Screen
        src="iva.png"
        cams={[
          { f: 0, x: 960, y: 540, s: 1.0 },
          { f: 50, x: alert.x - 120, y: alert.y + 40, s: 1.55 },
          { f: 90, x: alert.x, y: alert.y, s: 2.15 },
          { f: 170, x: alert.x, y: alert.y, s: 2.15 },
          { f: 220, x: note.x + note.width / 2, y: note.y + 40, s: 1.8 },
          { f: 330, x: note.x + note.width / 2, y: note.y + 40, s: 1.8 },
          { f: 380, x: 1290, y: 520, s: 1.45 },
        ]}
      >
        <Swap a="iva.png" b="iva_note.png" at={292} />
        {f >= 200 && f < 292 && (
          <div style={{ position: "absolute", left: note.x + 11, top: note.y + 9, width: note.width - 30, fontSize: 15.5, fontFamily: FONT, color: C.ink, background: C.surface, lineHeight: 1.5 }}>
            {NOTE.slice(0, typed)}
            <span style={{ opacity: Math.floor(f / 8) % 2 ? 0 : 1 }}>|</span>
          </div>
        )}
        {f >= 340 && (
          <Img src={staticFile("shots/iva_rejected.png")} style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, opacity: interpolate(f, [340, 350], [0, 1], { extrapolateRight: "clamp" }) }} />
        )}
        <Highlight box={B.iva_alert} at={90} until={175} />
        <Cursor path={[{ f: 180, x: note.x + 80, y: note.y + 120 }, { f: 200, x: note.x + 40, y: note.y + 30, click: true }, { f: 300, x: note.x + 120, y: note.y + 70 }, { f: 330, x: reject.x, y: reject.y, click: true }, { f: 420, x: reject.x + 10, y: reject.y + 10 }]} until={342} />
      </Screen>
      <Caption at={70} until={190} place="bottom">Every alert shows its numbers: no arithmetic for the approver.</Caption>
      <Caption at={200} until={335} place="bottom">Reject it, with a note that stays on record.</Caption>
      <Caption at={348} place="bottom">Who decided, when, and why.</Caption>
    </Scene>
  );
};

const SHEET_COLS = ["Vendor", "Invoice", "Issued", "Total", "Approved by", "Note"];
const SHEET_ROWS = [
  ["Quillwork Design Studio", "QW-2026866", "2026-10-17", "974.25", "Ana (AP)", "cost center 12"],
  ["Summit Payroll Services", "SPS-000170", "2026-10-05", "330.00", "Ana (AP)", ""],
];
const NEW_ROW = ["Harbor Legal Partners", "HLP/2026/369", "2026-10-15", "450.00", "Demo visitor", ""];

const Photo: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const doc = center(B.photo_doc);
  const total = center(B.photo_total);
  const approve = center(B.photo_approve);
  const sheetIn = spring({ frame: f - 175, fps, config: { damping: 200 } });
  const rowIn = spring({ frame: f - 215, fps, config: { damping: 16, stiffness: 140 } });
  return (
    <Scene len={S.photo.len}>
      <Screen
        src="photo.png"
        cams={[
          { f: 0, x: 960, y: 540, s: 1.0 },
          { f: 45, x: doc.x, y: doc.y - 60, s: 1.35 },
          { f: 95, x: total.x - 60, y: total.y + 60, s: 1.9 },
          { f: 140, x: approve.x + 160, y: approve.y - 60, s: 1.5 },
        ]}
      >
        <Cursor path={[{ f: 110, x: approve.x + 200, y: approve.y + 140 }, { f: 150, x: approve.x, y: approve.y, click: true }, { f: 200, x: approve.x, y: approve.y }]} until={172} />
      </Screen>
      <Caption at={15} until={150} place="bottom">A phone photo, read in 1.4 seconds for US$ 0.0004.</Caption>
      {f >= 170 && (
        <AbsoluteFill style={{ background: `rgba(245,246,248,${0.92 * sheetIn})` }}>
          <div style={{ position: "absolute", left: 210, top: 250, width: 1500, background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`, boxShadow: `0 24px 70px ${C.shadow}`, overflow: "hidden", opacity: sheetIn, transform: `translateY(${(1 - sheetIn) * 40}px)` }}>
            <div style={{ padding: "18px 26px", borderBottom: `1px solid ${C.line}`, fontSize: 26, fontWeight: 600, display: "flex", gap: 12, alignItems: "center" }}>
              <span style={{ width: 18, height: 18, borderRadius: 4, background: C.ok, display: "inline-block" }} /> Approved invoices
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1.1fr 1fr .8fr 1fr 1.2fr", fontSize: 23 }}>
              {SHEET_COLS.map((h) => (
                <div key={h} style={{ padding: "12px 18px", background: C.sheetHead, fontWeight: 600, color: C.muted, borderBottom: `1px solid ${C.line}` }}>{h}</div>
              ))}
              {SHEET_ROWS.flat().map((v, i) => (
                <div key={i} style={{ padding: "14px 18px", borderBottom: `1px solid ${C.line}`, textAlign: i % 6 === 3 ? "right" : "left" }}>{v}</div>
              ))}
              {NEW_ROW.map((v, i) => (
                <div key={`n${i}`} style={{ padding: "14px 18px", background: C.okSoft, opacity: rowIn, transform: `translateY(${(1 - rowIn) * 20}px)`, textAlign: i === 3 ? "right" : "left", fontWeight: 600 }}>{v}</div>
              ))}
            </div>
          </div>
        </AbsoluteFill>
      )}
      <Caption at={185} place="top">Approved: it's in the spreadsheet. Excel export too.</Caption>
    </Scene>
  );
};

const STATS = [
  { n: 104, suffix: "", label: "test documents, each with the right answer" },
  { n: 100, suffix: " %", label: "of fields read correctly by Claude Haiku" },
  { n: 0.7, suffix: "", label: "US$ per thousand invoices, roughly", decimals: 1 },
  { n: 51, suffix: "", label: "automated tests, run on every change" },
];

const Stats: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <Scene len={S.stats.len}>
      <Caption at={6}>Measured, not claimed.</Caption>
      <div style={{ position: "absolute", left: 96, right: 96, top: 330, display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 28 }}>
        {STATS.map((s, i) => {
          const p = spring({ frame: f - 25 - i * 14, fps, config: { damping: 200 } });
          const count = interpolate(f, [25 + i * 14, 75 + i * 14], [0, s.n], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
          return (
            <div key={s.label} style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 16, padding: "36px 32px", opacity: p, transform: `translateY(${(1 - p) * 24}px)` }}>
              <div style={{ fontSize: 96, fontWeight: 700, letterSpacing: "-0.03em", color: C.accent, fontVariantNumeric: "tabular-nums" }}>
                {count.toFixed(s.decimals ?? 0)}{s.suffix}
              </div>
              <div style={{ fontSize: 28, color: C.muted, lineHeight: 1.3 }}>{s.label}</div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 96, bottom: 110, fontSize: 28, color: C.muted, opacity: interpolate(f, [130, 145], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
        Chilean invoices with IVA · scans · phone photos · two-page invoices · quotes and receipts set aside
      </div>
    </Scene>
  );
};

const End: React.FC = () => {
  const f = useCurrentFrame();
  const o = (a: number) => interpolate(f, [a, a + 14], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Scene len={S.end.len} bg={C.night}>
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: 160, gap: 26, color: "#fff" }}>
        <div style={{ fontSize: 76, fontWeight: 700, letterSpacing: "-0.02em", opacity: o(6) }}>Try it with your own invoice.</div>
        <div style={{ fontSize: 38, color: C.sky, opacity: o(24) }}>invoice-pipeline-demo-production.up.railway.app</div>
        <div style={{ fontSize: 38, color: C.nightMuted, opacity: o(40) }}>github.com/felipe-acb-01/invoice-ai-pipeline</div>
        <div style={{ fontSize: 28, color: C.nightSubtle, marginTop: 20, opacity: o(56) }}>Python · Claude API · Gmail API · Google Sheets · FastAPI</div>
      </AbsoluteFill>
    </Scene>
  );
};

export const Demo: React.FC = () => (
  <AbsoluteFill style={{ background: C.bg }}>
    <Sequence from={S.title.from} durationInFrames={S.title.len}><Title /></Sequence>
    <Sequence from={S.inbox.from} durationInFrames={S.inbox.len}><Inbox /></Sequence>
    <Sequence from={S.run.from} durationInFrames={S.run.len}><Run /></Sequence>
    <Sequence from={S.queue.from} durationInFrames={S.queue.len}><Queue /></Sequence>
    <Sequence from={S.iva.from} durationInFrames={S.iva.len}><Iva /></Sequence>
    <Sequence from={S.photo.from} durationInFrames={S.photo.len}><Photo /></Sequence>
    <Sequence from={S.stats.from} durationInFrames={S.stats.len}><Stats /></Sequence>
    <Sequence from={S.end.from} durationInFrames={S.end.len}><End /></Sequence>
  </AbsoluteFill>
);
