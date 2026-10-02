import { Icon } from '../../../components/ui/index.js';

/** The round button that floats over the website. */
export function Launcher({ onOpen, unread }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={unread ? 'Open support chat — new reply' : 'Open support chat'}
      className="relative flex size-14 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-900/25 transition hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
    >
      <Icon name="chat" className="size-7" strokeWidth={1.6} />
      {unread && <span className="absolute top-0.5 right-0.5 size-3.5 rounded-full bg-rose-500 ring-2 ring-white" aria-hidden="true" />}
    </button>
  );
}
