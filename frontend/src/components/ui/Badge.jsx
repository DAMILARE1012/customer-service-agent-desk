import { Icon } from './Icon.jsx';
import { BADGE_TONES } from './tones.js';

export function Badge({ tone = 'slate', icon, children, className = '' }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE_TONES[tone]} ${className}`}
    >
      {icon && <Icon name={icon} className="size-3.5" />}
      {children}
    </span>
  );
}
