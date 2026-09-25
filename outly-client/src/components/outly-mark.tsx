/**
 * The Outly mark: a broken ring (the "O") with a signal arrow breaking out of
 * the gap. Reads as outbound research at any size.
 *
 * Colours come from --invert-bg / --invert-fg, so the tile stays the opposite
 * of the page in both light and dark themes. The standalone favicon at
 * src/app/icon.svg carries the same geometry with literal colours.
 */
export function OutlyMark({
  size = 30,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      role="img"
      aria-label="Outly"
    >
      <rect width="32" height="32" rx="8" fill="var(--invert-bg)" />
      <g
        fill="none"
        stroke="var(--invert-fg)"
        strokeWidth="2.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M22.58 13.61A7 7 0 1 1 18.39 9.42" />
        <path d="M17.56 14.44 24.4 7.6" />
        <path d="M20.2 7.6H24.4V11.8" />
      </g>
    </svg>
  );
}
