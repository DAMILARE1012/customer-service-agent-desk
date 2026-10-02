import { createListenerMiddleware, isAnyOf } from '@reduxjs/toolkit';
import { CONVERSATION_STATUS } from '../constants/conversation.js';
import { HANDOFF_REASON_META, PRIORITY_META } from '../constants/handoff.js';
import { QUEUE_VIEW } from '../constants/queue.js';
import { conversationsApi } from '../features/conversations/conversationsApi.js';
import { conversationSelected, queueViewChanged } from '../features/conversations/deskSlice.js';
import { handoffApi } from '../features/handoff/handoffApi.js';
import { notificationAdded } from '../features/notifications/notificationsSlice.js';

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

// A fresh handoff is a first-class event: when the polled queue shows a conversation that has just
// started waiting for an agent, surface it to the desk immediately.
const selectQueue = conversationsApi.endpoints.getConversations.select();

startListening({
  matcher: conversationsApi.endpoints.getConversations.matchFulfilled,
  effect: ({ payload: queue }, { dispatch, getOriginalState }) => {
    const before = selectQueue(getOriginalState()).data;
    if (!before) return; // first load: the backlog is visible in the queue, no need to toast it
    const waiting = new Set(before.filter((c) => c.status === CONVERSATION_STATUS.HANDOFF_PENDING).map((c) => c.id));

    for (const conversation of queue) {
      if (conversation.status !== CONVERSATION_STATUS.HANDOFF_PENDING || waiting.has(conversation.id)) continue;
      const { reason, priority } = conversation.handoff;
      dispatch(
        notificationAdded({
          conversationId: conversation.id,
          title: `${conversation.customer.name} needs an agent`,
          body: `${HANDOFF_REASON_META[reason].label} · ${PRIORITY_META[priority].label} priority`,
          tone: PRIORITY_META[priority].tone,
        }),
      );
    }
  },
});
