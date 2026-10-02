import { Badge } from '../../../components/ui/index.js';
import { PRIORITY_META } from '../../../constants/handoff.js';

export function PriorityBadge({ priority }) {
  const meta = PRIORITY_META[priority];
  if (!meta) return null;
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}
