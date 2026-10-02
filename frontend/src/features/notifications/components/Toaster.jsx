import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Icon } from '../../../components/ui/index.js';
import { SOLID_TONES } from '../../../components/ui/tones.js';
import { QUEUE_VIEW } from '../../../constants/queue.js';
import { conversationSelected, queueViewChanged } from '../../conversations/deskSlice.js';
import { notificationDismissed, selectNotifications } from '../notificationsSlice.js';

const AUTO_DISMISS_MS = 8000;

function Toast({ notification }) {
  const dispatch = useDispatch();
  const dismiss = () => dispatch(notificationDismissed(notification.id));

  useEffect(() => {
    const id = setTimeout(() => dispatch(notificationDismissed(notification.id)), AUTO_DISMISS_MS);
    return () => clearTimeout(id);
  }, [dispatch, notification.id]);

  const open = () => {
    dispatch(queueViewChanged(QUEUE_VIEW.NEEDS_AGENT));
    dispatch(conversationSelected(notification.conversationId));
    dismiss();
  };

  return (
    <div className="pointer-events-auto flex w-80 overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-slate-900/10">
      <span className={`w-1.5 shrink-0 ${SOLID_TONES[notification.tone]}`} />
      <button type="button" onClick={open} className="flex-1 px-3.5 py-3 text-left hover:bg-slate-50">
        <p className="text-sm font-semibold text-slate-900">{notification.title}</p>
        <p className="text-xs text-slate-500">{notification.body}</p>
        <p className="mt-1 text-xs font-medium text-indigo-600">Open handoff →</p>
      </button>
      <button type="button" onClick={dismiss} className="self-start p-2 text-slate-400 hover:text-slate-600" aria-label="Dismiss">
        <Icon name="x" className="size-4" />
      </button>
    </div>
  );
}

export function Toaster() {
  const notifications = useSelector(selectNotifications);
  return (
    <div className="pointer-events-none fixed top-16 right-4 z-40 flex flex-col gap-2" aria-live="polite">
      {notifications.map((n) => (
        <Toast key={n.id} notification={n} />
      ))}
    </div>
  );
}
