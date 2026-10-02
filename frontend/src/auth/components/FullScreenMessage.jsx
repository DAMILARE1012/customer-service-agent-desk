import { BatonMark } from '../../components/brand/Brand.jsx';
import { Spinner } from '../../components/ui/index.js';

/** Centered status page: signing in, sign-in errors, no access. */
export function FullScreenMessage({ title, description, busy = false, children }) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-4 bg-slate-50 px-6 text-center">
      <BatonMark className="size-12" />
      <div className="space-y-1.5">
        <h1 className="flex items-center justify-center gap-2 text-base font-semibold text-slate-900">
          {busy && <Spinner className="size-4 text-indigo-500" />}
          {title}
        </h1>
        {description && <p className="mx-auto max-w-md text-sm text-slate-500">{description}</p>}
      </div>
      {children}
    </div>
  );
}
