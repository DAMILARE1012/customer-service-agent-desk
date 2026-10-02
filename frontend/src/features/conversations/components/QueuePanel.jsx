import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { POLLING_INTERVAL_MS } from '../../../constants/queue.js';
import { errorMessage } from '../../../utils/format.js';
import { useGetConversationsQuery } from '../conversationsApi.js';
import { conversationSelected, selectSelectedConversationId } from '../deskSlice.js';
import { selectVisibleConversations } from '../selectors.js';
import { ConversationList } from './ConversationList.jsx';
import { QueueSearch } from './QueueSearch.jsx';
import { QueueTabs } from './QueueTabs.jsx';

export function QueuePanel() {
  const dispatch = useDispatch();
  const { isLoading, error } = useGetConversationsQuery(undefined, { pollingInterval: POLLING_INTERVAL_MS });
  const selectedId = useSelector(selectSelectedConversationId);
  const visible = useSelector(selectVisibleConversations);

  // Open the most urgent conversation on first load.
  useEffect(() => {
    if (!selectedId && visible.length) dispatch(conversationSelected(visible[0].id));
  }, [dispatch, selectedId, visible]);

  return (
    <aside className="flex min-h-0 flex-col border-r border-slate-200 bg-white">
      <div className="space-y-3 border-b border-slate-200 p-4">
        <QueueTabs />
        <QueueSearch />
      </div>
      {error && <p className="px-4 py-2 text-xs text-rose-600">{errorMessage(error)}</p>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ConversationList isLoading={isLoading} />
      </div>
    </aside>
  );
}
