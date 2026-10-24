type Direction = 'back' | 'forward' | 'external' | 'up';

/** Shared 16 px action arrows. Keep logos, charts and navigation symbols separate. */
export function ActionIcon({ direction = 'forward' }: { direction?: Direction }) {
  const paths: Record<Direction, string> = {
    back: 'M19 12H5 M11 6l-6 6 6 6',
    forward: 'M5 12h14 M13 6l6 6-6 6',
    external: 'M6 18 18 6 M6 6h12v12',
    up: 'M12 19V5 M6 11l6-6 6 6',
  };
  return <svg className="action-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[direction]} /></svg>;
}
