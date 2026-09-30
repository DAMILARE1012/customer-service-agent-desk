import { Icon } from './Icon.jsx';

export function EmptyState({ icon = 'chat', title, description, children }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <span className="rounded-full bg-slate-100 p-3 text-slate-400">
        <Icon name={icon} className="size-6" />
      </span>
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {description && <p className="max-w-xs text-xs text-slate-500">{description}</p>}
      {children}
    </div>
  );
}
