export function formatDuration(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function formatRelative(timestamp, now = Date.now()) {
  const ms = now - timestamp;
  if (ms < 45_000) return 'just now';
  return `${formatDuration(ms)} ago`;
}

export const formatClock = (timestamp) =>
  new Date(timestamp).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

export const formatPercent = (value) => (value == null ? '—' : `${Math.round(value * 100)}%`);

export const formatCurrency = (value) =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);

export const formatDate = (iso) => new Date(iso).toLocaleDateString(undefined, { month: 'short', year: 'numeric' });

export const initials = (name = '') =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');

export const errorMessage = (error) => error?.data?.message ?? error?.error ?? 'Something went wrong.';
