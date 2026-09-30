import { useDispatch, useSelector } from 'react-redux';
import { Icon } from '../../../components/ui/index.js';
import { POLLING_INTERVAL_MS } from '../../../constants/queue.js';
import { errorMessage } from '../../../utils/format.js';
import { useGetConversationQuery } from '../../conversations/conversationsApi.js';
import { selectSelectedConversationId } from '../../conversations/deskSlice.js';
import { useSendCustomerMessageMutation } from '../simulatorApi.js';
import { selectSimulatorConversationId, selectSimulatorOpen, simulatorToggled } from '../simulatorSlice.js';
import { CustomerChatView } from './CustomerChatView.jsx';
import { QuickPrompts } from './QuickPrompts.jsx';
import { SimulatorInput } from './SimulatorInput.jsx';
import { SimulatorTarget } from './SimulatorTarget.jsx';

/** Dev tool: play the customer in the chat widget to exercise the bot and the handoff policy. */
export function SimulatorPanel() {
  const dispatch = useDispatch();
  const open = useSelector(selectSimulatorOpen);
  const deskSelection = useSelector(selectSelectedConversationId);
  const pinned = useSelector(selectSimulatorConversationId);
  const conversationId = pinned ?? deskSelection;

  const { currentData: conversation } = useGetConversationQuery(conversationId, {
    skip: !open || !conversationId,
    pollingInterval: POLLING_INTERVAL_MS,
  });
  const [sendCustomerMessage, { isLoading, error }] = useSendCustomerMessageMutation();

  if (!open) return null;

  const send = (text) => sendCustomerMessage({ conversationId, text });

  return (
    <section className="fixed right-4 bottom-4 z-30 flex h-[560px] max-h-[calc(100vh-5rem)] w-[380px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-900/10">
      <header className="flex items-center justify-between bg-slate-900 px-4 py-2.5 text-white">
        <div>
          <p className="text-sm font-semibold">Customer simulator</p>
          <p className="text-[11px] text-slate-300">{conversation ? `Chatting as ${conversation.customer.name}` : 'Pick a conversation'}</p>
        </div>
        <button type="button" onClick={() => dispatch(simulatorToggled())} className="rounded p-1 text-slate-300 hover:bg-white/10 hover:text-white" aria-label="Close simulator">
          <Icon name="x" className="size-5" />
        </button>
      </header>

      <SimulatorTarget conversationId={conversationId} />
      <CustomerChatView messages={conversation?.messages ?? []} />

      <footer className="space-y-2 border-t border-slate-200 bg-slate-50 p-3">
        <QuickPrompts onPick={send} disabled={!conversationId || isLoading} />
        <SimulatorInput onSend={send} sending={isLoading} disabled={!conversationId} />
        {error && <p className="text-xs text-rose-600">{errorMessage(error)}</p>}
      </footer>
    </section>
  );
}
