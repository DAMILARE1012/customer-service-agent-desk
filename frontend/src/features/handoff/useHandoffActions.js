import { useSelector } from 'react-redux';
import { CONVERSATION_STATUS } from '../../constants/conversation.js';
import { selectCurrentAgent } from '../account/accountApi.js';
import { selectAvailability } from '../agent/agentSlice.js';
import { selectMyActiveCount } from '../conversations/selectors.js';
import {
  useAcceptHandoffMutation,
  useResolveConversationMutation,
  useReturnToBotMutation,
  useTakeOverMutation,
} from './handoffApi.js';

/**
 * Everything a component needs to move a conversation through the handoff lifecycle:
 * which transitions are allowed for this agent right now, and the calls to make them.
 */
export function useHandoffActions(conversation) {
  const agent = useSelector(selectCurrentAgent);
  const availability = useSelector(selectAvailability);
  const activeCount = useSelector(selectMyActiveCount);

  const [accept, acceptState] = useAcceptHandoffMutation();
  const [takeOver, takeOverState] = useTakeOverMutation();
  const [returnToBot, returnState] = useReturnToBotMutation();
  const [resolve, resolveState] = useResolveConversationMutation();

  const status = conversation?.status;
  const isMine = Boolean(agent.id) && conversation?.assignee?.id === agent.id;
  const atCapacity = activeCount >= agent.capacity;
  const away = availability !== 'online';
  const args = { conversationId: conversation?.id }; // who acts comes from the access token

  const blockedReason = !agent.id
    ? 'Your agent profile is still loading.'
    : away
      ? 'Set yourself online to pick up conversations.'
      : atCapacity
        ? `You’re at capacity (${agent.capacity} chats).`
        : null;

  return {
    agent,
    isMine,
    blockedReason,
    can: {
      accept: status === CONVERSATION_STATUS.HANDOFF_PENDING && !blockedReason,
      takeOver: status === CONVERSATION_STATUS.BOT_ACTIVE && !blockedReason,
      returnToBot: status === CONVERSATION_STATUS.AGENT_ACTIVE && isMine,
      resolve: status === CONVERSATION_STATUS.AGENT_ACTIVE && isMine,
    },
    accept: () => accept(args).unwrap(),
    takeOver: () => takeOver(args).unwrap(),
    returnToBot: () => returnToBot(args).unwrap(),
    resolve: () => resolve(args).unwrap(),
    pending: {
      accept: acceptState.isLoading,
      takeOver: takeOverState.isLoading,
      returnToBot: returnState.isLoading,
      resolve: resolveState.isLoading,
    },
    error: acceptState.error ?? takeOverState.error ?? returnState.error ?? resolveState.error,
  };
}
