import { useDispatch, useSelector } from 'react-redux';
import { Button } from '../../../components/ui/index.js';
import { errorMessage } from '../../../utils/format.js';
import { selectCurrentAgent } from '../../agent/agentSlice.js';
import { useSendAgentMessageMutation } from '../composerApi.js';
import { draftChanged, draftCleared, selectDraft } from '../composerSlice.js';
import { CopilotSuggestion } from './CopilotSuggestion.jsx';

export function AgentComposer({ conversation }) {
  const dispatch = useDispatch();
  const agent = useSelector(selectCurrentAgent);
  const draft = useSelector((state) => selectDraft(state, conversation.id));
  const [sendMessage, { isLoading, error }] = useSendAgentMessageMutation();

  const setDraft = (text) => dispatch(draftChanged({ conversationId: conversation.id, text }));

  const send = async () => {
    const text = draft.trim();
    if (!text) return;
    dispatch(draftCleared(conversation.id));
    try {
      await sendMessage({ conversationId: conversation.id, agent, text }).unwrap();
    } catch {
      setDraft(text); // give the text back so nothing is lost
    }
  };

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };

  return (
    <div className="border-t border-slate-200 bg-white px-5 py-4">
      <CopilotSuggestion copilot={conversation.copilot} onUse={setDraft} />
      <div className="flex items-end gap-2 rounded-xl p-2 ring-1 ring-slate-300 focus-within:ring-2 focus-within:ring-indigo-500">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder={`Reply to ${conversation.customer.name.split(' ')[0]}…  (Enter to send, Shift+Enter for newline)`}
          className="max-h-40 min-h-[2.5rem] flex-1 resize-y border-0 bg-transparent px-1 text-sm placeholder:text-slate-400 focus:outline-none"
        />
        <Button icon="send" onClick={send} loading={isLoading} disabled={!draft.trim()}>
          Send
        </Button>
      </div>
      {error && <p className="mt-2 text-xs text-rose-600">{errorMessage(error)}</p>}
    </div>
  );
}
