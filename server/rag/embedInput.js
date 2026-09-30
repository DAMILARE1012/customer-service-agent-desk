import { indexForm } from '../ingest/transform/normalize.js';

/**
 * The exact text indexed for a chunk, for both the vector and keyword index. Title and section
 * path give a short chunk the context it needs ("Refunds › Timelines: within 2 business days").
 */
export const embedInput = (chunk) => indexForm([chunk.title, chunk.headingPath.join(' > '), chunk.text].filter(Boolean).join('\n'));
