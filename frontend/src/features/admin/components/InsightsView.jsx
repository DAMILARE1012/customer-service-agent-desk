import { EmptyState, Icon, Spinner } from '../../../components/ui/index.js';
import { STATUS_META } from '../../../constants/conversation.js';
import { SOLID_TONES } from '../../../components/ui/tones.js';
import { HANDOFF_REASON_META } from '../../../constants/handoff.js';
import { errorMessage, formatDuration, formatPercent } from '../../../utils/format.js';
import { useGetInsightsQuery } from '../adminApi.js';
import { Card } from './Card.jsx';

function StatTile({ label, value, detail }) {
  return (
    <div className="rounded-xl bg-white px-4 py-3.5 shadow-sm ring-1 ring-slate-200">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</p>
      {detail && <p className="mt-0.5 text-[11px] text-slate-500">{detail}</p>}
    </div>
  );
}

/** One series (handoff count per reason): a single hue, labels and values as text, hover for detail. */
function ReasonBars({ rows }) {
  if (!rows.length) return <p className="px-5 py-8 text-center text-xs text-slate-400">No handoffs yet.</p>;
  const max = Math.max(...rows.map((r) => r.count));
  const total = rows.reduce((sum, r) => sum + r.count, 0);
  return (
    <ul className="space-y-3 px-5 py-4">
      {rows.map((row) => (
        <li key={row.reason} title={`${row.label}: ${row.count} of ${total} handoffs (${formatPercent(row.count / total)})`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
            <span className="flex items-center gap-1.5 font-medium text-slate-700">
              <Icon name={HANDOFF_REASON_META[row.reason]?.icon ?? 'question'} className="size-3.5 text-slate-400" />
              {row.label}
            </span>
            <span className="text-slate-500 tabular-nums">
              {row.count} <span className="text-slate-400">· {formatPercent(row.count / total)}</span>
            </span>
          </div>
          <div className="h-2 rounded-full bg-slate-100">
            <div className="h-2 rounded-r-[4px] rounded-l-full bg-indigo-500" style={{ width: `${Math.max(2, (row.count / max) * 100)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function StatusList({ byStatus }) {
  return (
    <ul className="divide-y divide-slate-100">
      {Object.entries(STATUS_META).map(([status, meta]) => (
        <li key={status} className="flex items-center justify-between px-5 py-2.5 text-sm">
          <span className="flex items-center gap-2 text-slate-700">
            <span className={`size-2 rounded-full ${SOLID_TONES[meta.tone]}`} />
            {meta.label}
          </span>
          <span className="font-medium text-slate-900 tabular-nums">{byStatus[status] ?? 0}</span>
        </li>
      ))}
    </ul>
  );
}

function Metric({ label, value, hint, score = false }) {
  // Shares read as percentages; ranking scores (nDCG, MRR) are 0–1 numbers, not percentages.
  const shown = value == null ? '—' : score ? value.toFixed(2) : formatPercent(value);
  return (
    <div title={hint}>
      <dt className="text-[11px] text-slate-500">{label}</dt>
      <dd className="text-lg font-semibold text-slate-900 tabular-nums">{shown}</dd>
    </div>
  );
}

function Evaluation({ evaluation }) {
  const { retrieval, endToEnd } = evaluation;
  if (!retrieval && !endToEnd) {
    return <p className="px-5 py-6 text-xs text-slate-500">No evaluation reports yet. Run <code className="rounded bg-slate-100 px-1">npm run eval</code> (retrieval) and <code className="rounded bg-slate-100 px-1">npm run eval:rag</code> (end to end) on the backend.</p>;
  }
  return (
    <div className="divide-y divide-slate-100">
      {retrieval && (
        <div className="px-5 py-4">
          <p className="mb-2 text-xs font-medium text-slate-700">
            Retrieval · {retrieval.questions} WixQA questions · {retrieval.mode} search
          </p>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label="Right article in top 5" value={retrieval.hitAt5} />
            <Metric label="Recall@5" value={retrieval.recallAt5} />
            <Metric label="nDCG@5" value={retrieval.ndcgAt5} score hint="Rewards correct articles ranked higher (0–1)" />
            <Metric label="MRR" value={retrieval.mrr} score hint="Mean reciprocal rank of the first correct article (0–1)" />
          </dl>
        </div>
      )}
      {endToEnd && (
        <div className="px-5 py-4">
          <p className="mb-2 flex items-center justify-between gap-2 text-xs font-medium text-slate-700">
            <span>End to end · {endToEnd.model}</span>
            {endToEnd.url && (
              <a href={endToEnd.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-500">
                Run in Langfuse <Icon name="external" className="size-3.5" />
              </a>
            )}
          </p>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label="Correct & grounded" value={endToEnd.correctAndGrounded} hint="Answered, correct (≥ 0.75) and faithful (≥ 0.9)" />
            <Metric label="Faithfulness" value={endToEnd.faithfulness} hint="Share of the answer's claims supported by the sources" />
            <Metric label="Answer correctness" value={endToEnd.answerCorrectness} />
            <Metric label="Off-topic handed off" value={endToEnd.handoffCorrect} />
            <Metric label="Context recall" value={endToEnd.contextRecall} />
            <Metric label="Answer relevance" value={endToEnd.answerRelevance} />
            <Metric label="Cites a correct article" value={endToEnd.citationCorrect} />
          </dl>
        </div>
      )}
    </div>
  );
}

const LINKS = [
  { key: 'grafana', label: 'Grafana', description: 'Live latency, cost, rates and alerts', icon: 'chart' },
  { key: 'langfuse', label: 'Langfuse', description: 'Traces, judge scores and experiments', icon: 'search' },
  { key: 'keycloakUsers', label: 'Keycloak users', description: 'Invite agents, assign roles', icon: 'users' },
];

export function InsightsView() {
  const { data, error, isLoading } = useGetInsightsQuery(undefined, { pollingInterval: 15_000 });

  if (isLoading) return <div className="flex justify-center py-16 text-slate-400"><Spinner /></div>;
  if (error) return <EmptyState icon="warning" title="Couldn’t load insights" description={errorMessage(error)} />;

  const { conversations, handoffs, bot, evaluation, links } = data;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile label="Conversations" value={conversations.total} detail={`${conversations.byStatus.handoff_pending ?? 0} waiting for an agent`} />
        <StatTile label="Handed to a person" value={formatPercent(handoffs.rate)} detail={`${handoffs.conversationsHandedOff} conversations`} />
        <StatTile label="Bot answer rate" value={formatPercent(bot.answerRate)} detail={`of ${bot.questions} questions`} />
        <StatTile label="Median wait for an agent" value={handoffs.medianWaitSeconds == null ? '—' : formatDuration(handoffs.medianWaitSeconds * 1000)} />
        <StatTile label="Resolved without an agent" value={bot.resolvedWithoutAgent} detail={`of ${bot.resolved} resolved`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Why the assistant stepped aside" description="Handoffs by primary reason" className="lg:col-span-2">
          <ReasonBars rows={handoffs.byReason} />
        </Card>
        <Card title="Conversations by state">
          <StatusList byStatus={conversations.byStatus} />
        </Card>
      </div>

      <Card title="Answer quality" description="Latest offline evaluation (LLM-as-judge on expert-written WixQA questions)">
        <Evaluation evaluation={evaluation} />
      </Card>

      {links && (
        <div className="grid gap-3 sm:grid-cols-3">
          {LINKS.map((link) => (
            <a key={link.key} href={links[link.key]} target="_blank" rel="noreferrer" className="group flex items-center gap-3 rounded-xl bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200 transition hover:ring-indigo-300">
              <span className="rounded-lg bg-slate-100 p-2 text-slate-500 group-hover:text-indigo-600">
                <Icon name={link.icon} className="size-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-slate-900">{link.label}</span>
                <span className="block truncate text-xs text-slate-500">{link.description}</span>
              </span>
              <Icon name="external" className="size-4 text-slate-300 group-hover:text-indigo-500" />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
