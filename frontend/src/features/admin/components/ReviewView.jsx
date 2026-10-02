import { useEffect, useState } from 'react';
import { Badge, Button, EmptyState, Icon, Spinner, Tabs } from '../../../components/ui/index.js';
import { errorMessage } from '../../../utils/format.js';
import { useGetReviewItemsQuery, useReindexKnowledgeMutation, useReviewActionMutation, useRunReviewMutation, useUpdateReviewItemMutation } from '../adminApi.js';
import { Card } from './Card.jsx';

const STATUS_TONE = { pending: 'amber', published: 'emerald', approved: 'emerald', rejected: 'slate' };

const inputClass = 'w-full rounded-lg border-0 py-2 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500';

/** A question the help centre couldn't answer: write the missing article here and publish it. */
function GapCard({ item, onDone }) {
  const [draft, setDraft] = useState({ title: item.title, answer: item.answer });
  const [update, updateState] = useUpdateReviewItemMutation();
  const [act, actState] = useReviewActionMutation();
  const open = item.status === 'pending';
  useEffect(() => setDraft({ title: item.title, answer: item.answer }), [item.title, item.answer]);
  const dirty = draft.title !== item.title || draft.answer !== item.answer;

  const publish = async () => {
    if (dirty) await update({ id: item.id, ...draft }).unwrap();
    const published = await act({ id: item.id, action: 'publish' }).unwrap();
    onDone(`Published as ${published.publishedPath}. Use “Index new articles” to make it live now, or it’s picked up on the next ingestion.`);
  };

  return (
    <Card
      title={item.question}
      description={`Asked ${item.count} time${item.count === 1 ? '' : 's'} · ${item.conversationIds.length} conversation${item.conversationIds.length === 1 ? '' : 's'}`}
      aside={<Badge tone={STATUS_TONE[item.status]}>{item.status}</Badge>}
    >
      <div className="grid gap-5 px-5 py-4 lg:grid-cols-2">
        <div className="space-y-3 text-sm">
          {item.examples.length > 1 && (
            <div>
              <p className="mb-1 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">Also asked as</p>
              <ul className="space-y-1 text-slate-600">
                {item.examples.slice(1).map((q) => <li key={q}>“{q}”</li>)}
              </ul>
            </div>
          )}
          <div>
            <p className="mb-1 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">How agents answered</p>
            {item.agentAnswers.length ? (
              <ul className="space-y-2">
                {item.agentAnswers.map((a) => <li key={a} className="rounded-lg bg-indigo-50/70 px-3 py-2 text-slate-700">{a}</li>)}
              </ul>
            ) : (
              <p className="text-xs text-slate-500">No agent answer recorded.</p>
            )}
          </div>
          <p className="text-[11px] text-slate-400">Personal details were removed automatically; check before publishing.</p>
        </div>

        {item.status === 'published' ? (
          <div className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            <p className="font-medium">Published as {item.publishedPath}</p>
            <p className="mt-1 text-xs">It joins the knowledge base on the next index — use “Index new articles” above to do it now.</p>
          </div>
        ) : (
          <div className="space-y-2">
            <input value={draft.title} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} placeholder="Article title" disabled={!open} className={inputClass} aria-label="Article title" />
            <textarea
              value={draft.answer}
              onChange={(e) => setDraft((d) => ({ ...d, answer: e.target.value }))}
              rows={7}
              disabled={!open}
              placeholder="Write the article in Markdown — what the customer needs to know, step by step."
              className={inputClass}
              aria-label="Article body"
            />
            {(updateState.error || actState.error) && <p className="text-xs text-rose-700">{errorMessage(updateState.error ?? actState.error)}</p>}
            {open && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" icon="book" onClick={publish} loading={actState.isLoading} disabled={!draft.title.trim() || draft.answer.trim().length < 40}>
                  Publish article
                </Button>
                <Button size="sm" variant="secondary" onClick={() => update({ id: item.id, ...draft })} disabled={!dirty} loading={updateState.isLoading}>
                  Save draft
                </Button>
                <Button size="sm" variant="ghost" onClick={() => act({ id: item.id, action: 'reject' })}>
                  Dismiss
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

/** An agent-resolved case: approve it into the evaluation set (question + reference answer). */
function TestQuestionCard({ item, onDone }) {
  const [draft, setDraft] = useState({ question: item.question, answer: item.answer });
  const [update] = useUpdateReviewItemMutation();
  const [act, actState] = useReviewActionMutation();
  const open = item.status === 'pending';
  const dirty = draft.question !== item.question || draft.answer !== item.answer;

  const approve = async () => {
    if (dirty) await update({ id: item.id, ...draft }).unwrap();
    await act({ id: item.id, action: 'approve' }).unwrap();
    onDone('Added to the evaluation set. Run npm run eval:rag -- --include-reviewed to score the assistant on it.');
  };

  return (
    <Card title="Test question" description={`From ${item.conversationIds.length} resolved handoff`} aside={<Badge tone={STATUS_TONE[item.status]}>{item.status}</Badge>}>
      <div className="space-y-2 px-5 py-4">
        <label className="block text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
          Question
          <textarea value={draft.question} onChange={(e) => setDraft((d) => ({ ...d, question: e.target.value }))} rows={2} disabled={!open} className={`${inputClass} mt-1 font-normal tracking-normal text-slate-800 normal-case`} />
        </label>
        <label className="block text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
          Reference answer (from the agent)
          <textarea value={draft.answer} onChange={(e) => setDraft((d) => ({ ...d, answer: e.target.value }))} rows={4} disabled={!open} className={`${inputClass} mt-1 font-normal tracking-normal text-slate-800 normal-case`} />
        </label>
        {actState.error && <p className="text-xs text-rose-700">{errorMessage(actState.error)}</p>}
        {open && (
          <div className="flex gap-2">
            <Button size="sm" icon="check" onClick={approve} loading={actState.isLoading}>Add to evaluation set</Button>
            <Button size="sm" variant="ghost" onClick={() => act({ id: item.id, action: 'reject' })}>Reject</Button>
          </div>
        )}
        {item.status === 'approved' && <p className="text-xs text-emerald-700">In the evaluation set — run <code className="rounded bg-slate-100 px-1">npm run eval:rag -- --include-reviewed</code>.</p>}
      </div>
    </Card>
  );
}

const TABS = [
  { id: 'knowledge_gap', label: 'Knowledge gaps' },
  { id: 'test_question', label: 'Test questions' },
];

export function ReviewView() {
  const [kind, setKind] = useState('knowledge_gap');
  const [status, setStatus] = useState('pending');
  const { data: items = [], isFetching, error } = useGetReviewItemsQuery({ kind, ...(status && { status }) });
  const [runReview, runState] = useRunReviewMutation();
  const [reindex, reindexState] = useReindexKnowledgeMutation();
  const run = runState.data;
  const [notice, setNotice] = useState(null);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Tabs tabs={TABS} value={kind} onChange={setKind} className="w-72 rounded-lg bg-slate-100 p-1" />
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-lg border-0 py-1.5 pr-8 pl-3 text-sm ring-1 ring-slate-300" aria-label="Status">
          <option value="pending">To review</option>
          <option value="">All</option>
          <option value={kind === 'knowledge_gap' ? 'published' : 'approved'}>{kind === 'knowledge_gap' ? 'Published' : 'Approved'}</option>
          <option value="rejected">Dismissed</option>
        </select>
        <div className="ml-auto flex gap-2">
          <Button variant="secondary" size="sm" icon="refresh" onClick={() => runReview()} loading={runState.isLoading}>Review closed chats now</Button>
          <Button variant="secondary" size="sm" icon="book" onClick={() => reindex()} loading={reindexState.isLoading}>Index new articles</Button>
        </div>
      </div>
      {run && (
        <p className="text-xs text-slate-500">
          {run.skipped ?? `Reviewed ${run.conversations} closed conversation${run.conversations === 1 ? '' : 's'}: ${run.gapsNew} new gap${run.gapsNew === 1 ? '' : 's'}, ${run.gapsUpdated} added to existing ones, ${run.testQuestions} test question${run.testQuestions === 1 ? '' : 's'}.`}
        </p>
      )}
      {notice && (
        <p className="flex items-start gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
          <Icon name="checkCircle" className="mt-0.5 size-4 shrink-0" />
          {notice}
        </p>
      )}
      {reindexState.data && <p className="text-xs text-slate-500">Indexed: {reindexState.data.embedded} chunk(s) embedded, {reindexState.data.reused} reused. The assistant uses them within a minute.</p>}
      {(reindexState.error || runState.error) && <p className="text-xs text-rose-700">{errorMessage(reindexState.error ?? runState.error)}</p>}

      {error ? (
        <EmptyState icon="warning" title="Couldn’t load the review queue" description={errorMessage(error)} />
      ) : isFetching && !items.length ? (
        <div className="flex justify-center py-12 text-slate-400"><Spinner /></div>
      ) : items.length === 0 ? (
        <EmptyState icon="sparkles" title="Nothing to review" description="Closed conversations are reviewed every hour. Questions the help centre couldn’t answer and resolved handoffs appear here." />
      ) : (
        <div className="space-y-4">
          {items.map((item) =>
            item.kind === 'knowledge_gap' ? <GapCard key={item.id} item={item} onDone={setNotice} /> : <TestQuestionCard key={item.id} item={item} onDone={setNotice} />,
          )}
        </div>
      )}
      <p className="flex items-center gap-1.5 text-[11px] text-slate-400">
        <Icon name="lock" className="size-3.5" /> Nothing here is published or added automatically — every article and test question is approved by an admin.
      </p>
    </div>
  );
}
