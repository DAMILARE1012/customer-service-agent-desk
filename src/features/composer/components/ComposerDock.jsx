import { useSelector } from 'react-redux';
import { CONVERSATION_STATUS } from '../../../constants/conversation.js';
import { selectCurrentAgent } from '../../agent/agentSlice.js';
import { AgentComposer } from './AgentComposer.jsx';
import { ComposerGate } from './ComposerGate.jsx';

/** The agent can only type once they own the conversation; otherwise show the gate. */
export function ComposerDock({ conversation }) {
  const agent = useSelector(selectCurrentAgent);
  const canReply = conversation.status === CONVERSATION_STATUS.AGENT_ACTIVE && conversation.assignee?.id === agent.id;
  return canReply ? <AgentComposer conversation={conversation} /> : <ComposerGate conversation={conversation} />;
}
