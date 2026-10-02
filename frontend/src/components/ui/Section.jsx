import { Icon } from './Icon.jsx';

/** Titled block used to stack the context panels. */
export function Section({ title, icon, aside, children, className = '' }) {
  return (
    <section className={`border-b border-slate-200 px-4 py-4 last:border-b-0 ${className}`}>
      <header className="mb-2.5 flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
          {icon && <Icon name={icon} className="size-3.5" />}
          {title}
        </h3>
        {aside}
      </header>
      {children}
    </section>
  );
}
