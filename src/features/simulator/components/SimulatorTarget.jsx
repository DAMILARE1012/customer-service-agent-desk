import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { Button } from '../../../components/ui/index.js';
import { STATUS_META } from '../../../constants/conversation.js';
import { useGetConversationsQuery } from '../../conversations/conversationsApi.js';
import { useGetCustomersQuery, useStartConversationMutation } from '../simulatorApi.js';
import { simulatorConversationChanged } from '../simulatorSlice.js';

const selectClass = 'min-w-0 flex-1 rounded-md border-0 bg-white py-1.5 pr-7 pl-2 text-xs ring-1 ring-slate-300 focus:ring-2 focus:ring-slate-900 focus:outline-none';

/** Choose which conversation to speak into — or start a new one as any customer. */
export function SimulatorTarget({ conversationId }) {
  const dispatch = useDispatch();
  const { data: conversations = [] } = useGetConversationsQuery();
  const { data: customers = [] } = useGetCustomersQuery();
  const [startConversation, { isLoading }] = useStartConversationMutation();
  const [customerId, setCustomerId] = useState('cus_sam');

  return (
    <div className="space-y-2 border-b border-slate-200 bg-slate-50 px-3 py-2.5">
      <label className="flex items-center gap-2 text-xs text-slate-500">
        <span className="w-12 shrink-0">Chat</span>
        <select value={conversationId ?? ''} onChange={(e) => dispatch(simulatorConversationChanged(e.target.value))} className={selectClass}>
          {conversations.map((c) => (
            <option key={c.id} value={c.id}>
              {c.customer.name} — {STATUS_META[c.status].label}
            </option>
          ))}
        </select>
      </label>
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <span className="w-12 shrink-0">New as</span>
        <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={selectClass} aria-label="Customer for new chat">
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <Button size="sm" variant="secondary" icon="plus" loading={isLoading} onClick={() => startConversation({ customerId })}>
          Start
        </Button>
      </div>
    </div>
  );
}
