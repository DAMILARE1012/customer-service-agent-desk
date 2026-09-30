import { useSelector } from 'react-redux';
import { EmptyState, Spinner } from '../../../components/ui/index.js';
import { POLLING_INTERVAL_MS } from '../../../constants/queue.js';
import { errorMessage } from '../../../utils/format.js';
import { ComposerDock } from '../../composer/components/ComposerDock.jsx';
import { useGetConversationQuery } from '../../conversations/conversationsApi.js';
import { selectSelectedConversationId } from '../../conversations/deskSlice.js';
import { MessageList } from './MessageList.jsx';
import { ThreadHeader } from './ThreadHeader.jsx';

export function ConversationPanel() {
  const selectedId = useSelector(selectSelectedConversationId);
  // `currentData` (not `data`) so switching chats never flashes the previous transcript.
  const { currentData: conversation, isFetching, error } = useGetConversationQuery(selectedId, {
    skip: !selectedId,
    pollingInterval: POLLING_INTERVAL_MS,
  });

  let body;
  if (!selectedId) body = <EmptyState title="Select a conversation" description="Pick a chat from the queue to see the transcript." />;
  else if (error) body = <EmptyState icon="warning" title="Couldn’t load conversation" description={errorMessage(error)} />;
  else if (!conversation && isFetching) body = <div className="flex h-full items-center justify-center text-slate-400"><Spinner /></div>;
  else if (conversation) {
    body = (
      <>
        <ThreadHeader conversation={conversation} />
        <MessageList messages={conversation.messages} customerName={conversation.customer.name} />
        <ComposerDock conversation={conversation} />
      </>
    );
  }

  return <main className="flex min-h-0 min-w-0 flex-col bg-slate-50">{body}</main>;
}
