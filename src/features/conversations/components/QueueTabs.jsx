import { useDispatch, useSelector } from 'react-redux';
import { Tabs } from '../../../components/ui/index.js';
import { QUEUE_VIEWS } from '../../../constants/queue.js';
import { queueViewChanged, selectQueueView } from '../deskSlice.js';
import { selectQueueCounts } from '../selectors.js';

export function QueueTabs() {
  const dispatch = useDispatch();
  const view = useSelector(selectQueueView);
  const counts = useSelector(selectQueueCounts);
  const tabs = QUEUE_VIEWS.map((tab) => ({ ...tab, count: counts[tab.id] ?? 0 }));

  return (
    <Tabs tabs={tabs} value={view} onChange={(id) => dispatch(queueViewChanged(id))} className="rounded-lg bg-slate-100 p-1" />
  );
}
