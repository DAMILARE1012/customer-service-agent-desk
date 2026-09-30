import { startActiveObservation } from '@langfuse/tracing';
import { config } from '../config.js';
import { llmCost, llmDuration, llmRequests, llmTokens } from '../observability/metrics.js';

export class LlmError extends Error {
  constructor(message, { status = null, code = null, retryable = false } = {}) {
    super(message);
    this.name = 'LlmError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function costOf(model, usage) {
  const [input = 0, output = 0] = config.llm.prices[model] ?? [];
  return {
    input: ((usage.prompt_tokens ?? 0) * input) / 1e6,
    output: ((usage.completion_tokens ?? 0) * output) / 1e6,
  };
}

const MAX_RETRY_WAIT_MS = 60_000;

/**
 * How long to wait before retrying: Groq's retry-after header, else the "try again in 7.5s" hint in
 * the 429 message (tokens-per-minute limits often need more than a few seconds), else backoff.
 */
function retryDelayMs(res, payload, attempt) {
  const header = Number(res?.headers.get('retry-after'));
  const hint = String(payload?.error?.message ?? '').match(/try again in (?:(\d+)m)?([\d.]+)s/i);
  const seconds = Number.isFinite(header) && header > 0 ? header : hint ? Number(hint[1] ?? 0) * 60 + Number(hint[2]) : null;
  return seconds != null ? Math.min(seconds * 1000 + 250, MAX_RETRY_WAIT_MS) : 500 * 2 ** attempt;
}

async function post(body, maxRetries = config.llm.maxRetries) {
  const { apiKey, baseUrl, timeoutMs } = config.llm;
  if (!apiKey) throw new LlmError('GROQ_API_KEY is not set.', { code: 'missing_api_key' });

  for (let attempt = 0; ; attempt += 1) {
    let res;
    try {
      res = await fetch(`${baseUrl}/chat/completions`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (error) {
      const timeout = error.name === 'TimeoutError' || error.name === 'AbortError';
      if (attempt < maxRetries) {
        await wait(500 * 2 ** attempt);
        continue;
      }
      throw new LlmError(timeout ? `Groq timed out after ${timeoutMs} ms` : `Groq unreachable: ${error.message}`, {
        code: timeout ? 'timeout' : 'network',
      });
    }

    if (res.ok) return res.json();

    const payload = await res.json().catch(() => ({}));
    const code = payload?.error?.code ?? payload?.error?.type ?? null;
    const retryable = res.status === 429 || res.status >= 500;
    if (retryable && attempt < maxRetries) {
      await wait(retryDelayMs(res, payload, attempt));
      continue;
    }
    throw new LlmError(`Groq ${res.status}: ${payload?.error?.message ?? res.statusText}`, { status: res.status, code, retryable });
  }
}

const statusLabel = (error) => (error.status === 429 ? 'rate_limited' : error.code === 'timeout' ? 'timeout' : 'error');

/**
 * One chat completion, traced as a Langfuse generation and counted in Prometheus.
 *
 * @param {{ purpose: string, messages: object[], model?: string, temperature?: number, maxTokens?: number,
 *           responseFormat?: object, reasoningEffort?: string, maxRetries?: number }} request
 * @returns {Promise<{ content: string, usage: object, model: string }>}
 */
export function chat({ purpose, messages, model = config.llm.model, temperature = config.llm.temperature, maxTokens = config.llm.maxTokens, responseFormat, reasoningEffort, maxRetries }) {
  const body = {
    model,
    messages,
    temperature,
    max_completion_tokens: maxTokens,
    ...(responseFormat && { response_format: responseFormat }),
    ...(reasoningEffort && { reasoning_effort: reasoningEffort }),
  };

  return startActiveObservation(
    `llm:${purpose}`,
    async (generation) => {
      generation.update({ model, input: messages, modelParameters: { temperature, max_completion_tokens: maxTokens, ...(reasoningEffort && { reasoning_effort: reasoningEffort }) } });
      const endTimer = llmDuration.startTimer({ model, purpose });
      try {
        const data = await post(body, maxRetries);
        const content = data.choices?.[0]?.message?.content ?? '';
        const usage = data.usage ?? {};
        const cost = costOf(model, usage);

        llmRequests.inc({ model, purpose, status: 'ok' });
        llmTokens.inc({ model, purpose, type: 'prompt' }, usage.prompt_tokens ?? 0);
        llmTokens.inc({ model, purpose, type: 'completion' }, usage.completion_tokens ?? 0);
        llmCost.inc({ model, purpose }, cost.input + cost.output);

        generation.update({
          output: content,
          usageDetails: { input: usage.prompt_tokens ?? 0, output: usage.completion_tokens ?? 0 },
          costDetails: cost,
        });
        return { content, usage, model: data.model ?? model };
      } catch (error) {
        llmRequests.inc({ model, purpose, status: statusLabel(error) });
        generation.update({ level: 'ERROR', statusMessage: error.message });
        throw error;
      } finally {
        endTimer();
      }
    },
    { asType: 'generation' },
  );
}

/** chat() that parses a JSON reply; one retry if the model returns malformed JSON. */
export async function chatJson(request) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const reply = await chat(request);
      return { ...reply, json: JSON.parse(reply.content) };
    } catch (error) {
      const malformed = error instanceof SyntaxError || error.code === 'json_validate_failed';
      if (!malformed || attempt === 1) throw error;
    }
  }
  throw new LlmError('unreachable');
}
