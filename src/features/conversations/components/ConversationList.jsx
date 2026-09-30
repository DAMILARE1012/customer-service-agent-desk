import { useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { EmptyState, Spinner } from '../../../components/ui/index.js';
import { QUEUE_VIEW } from '../../../constants/queue.js';
import { useNow } from '../../../hooks/useNow.js';
import { conversationSelected, selectQueueView, selectSelectedConversationId } from '../deskSlice.js';
import { selectVisibleConversations } from '../selectors.js';
import { ConversationListItem } from './ConversationListItem.jsx';

const EMPTY_COPY = {
  [QUEUE_VIEW.NEEDS_AGENT]: { title: 'No one is waiting', description: 'When the bot steps aside, the conversation lands here with its full context.' },
  [QUEUE_VIEW.MINE]: { title: 'No active chats', description: 'Accept a handoff to start helping a customer.' },
  [QUEUE_VIEW.BOT_LIVE]: { title: 'The bot is idle', description: 'Open the customer simulator to start a conversation.' },
  [QUEUE_VIEW.ALL]: { title: 'No conversations yet' },
};

export function ConversationList({ isLoading }) {
  const dispatch = useDispatch();
  const conversations = useSelector(selectVisibleConversations);
  const selectedId = useSelector(selectSelectedConversationId);
  const view = useSelector(selectQueueView);
  const now = useNow(30_000);
  const onSelect = useCallback((id) => dispatch(conversationSelected(id)), [dispatch]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-10 text-slate-400">
        <Spinner />
      </div>
    );
  }

  if (conversations.length === 0) return <EmptyState icon="checkCircle" {...EMPTY_COPY[view]} />;

  return (
    <ul className="divide-y divide-slate-100">
      {conversations.map((conversation) => (
        <ConversationListItem
          key={conversation.id}
          conversation={conversation}
          selected={conversation.id === selectedId}
          onSelect={onSelect}
          now={now}
        />
      ))}
    </ul>
  );
}
