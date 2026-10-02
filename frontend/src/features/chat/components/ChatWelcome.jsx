import { BatonMark } from '../../../components/brand/Brand.jsx';
import { Icon } from '../../../components/ui/index.js';
import { SUGGESTED_QUESTIONS } from '../chatStatus.js';
import { ChatComposer } from './ChatComposer.jsx';

/** A new conversation: greet, offer starter questions, explain the handoff promise. */
export function ChatWelcome({ firstName, onAsk, sending }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-4 py-10">
      <div className="w-full max-w-xl space-y-6">
        <div className="space-y-3 text-center">
          <BatonMark className="mx-auto size-12" />
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Hi{firstName ? ` ${firstName}` : ''}, how can we help?</h1>
          <p className="text-sm text-slate-500">
            Baton answers from our help centre and cites its sources. If it can’t help, it brings in a person — and passes along everything you’ve said, so
            you never have to repeat yourself.
          </p>
        </div>

        <ChatComposer onSend={onAsk} sending={sending} placeholder="Describe what you need help with…" />

        <div className="grid gap-2 sm:grid-cols-2">
          {SUGGESTED_QUESTIONS.map((question) => (
            <button
              key={question}
              type="button"
              disabled={sending}
              onClick={() => onAsk(question)}
              className="flex items-start gap-2 rounded-xl bg-white px-3.5 py-3 text-left text-sm text-slate-700 shadow-sm ring-1 ring-slate-200 transition hover:text-indigo-700 hover:ring-indigo-300 disabled:opacity-50"
            >
              <Icon name="chat" className="mt-0.5 size-4 shrink-0 text-slate-400" />
              {question}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
