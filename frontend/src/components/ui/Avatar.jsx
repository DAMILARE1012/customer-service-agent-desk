import { initials } from '../../utils/format.js';
import { Icon } from './Icon.jsx';

const PALETTE = ['bg-rose-100 text-rose-700', 'bg-amber-100 text-amber-800', 'bg-emerald-100 text-emerald-700', 'bg-sky-100 text-sky-700', 'bg-violet-100 text-violet-700', 'bg-teal-100 text-teal-700'];

const colorFor = (seed = '') => PALETTE[[...seed].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % PALETTE.length];

const SIZES = { sm: 'size-7 text-[11px]', md: 'size-9 text-xs', lg: 'size-12 text-sm' };

export function Avatar({ name, kind = 'person', size = 'md' }) {
  if (kind === 'bot') {
    return (
      <span className={`inline-flex shrink-0 items-center justify-center rounded-full bg-sky-600 text-white ${SIZES[size]}`}>
        <Icon name="bot" className="size-4" />
      </span>
    );
  }
  return (
    <span className={`inline-flex shrink-0 items-center justify-center rounded-full font-semibold ${SIZES[size]} ${colorFor(name)}`}>
      {initials(name)}
    </span>
  );
}
