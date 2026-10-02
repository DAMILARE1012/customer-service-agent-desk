import { Badge } from '../../../components/ui/index.js';
import { HANDOFF_REASON_META } from '../../../constants/handoff.js';

export function HandoffReasonBadge({ reason }) {
  const meta = HANDOFF_REASON_META[reason];
  if (!meta) return null;
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}
