import { useDispatch, useSelector } from 'react-redux';
import { EmptyState, Tabs } from '../../../components/ui/index.js';
import { CONVERSATION_STATUS } from '../../../constants/conversation.js';
import { CustomerProfile } from '../../customer/components/CustomerProfile.jsx';
import { CustomerTimeline } from '../../customer/components/CustomerTimeline.jsx';
import { useGetConversationQuery } from '../../conversations/conversationsApi.js';
import { contextTabChanged, selectContextTab, selectSelectedConversationId } from '../../conversations/deskSlice.js';
import { HandoffBrief } from './HandoffBrief.jsx';
import { KnowledgeSources } from './KnowledgeSources.jsx';
import { LiveBotInsights } from './LiveBotInsights.jsx';

function HandoffTab({ conversation }) {
  // While the bot is in charge, show the live signals; once it steps aside, show the frozen packet.
  if (conversation.status === CONVERSATION_STATUS.BOT_ACTIVE || !conversation.handoff) {
    return <LiveBotInsights conversation={conversation} />;
  }
  return <HandoffBrief key={conversation.handoff.id} handoff={conversation.handoff} replyEmail={conversation.contact?.email ?? conversation.customer?.email} />;
}

export function ContextPanel() {
  const dispatch = useDispatch();
  const selectedId = useSelector(selectSelectedConversationId);
  const tab = useSelector(selectContextTab);
  // Same cache entry as the thread — no extra request.
  const { currentData: conversation } = useGetConversationQuery(selectedId, { skip: !selectedId });

  const tabs = [
    { id: 'handoff', label: conversation?.handoff && conversation.status !== CONVERSATION_STATUS.BOT_ACTIVE ? 'Handoff brief' : 'Bot insights' },
    { id: 'knowledge', label: 'Knowledge' },
    { id: 'customer', label: 'Customer' },
  ];

  return (
    <aside className="flex min-h-0 flex-1 flex-col border-l border-slate-200 bg-white">
      <div className="border-b border-slate-200 p-3">
        <Tabs tabs={tabs} value={tab} onChange={(id) => dispatch(contextTabChanged(id))} className="rounded-lg bg-slate-100 p-1" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!conversation ? (
          <EmptyState icon="sparkles" title="No conversation selected" description="Context from the bot shows up here." />
        ) : tab === 'handoff' ? (
          <HandoffTab conversation={conversation} />
        ) : tab === 'knowledge' ? (
          <KnowledgeSources conversation={conversation} />
        ) : (
          <>
            <CustomerProfile customer={conversation.customer} />
            <CustomerTimeline customerId={conversation.customer.id} currentId={conversation.id} />
          </>
        )}
      </div>
    </aside>
  );
}
