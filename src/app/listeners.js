import { createListenerMiddleware, isAnyOf } from '@reduxjs/toolkit';
import { CONVERSATION_STATUS, SYSTEM_EVENT } from '../constants/conversation.js';
import { HANDOFF_REASON_META, PRIORITY_META } from '../constants/handoff.js';
import { QUEUE_VIEW } from '../constants/queue.js';
import { conversationSelected, queueViewChanged } from '../features/conversations/deskSlice.js';
import { handoffApi } from '../features/handoff/handoffApi.js';
import { notificationAdded } from '../features/notifications/notificationsSlice.js';
import { simulatorApi } from '../features/simulator/simulatorApi.js';
import { simulatorConversationChanged } from '../features/simulator/simulatorSlice.js';

export const listenerMiddleware = createListenerMiddleware();
const startListening = listenerMiddleware.startListening;

// Once an agent owns a conversation, follow it into "Mine".
startListening({
  matcher: isAnyOf(handoffApi.endpoints.acceptHandoff.matchFulfilled, handoffApi.endpoints.takeOver.matchFulfilled),
  effect: (action, { dispatch }) => {
    dispatch(queueViewChanged(QUEUE_VIEW.MINE));
    dispatch(conversationSelected(action.payload.id));
  },
});

// A fresh handoff is a first-class event: surface it to the desk immediately.
startListening({
  matcher: simulatorApi.endpoints.sendCustomerMessage.matchFulfilled,
  effect: ({ payload: conversation }, { dispatch }) => {
    const justHandedOff =
      conversation.status === CONVERSATION_STATUS.HANDOFF_PENDING &&
      conversation.messages.at(-1)?.event?.type === SYSTEM_EVENT.HANDOFF_REQUESTED;
    if (!justHandedOff) return;

    const { reason, priority } = conversation.handoff;
    dispatch(
      notificationAdded({
        conversationId: conversation.id,
        title: `${conversation.customer.name} needs an agent`,
        body: `${HANDOFF_REASON_META[reason].label} · ${PRIORITY_META[priority].label} priority`,
        tone: PRIORITY_META[priority].tone,
      }),
    );
  },
});

// New simulated chats show up selected in the live bot queue.
startListening({
  matcher: simulatorApi.endpoints.startConversation.matchFulfilled,
  effect: ({ payload: conversation }, { dispatch }) => {
    dispatch(simulatorConversationChanged(conversation.id));
    dispatch(queueViewChanged(QUEUE_VIEW.BOT_LIVE));
    dispatch(conversationSelected(conversation.id));
  },
});
