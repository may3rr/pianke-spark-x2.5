// Inline SVG, SF-Symbols "fill" style (fill="currentColor"); strokes only
// for the checkmark draw. Colors come from CSS variables.

interface IconProps {
  size?: number
  color?: string
}

function Fill({
  size = 18,
  color = 'currentColor',
  children,
  viewBox = '0 0 24 24',
}: IconProps & { children: React.ReactNode; viewBox?: string }) {
  return (
    <svg width={size} height={size} viewBox={viewBox} fill={color} aria-hidden style={{ flex: 'none', display: 'block' }}>
      {children}
    </svg>
  )
}

export function MoonFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M14.1 2.1a.9.9 0 0 0-1.1 1.1 7.6 7.6 0 0 1-9.8 9.8.9.9 0 0 0-1.1 1.1A10 10 0 1 0 14.1 2.1z" />
      <path d="M18.1 2.7l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4-1.4-.5 1.4-.5zM20.5 8.1l.3.9.9.3-.9.3-.3.9-.3-.9-.9-.3.9-.3z" />
    </Fill>
  )
}

export function BookmarkFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M6.5 2.5h11A1.5 1.5 0 0 1 19 4v16.6a.9.9 0 0 1-1.4.7L12 17.4l-5.6 3.9a.9.9 0 0 1-1.4-.7V4a1.5 1.5 0 0 1 1.5-1.5z" />
    </Fill>
  )
}

export function CheckCircleFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm4.7 6.3a1 1 0 0 0-1.4.1l-4.4 5.1-2.2-2.2a1 1 0 1 0-1.4 1.4l3 3a1 1 0 0 0 1.5-.1l5-5.9a1 1 0 0 0-.1-1.4z"
      />
    </Fill>
  )
}

export function SparklesFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M10.35 4.6l1.6 4.6a3 3 0 0 0 1.8 1.8l4.6 1.6-4.6 1.6a3 3 0 0 0-1.8 1.8l-1.6 4.6-1.6-4.6a3 3 0 0 0-1.8-1.8l-4.6-1.6 4.6-1.6a3 3 0 0 0 1.8-1.8z" />
      <path d="M18.85 3.1l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7zM18.85 16.6l.6 1.6 1.6.6-1.6.6-.6 1.6-.6-1.6-1.6-.6 1.6-.6z" />
    </Fill>
  )
}

export function GearFillIcon(p: IconProps) {
  // six teeth around (12, 12); the thin stroke rounds the tooth corners
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        stroke={p.color ?? 'currentColor'}
        strokeWidth={0.9}
        strokeLinejoin="round"
        d="M9.62 4.47L10.14 1.97L13.86 1.97L14.38 4.47A7.9 7.9 0 0 1 17.34 6.18L19.76 5.38L22.03 8.60L19.71 10.29A7.9 7.9 0 0 1 19.71 13.71L22.03 15.40L19.76 18.62L17.34 17.82A7.9 7.9 0 0 1 14.38 19.53L13.86 22.03L10.14 22.03L9.62 19.53A7.9 7.9 0 0 1 6.66 17.82L4.24 18.62L1.97 15.40L4.29 13.71A7.9 7.9 0 0 1 4.29 10.29L1.97 8.60L4.24 5.38L6.66 6.18A7.9 7.9 0 0 1 9.62 4.47ZM12 8.4a3.6 3.6 0 1 0 0 7.2a3.6 3.6 0 1 0 0-7.2z"
      />
    </Fill>
  )
}

export function FilmFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M4 3h16a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zm0 2v2h2V5zm0 4v2h2V9zm0 4v2h2v-2zm0 4v2h2v-2zM18 5v2h2V5zm0 4v2h2V9zm0 4v2h2v-2zm0 4v2h2v-2zM8 5v6h8V5zm0 8v6h8v-6z"
      />
    </Fill>
  )
}

export function LockFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M12 2a5 5 0 0 1 5 5v3h.5A2.5 2.5 0 0 1 20 12.5v7a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 19.5v-7A2.5 2.5 0 0 1 6.5 10H7V7a5 5 0 0 1 5-5zm0 2a3 3 0 0 0-3 3v3h6V7a3 3 0 0 0-3-3z"
      />
    </Fill>
  )
}

export function CpuFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M9 1.5h1.5V4h3V1.5H15V4h1a3 3 0 0 1 3 3v1h2.5v1.5H19v5h2.5V16H19v1a3 3 0 0 1-3 3h-1v2.5h-1.5V20h-3v2.5H9V20H8a3 3 0 0 1-3-3v-1H2.5v-1.5H5v-5H2.5V8H5V7a3 3 0 0 1 3-3h1zM9 8.5a.5.5 0 0 0-.5.5v6c0 .3.2.5.5.5h6c.3 0 .5-.2.5-.5V9a.5.5 0 0 0-.5-.5z"
      />
    </Fill>
  )
}

export function WifiSlashFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M3.3 2.3l18.4 18.4-1.4 1.4-6.2-6.2a2.6 2.6 0 1 1-3.4 3.3L2 6.5l1.3-1.3zM12 4.5c3.8 0 7.3 1.5 9.9 4l-1.6 1.6A11.6 11.6 0 0 0 9 7l-2.3-2c1.7-.4 3.5-.5 5.3-.5zm0 4.5c2.6 0 5 1 6.7 2.8l-1.6 1.6a7.3 7.3 0 0 0-3.9-2.1zM5.3 8.6l1.5 1.5c-.5.3-1 .7-1.5 1.1L3.7 9.6c.5-.4 1-.7 1.6-1zm3.2 3.2l1.6 1.6c-.6.2-1.1.6-1.6 1l-1.6-1.6c.5-.4 1-.7 1.6-1z" />
    </Fill>
  )
}

export function BooksFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M4.9 4.5h2.6a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H4.9a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1zm5.4 0h2.6a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-2.6a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1zm3.6 3.26l3.72-.79 2.5 11.74-3.72.79z" />
    </Fill>
  )
}

export function QuoteFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M4 14C4 9.5 6.5 6.5 10 5.5l.7 1.6C9.1 8 7.9 9.5 7.7 11.5H10v7H4zm9.5 0c0-4.5 2.5-7.5 6-8.5l.7 1.6c-2.1.9-3.3 2.4-3.5 4.4h2.8v7h-6z" />
    </Fill>
  )
}

export function PlusIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M11 4h2v7h7v2h-7v7h-2v-7H4v-2h7z" />
    </Fill>
  )
}

export function XmarkIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M4.5 4.5h2.9l12.1 12.1v2.9h-2.9L4.5 7.4zM19.5 4.5v2.9L7.4 19.5H4.5v-2.9L16.1 4.5z" />
    </Fill>
  )
}

export function PencilFillIcon(p: IconProps) {
  // 45° pencil in three pieces: graphite tip, white band, body — the band
  // sits right behind the tip, not mid-pencil
  return (
    <Fill {...p}>
      <path d="M4.3 20.5l.85-3.96 3.11 3.11zM6.49 15.2l9.97-9.98 1.7-1.7 1.42 4.82-9.98 9.97z" />
    </Fill>
  )
}

export function ArrowClockwiseIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M19.8 9.16A8.3 8.3 0 1 1 16.64 5.12L15.52 6.78A6.3 6.3 0 1 0 17.92 9.85zM15.34 8.02L20.06 9.24 18.04 4.8z" />
    </Fill>
  )
}

export function PersonFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M12 3a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9zm0 10.5c4.4 0 8 2.4 8 5.4V21H4v-2.1c0-3 3.6-5.4 8-5.4z" />
    </Fill>
  )
}

export function HandThumbDownFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M8.4 3.4h8.8a3 3 0 0 1 2.9 2.2l1.6 6.3A2 2 0 0 1 19.8 14.4H14.4l.8 3.5a2.3 2.3 0 0 1-4.1 1.8L7.4 14.2V4.4a1 1 0 0 1 1-1zM2.9 4.4h2.5v10H2.9a.5.5 0 0 1-.5-.5v-9a.5.5 0 0 1 .5-.5z" />
    </Fill>
  )
}

export function ChevronRightIcon({ size = 12 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden style={{ flex: 'none' }}>
      <path d="M4.2 2.5L7.7 6l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Animated checkmark (stroke draw) inside a filled circle */
export function CheckDraw({ size = 16, color = 'var(--ok)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden style={{ flex: 'none', display: 'block' }}>
      <circle cx="8" cy="8" r="8" fill={color} />
      <path className="check-draw" d="M4.6 8.3l2.2 2.2 4.6-4.9" fill="none" stroke="white" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" pathLength={100} />
    </svg>
  )
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg className="spinner" width={size} height={size} viewBox="0 0 16 16" aria-hidden style={{ flex: 'none', display: 'block' }}>
      <circle cx="8" cy="8" r="6.5" fill="none" stroke="var(--fill-strong)" strokeWidth={2} />
      <path d="M8 1.5a6.5 6.5 0 0 1 6.5 6.5" fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinecap="round" />
    </svg>
  )
}

/** colored rounded-square tile with a white glyph (macOS Settings look) */
export function Tile({ color, icon, size = 22 }: { color: string; icon: React.ReactNode; size?: number }) {
  return (
    <span className="tile" style={{ width: size, height: size, borderRadius: size * 0.27, background: color }}>
      {icon}
    </span>
  )
}

export function MusicNoteFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M19.55 5.85V3.65L20.85 4.85v2.2zM9.55 17.05v-11.2h1.3v11.2zM19.55 17.05v-12.2h1.3v12.2zM9.7 17.05a3.3 3.3 0 1 1-6.6 0 3.3 3.3 0 1 1 6.6 0zM19.7 17.05a3.3 3.3 0 1 1-6.6 0 3.3 3.3 0 1 1 6.6 0z" />
    </Fill>
  )
}

export function BookFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M11 5.6C9.3 4.4 6.9 3.8 3.9 3.9a1 1 0 0 0-.9 1v12.6a1 1 0 0 0 1 1c2.8-.1 5 .5 7 1.9zm2 0c1.7-1.2 4.1-1.8 7.1-1.7a1 1 0 0 1 .9 1v12.6a1 1 0 0 1-1 1c-2.8-.1-5 .5-7 1.9z" />
    </Fill>
  )
}

export function HeartFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M12 20.6l-1.3-1.2C5.6 14.8 2.5 12 2.5 8.4A4.9 4.9 0 0 1 7.4 3.5c1.8 0 3.5.8 4.6 2.1a6.1 6.1 0 0 1 4.6-2.1 4.9 4.9 0 0 1 4.9 4.9c0 3.6-3.1 6.4-8.2 11z" />
    </Fill>
  )
}

export function MagnifierIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M10.5 3a7.5 7.5 0 0 1 6 12l4.3 4.3-1.4 1.4-4.3-4.3A7.5 7.5 0 1 1 10.5 3zm0 2a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11z" />
    </Fill>
  )
}

export function GridIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z" />
    </Fill>
  )
}

export function ListIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M4 5h16v2H4zm0 6h16v2H4zm0 6h16v2H4z" />
    </Fill>
  )
}

export function ChevronLeftIcon({ size = 12 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden style={{ flex: 'none', display: 'block' }}>
      <path d="M7.8 2.5L4.3 6l3.5 3.5" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** doc.on.doc: copy */
export function CopyIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" aria-hidden style={{ flex: 'none', display: 'block' }}>
      <rect x="8.5" y="8.5" width="12" height="12.5" rx="2.6" />
      <path d="M15.5 8.5V5.6A2.6 2.6 0 0 0 12.9 3H6.1A2.6 2.6 0 0 0 3.5 5.6v7.8A2.6 2.6 0 0 0 6.1 16h2.4" />
    </svg>
  )
}
