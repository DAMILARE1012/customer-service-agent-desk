// Bump when any rule below changes. The version is part of the pipeline fingerprint, so a bump
// makes every source re-parse on the next run (vectors are still reused where text is unchanged).
export const NORMALIZER_VERSION = 1;

const INVISIBLE = /[\u00AD\u200B-\u200F\u2060-\u2064\uFEFF]/g; // soft hyphen, zero-width chars, BOM
const CONTROL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;
const ODD_SPACES = /[\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000\t]/g;
const LINE_SEPARATORS = /\r\n?|[\u2028\u2029]/g;

/**
 * Meaning-preserving cleanup. The result is what agents see and what the LLM quotes, so nothing
 * here rewrites content: identifiers (#48213, $249.99, SAVE20), URLs and arrows are left alone.
 *
 * @param {string} text
 * @param {{ boilerplate?: RegExp[] }} [options] per-source patterns for text that carries no information
 */
export function cleanText(text, { boilerplate = [] } = {}) {
  let result = text
    .normalize('NFKC')
    .replace(LINE_SEPARATORS, '\n')
    .replace(INVISIBLE, '')
    .replace(CONTROL, '')
    .replace(ODD_SPACES, ' ');

  for (const pattern of boilerplate) result = result.replace(pattern, '');

  return result
    .split('\n')
    .map((line) => line.replace(/(\S) {2,}/g, '$1 ').trimEnd()) // keep leading indentation (nested lists)
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/**
 * Extra folding applied only to what gets indexed (embedding input + keyword index), never to the
 * text shown to people. Queries go through the same function so both sides match.
 */
export function indexForm(text) {
  return text
    .replace(/[\u2018\u2019\u201A\u201B\u2032]/g, "'")
    .replace(/[\u201C\u201D\u201E\u201F\u2033]/g, '"')
    .replace(/[\u2010-\u2015]/g, '-');
}

export const normalizeQuery = (query) => indexForm(cleanText(query));
