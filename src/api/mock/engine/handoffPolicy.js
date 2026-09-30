import { HANDOFF_POLICY, HANDOFF_PRECEDENCE, HANDOFF_REASON, PRIORITY } from '../../../constants/handoff.js';

export { HANDOFF_POLICY };

// Exported so the real backend applies exactly the same rules.
export const HUMAN_REQUEST =
  /\b(human|real person|actual person|agent|representative|operator|someone real|live (chat|support)|(speak|talk) (to|with) (a |an )?(person|someone|manager))\b/i;

export const SENSITIVE_TOPICS = [
  { topic: 'Unauthorized charge or fraud', pattern: /unauthori[sz]ed|fraud|didn['’]?t (make|authori[sz]e)|chargeback|dispute the charge/i },
  { topic: 'Legal threat', pattern: /\b(lawyer|attorney|legal action|sue|court)\b/i },
  { topic: 'Account closure & data deletion', pattern: /\b(close|delete|remove|erase)\b.{0,20}\b(account|data)\b|gdpr|right to be forgotten/i },
  { topic: 'Product safety', pattern: /\b(injur\w*|caught fire|burn(ed|t)|unsafe|hazard|smok(e|ing))\b/i },
];

const pct = (n) => `${Math.round(n * 100)}%`;

/**
 * Evaluates every handoff signal for a single customer turn.
 * Returns all signals that fired (the agent sees them all) plus the primary one.
 */
export function evaluateHandoff({ text, retrieval, sentiment, failedAttempts }) {
  const signals = [];

  const sensitive = SENSITIVE_TOPICS.find(({ pattern }) => pattern.test(text));
  if (sensitive) {
    signals.push({
      reason: HANDOFF_REASON.SENSITIVE_TOPIC,
      detail: `${sensitive.topic} — policy requires a human.`,
      topic: sensitive.topic,
    });
  }

  if (HUMAN_REQUEST.test(text)) {
    signals.push({ reason: HANDOFF_REASON.CUSTOMER_REQUEST, detail: 'Customer explicitly asked to speak with a person.' });
  }

  if (sentiment <= HANDOFF_POLICY.sentimentThreshold) {
    signals.push({
      reason: HANDOFF_REASON.NEGATIVE_SENTIMENT,
      detail: `Sentiment fell to ${sentiment.toFixed(2)} (threshold ${HANDOFF_POLICY.sentimentThreshold}).`,
    });
  }

  const confident = retrieval.confidence >= HANDOFF_POLICY.answerThreshold;
  const attemptsIncludingThisTurn = failedAttempts + 1;
  if (!confident && attemptsIncludingThisTurn >= HANDOFF_POLICY.maxFailedAttempts) {
    signals.push({
      reason: HANDOFF_REASON.REPEATED_FAILURE,
      detail: `${attemptsIncludingThisTurn} turns in a row without a confident answer (best match ${pct(retrieval.confidence)}).`,
    });
  } else if (
    retrieval.confidence < HANDOFF_POLICY.noMatchThreshold &&
    retrieval.terms.length >= HANDOFF_POLICY.minTermsForNoMatch
  ) {
    signals.push({
      reason: HANDOFF_REASON.LOW_CONFIDENCE,
      detail: `Best knowledge-base match scored ${pct(retrieval.confidence)} — nothing covers this question.`,
    });
  }

  const primary = HANDOFF_PRECEDENCE.map((reason) => signals.find((s) => s.reason === reason)).find(Boolean) ?? null;
  return { shouldHandoff: primary !== null, primary, signals };
}

export function computePriority({ reason, sentiment, tier }) {
  if (reason === HANDOFF_REASON.SENSITIVE_TOPIC || sentiment <= -0.7) return PRIORITY.URGENT;
  if (
    tier === 'enterprise' ||
    reason === HANDOFF_REASON.NEGATIVE_SENTIMENT ||
    reason === HANDOFF_REASON.REPEATED_FAILURE
  ) {
    return PRIORITY.HIGH;
  }
  return PRIORITY.NORMAL;
}

export function detectSmallTalk(text) {
  const trimmed = text.trim();
  if (/^(hi|hello|hey|good (morning|afternoon|evening))( there)?[\s!.]*$/i.test(trimmed)) return 'greeting';
  if (/^(ok(ay)?[,\s]*)?(thanks|thank you|thx|ty|great|perfect|awesome|cool|got it)([\s,!.]+(so much|a lot|again))?[\s!.]*$/i.test(trimmed)) {
    return 'thanks';
  }
  return null;
}
