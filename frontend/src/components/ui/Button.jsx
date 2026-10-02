import { Icon } from './Icon.jsx';
import { Spinner } from './Spinner.jsx';

const VARIANTS = {
  primary: 'bg-indigo-600 text-white hover:bg-indigo-500 focus-visible:outline-indigo-600 shadow-sm',
  success: 'bg-emerald-600 text-white hover:bg-emerald-500 focus-visible:outline-emerald-600 shadow-sm',
  secondary: 'bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 shadow-sm',
  ghost: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
  danger: 'bg-rose-600 text-white hover:bg-rose-500 focus-visible:outline-rose-600 shadow-sm',
  dangerGhost: 'text-rose-600 hover:bg-rose-50 hover:text-rose-700',
};

const SIZES = {
  sm: 'px-2.5 py-1.5 text-xs gap-1.5',
  md: 'px-3.5 py-2 text-sm gap-2',
};

export function Button({ variant = 'primary', size = 'md', icon, loading = false, disabled, className = '', children, ...props }) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`inline-flex shrink-0 items-center justify-center rounded-lg font-medium whitespace-nowrap transition focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...props}
    >
      {loading ? <Spinner className="size-4" /> : icon && <Icon name={icon} className="size-4" />}
      {children}
    </button>
  );
}
