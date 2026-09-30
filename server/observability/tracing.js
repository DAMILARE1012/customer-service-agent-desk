import { LangfuseClient } from '@langfuse/client';
import { LangfuseSpanProcessor } from '@langfuse/otel';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { config } from '../config.js';

// Traces go to Langfuse through OpenTelemetry. The SDK reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
// and LANGFUSE_BASE_URL from the environment (loaded from .env by config.js).
// Without keys, @langfuse/tracing calls become no-ops, so instrumented code runs unchanged.

let sdk = null;
let client = null;

/** Call once, before anything else runs. Returns whether tracing is active. */
export function initTracing() {
  if (!config.observability.langfuseEnabled) return false;
  if (!sdk) {
    sdk = new NodeSDK({ spanProcessors: [new LangfuseSpanProcessor({ environment: config.observability.environment })] });
    sdk.start();
  }
  return true;
}

/** Langfuse API client (scores, datasets, experiments), or null when Langfuse isn't configured. */
export function getLangfuse() {
  if (!config.observability.langfuseEnabled) return null;
  client ??= new LangfuseClient();
  return client;
}

/** Flush pending spans and scores. Required before a short-lived script exits. */
export async function shutdownTracing() {
  await client?.flush?.();
  await client?.shutdown?.();
  await sdk?.shutdown();
}
