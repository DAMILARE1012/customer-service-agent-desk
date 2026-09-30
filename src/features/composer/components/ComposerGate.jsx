import { Button, Icon } from '../../../components/ui/index.js';
import { CONVERSATION_STATUS } from '../../../constants/conversation.js';
import { useHandoffActions } from '../../handoff/useHandoffActions.js';

/** Replaces the composer when the agent can't (or shouldn't yet) reply, and says why. */
export function ComposerGate({ conversation }) {
  const { can, blockedReason, pending, accept, takeOver } = useHandoffActions(conversation);
  const { status, assignee } = conversation;
  const swallow = (fn) => () => fn().catch(() => {});

  const content = {
    [CONVERSATION_STATUS.BOT_ACTIVE]: {
      icon: 'bot',
      text: 'The assistant is handling this conversation. You’re watching live.',
      action: (
        <Button variant="secondary" size="sm" icon="arrowRight" onClick={swallow(takeOver)} disabled={!can.takeOver} loading={pending.takeOver}>
          Take over
        </Button>
      ),
    },
    [CONVERSATION_STATUS.HANDOFF_PENDING]: {
      icon: 'clock',
      text: 'The bot has stepped aside and the customer is waiting. Review the brief, then accept to reply.',
      action: (
        <Button size="sm" icon="check" onClick={swallow(accept)} disabled={!can.accept} loading={pending.accept}>
          Accept handoff
        </Button>
      ),
    },
    [CONVERSATION_STATUS.AGENT_ACTIVE]: {
      icon: 'user',
      text: `${assignee?.name ?? 'Another agent'} is handling this conversation.`,
    },
    [CONVERSATION_STATUS.RESOLVED]: {
      icon: 'checkCircle',
      text: 'Resolved. If the customer writes again, the bot picks it back up.',
    },
  }[status];

  return (
    <div className="border-t border-slate-200 bg-white px-5 py-4">
      <div className="flex items-center justify-between gap-4 rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-200">
        <p className="flex items-center gap-2 text-sm text-slate-600">
          <Icon name={content.icon} className="size-4 shrink-0 text-slate-400" />
          {content.text}
        </p>
        {content.action}
      </div>
      {blockedReason && content.action && <p className="mt-2 text-xs text-amber-700">{blockedReason}</p>}
    </div>
  );
}
