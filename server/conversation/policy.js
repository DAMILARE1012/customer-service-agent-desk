import { HUMAN_REQUEST, SENSITIVE_TOPICS } from '../../src/api/mock/engine/handoffPolicy.js';
import { HANDOFF_PRECEDENCE, HANDOFF_REASON } from '../../src/constants/handoff.js';
import { config } from '../config.js';

// When the real bot steps aside. The conversation-level rules (sensitive topics, asking for a
// person, frustration) are shared with the demo; the knowledge-level rules use the calibrated
// retrieval threshold and the LLM's own verdict on whether the sources answer the question.

const pct = (n) => `${Math.round(n * 100)}%`;
const wordCount = (text) => text.trim().split(/\s+/).filter(Boolean).length;

/** Signals that don't need the knowledge base. If any fire, the LLM isn't called at all. */
export function conversationSignals({ text, sentiment }) {
  const signals = [];
  const sensitive = SENSITIVE_TOPICS.find(({ pattern }) => pattern.test(text));
  if (sensitive) {
    signals.push({ reason: HANDOFF_REASON.SENSITIVE_TOPIC, detail: `${sensitive.topic} — policy requires a human.`, topic: sensitive.topic });
  }
  if (HUMAN_REQUEST.test(text)) {
    signals.push({ reason: HANDOFF_REASON.CUSTOMER_REQUEST, detail: 'Customer explicitly asked to speak with a person.' });
  }
  if (sentiment <= config.policy.sentimentThreshold) {
    signals.push({
      reason: HANDOFF_REASON.NEGATIVE_SENTIMENT,
      detail: `Sentiment fell to ${sentiment.toFixed(2)} (threshold ${config.policy.sentimentThreshold}).`,
    });
  }
  return signals;
}

/**
 * Signals from the answer attempt. Returns [] when the bot should keep going (answer or clarify).
 * @param {{ result: { status: string, retrieval: { confidence: number }, error?: string }, text: string, failedAttempts: number }} params
 */
export function answerSignals({ result, text, failedAttempts }) {
  const { confidence } = result.retrieval;
  const attempts = failedAttempts + 1;

  switch (result.status) {
    case 'error':
      return [{ reason: HANDOFF_REASON.ASSISTANT_UNAVAILABLE, detail: `The language model call failed: ${result.error}` }];
    case 'no_match':
      // A substantive question with nothing relevant in the KB goes straight to a person;
      // a vague one ("it's not working") gets a clarifying question first.
      if (wordCount(text) >= 4) {
        return [{
          reason: HANDOFF_REASON.LOW_CONFIDENCE,
          detail: `Best knowledge-base match was ${pct(confidence)}, below the ${pct(config.policy.noMatchThreshold)} no-match threshold.`,
        }];
      }
      break;
    case 'unanswerable':
      break;
    default:
      return [];
  }

  if (attempts >= config.policy.maxFailedAttempts) {
    return [{
      reason: HANDOFF_REASON.REPEATED_FAILURE,
      detail: `${attempts} turns in a row without a grounded answer (best match ${pct(confidence)}).`,
    }];
  }
  return [];
}

/** Pick the primary reason by precedence; every signal is kept for the agent's brief. */
export function decide(signals) {
  const primary = HANDOFF_PRECEDENCE.map((reason) => signals.find((s) => s.reason === reason)).find(Boolean) ?? null;
  return { shouldHandoff: primary !== null, primary, signals };
}
