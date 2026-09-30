import { Badge } from '../../../components/ui/index.js';
import { STATUS_META } from '../../../constants/conversation.js';

export function StatusBadge({ status }) {
  const meta = STATUS_META[status];
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}
