import { Icon } from '../../../components/ui/index.js';
import { BOT_REPLY_KIND } from '../../../constants/conversation.js';
import { formatPercent } from '../../../utils/format.js';

const KIND_LABEL = {
  [BOT_REPLY_KIND.ANSWER]: 'Answered from KB',
  [BOT_REPLY_KIND.CLARIFY]: 'Asked to clarify',
  [BOT_REPLY_KIND.HANDOFF_NOTICE]: 'Handoff notice',
};

const confidenceTone = (value) => (value >= 0.5 ? 'text-emerald-700' : value >= 0.35 ? 'text-amber-700' : 'text-rose-700');

/** The retrieval trace under a bot reply — what it cited and how sure it was. Agent-only. */
export function BotReplyMeta({ meta }) {
  if (!meta || meta.kind === BOT_REPLY_KIND.SMALL_TALK) return null;
  const [topSource] = meta.sources ?? [];

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
      <span>{KIND_LABEL[meta.kind]}</span>
      {meta.confidence != null && (
        <span className={`font-medium ${confidenceTone(meta.confidence)}`}>{formatPercent(meta.confidence)} confidence</span>
      )}
      {topSource && meta.kind === BOT_REPLY_KIND.ANSWER && (
        <span className="inline-flex items-center gap-1" title={topSource.snippet}>
          <Icon name="book" className="size-3" />
          {topSource.title}
        </span>
      )}
    </div>
  );
}
