import { Badge, Button } from '../../../components/ui/index.js';
import { CONVERSATION_STATUS } from '../../../constants/conversation.js';
import { errorMessage } from '../../../utils/format.js';
import { useHandoffActions } from '../useHandoffActions.js';

// Errors stay on the mutation state and are rendered below, so the promise rejection can be dropped.
const run = (fn) => () => fn().catch(() => {});

function ActionButtons({ conversation, actions }) {
  const { can, isMine, blockedReason, pending, accept, takeOver, returnToBot, resolve } = actions;

  switch (conversation.status) {
    case CONVERSATION_STATUS.BOT_ACTIVE:
      return (
        <Button variant="secondary" size="sm" icon="arrowRight" onClick={run(takeOver)} disabled={!can.takeOver} loading={pending.takeOver} title={blockedReason ?? 'Step in before the bot hands off'}>
          Take over
        </Button>
      );

    case CONVERSATION_STATUS.HANDOFF_PENDING:
      return (
        <Button size="sm" icon="check" onClick={run(accept)} disabled={!can.accept} loading={pending.accept} title={blockedReason ?? undefined}>
          Accept handoff
        </Button>
      );

    case CONVERSATION_STATUS.AGENT_ACTIVE:
      if (!isMine) return <Badge tone="indigo" icon="user">{conversation.assignee?.name}</Badge>;
      return (
        <>
          <Button variant="secondary" size="sm" icon="returnLeft" onClick={run(returnToBot)} loading={pending.returnToBot} title="Hand the conversation back to the bot">
            Return to bot
          </Button>
          <Button variant="success" size="sm" icon="checkCircle" onClick={run(resolve)} loading={pending.resolve}>
            Resolve
          </Button>
        </>
      );

    default:
      return null;
  }
}

/** Header actions, driven entirely by the conversation's lifecycle state. */
export function ConversationActions({ conversation }) {
  const actions = useHandoffActions(conversation);
  return (
    <div className="flex items-center gap-2">
      {actions.error && <span className="text-xs text-rose-600">{errorMessage(actions.error)}</span>}
      <ActionButtons conversation={conversation} actions={actions} />
    </div>
  );
}
