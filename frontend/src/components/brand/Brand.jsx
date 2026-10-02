// Baton's mark: the baton passing between two hands — the assistant and the person it hands over to.
export function BatonMark({ className = 'size-8' }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="baton-mark-fill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset="1" stopColor="#8b5cf6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#baton-mark-fill)" />
      <circle cx="8" cy="23.5" r="2.6" fill="#fff" fillOpacity="0.55" />
      <circle cx="24" cy="8.5" r="2.6" fill="#fff" fillOpacity="0.55" />
      <rect x="7" y="13.6" width="18" height="4.8" rx="2.4" fill="#fff" transform="rotate(-38 16 16)" />
    </svg>
  );
}

/** Mark + wordmark. `tone` follows the surface it sits on. */
export function Brand({ subtitle, tone = 'dark', size = 'md' }) {
  const big = size === 'lg';
  return (
    <div className="flex items-center gap-2.5">
      <BatonMark className={big ? 'size-11' : 'size-8'} />
      <div className="leading-tight">
        <p className={`font-semibold tracking-tight ${big ? 'text-xl' : 'text-sm'} ${tone === 'dark' ? 'text-white' : 'text-slate-900'}`}>Baton</p>
        {subtitle && <p className={`text-[11px] ${tone === 'dark' ? 'text-slate-400' : 'text-slate-500'}`}>{subtitle}</p>}
      </div>
    </div>
  );
}
