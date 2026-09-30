// Bump when the splitting rules change (part of the pipeline fingerprint).
export const CHUNKER_VERSION = 3;

const HEADING = /^(#{1,6})\s+(.+)$/;

/** Split markdown into sections at headings; each section knows its heading path. */
function toSections(markdown) {
  const sections = [];
  const path = [];
  let current = { headingPath: [], heading: null, blocks: [] };

  for (const block of markdown.split(/\n{2,}/)) {
    // Hand-written markdown often has text directly under the heading ("# Title\nBody").
    const [firstLine, ...rest] = block.trim().split('\n');
    const match = firstLine.match(HEADING);
    if (!match) {
      if (block.trim()) current.blocks.push(block.trim());
      continue;
    }
    sections.push(current);
    const level = match[1].length;
    const title = match[2].trim();
    while (path.length && path.at(-1).level >= level) path.pop();
    path.push({ level, title });
    current = { headingPath: path.map((p) => p.title), heading: firstLine, blocks: [] };
    if (rest.join('\n').trim()) current.blocks.push(rest.join('\n').trim());
  }
  sections.push(current);
  return sections.filter((s) => s.blocks.length);
}

/** Break one oversized block into pieces that fit: by line, then sentence, then word. */
function splitOversized(block, countTokens, maxTokens) {
  const byLevel = [(t) => t.split('\n'), (t) => t.split(/(?<=[.!?])\s+/), (t) => t.split(/\s+/)];
  const joiners = ['\n', ' ', ' '];

  const split = (text, level) => {
    if (countTokens(text) <= maxTokens || level >= byLevel.length) return [text];
    const parts = byLevel[level](text).filter(Boolean);
    if (parts.length === 1) return split(text, level + 1);
    const pieces = [];
    let buffer = '';
    for (const part of parts) {
      const candidate = buffer ? `${buffer}${joiners[level]}${part}` : part;
      if (countTokens(candidate) <= maxTokens) buffer = candidate;
      else {
        if (buffer) pieces.push(buffer);
        buffer = part;
      }
    }
    if (buffer) pieces.push(buffer);
    return pieces.flatMap((piece) => split(piece, level + 1));
  };

  return split(block, 0);
}

/** An inline heading (from a folded-in small section) must stay with the block after it. */
function glueHeadings(pieces) {
  const glued = [];
  for (let i = 0; i < pieces.length; i += 1) {
    if (HEADING.test(pieces[i]) && i + 1 < pieces.length) {
      glued.push(`${pieces[i]}\n${pieces[i + 1]}`);
      i += 1;
    } else glued.push(pieces[i]);
  }
  return glued;
}

/** Greedily pack a section's blocks into chunks of roughly `targetTokens`. */
function packSection(blocks, { countTokens, minTokens, targetTokens, maxTokens }) {
  const pieces = glueHeadings(blocks).flatMap((block) => splitOversized(block, countTokens, maxTokens));
  const chunks = [];
  let buffer = [];
  let tokens = 0;

  for (const piece of pieces) {
    const size = countTokens(piece);
    // Close the chunk once it reaches the target — but never while it's still tiny (an intro like
    // "perform the following actions:" belongs with the list after it), unless that would exceed max.
    const overTarget = tokens + size > targetTokens && tokens >= minTokens;
    if (buffer.length && (overTarget || tokens + size > maxTokens)) {
      chunks.push(buffer.join('\n\n'));
      buffer = [];
      tokens = 0;
    }
    buffer.push(piece);
    tokens += size;
  }
  if (buffer.length) {
    const tail = buffer.join('\n\n');
    // A tiny remainder reads better as the end of the previous chunk than as a chunk of its own.
    const previous = chunks.at(-1);
    if (previous && tokens < minTokens && countTokens(`${previous}\n\n${tail}`) <= maxTokens) chunks[chunks.length - 1] = `${previous}\n\n${tail}`;
    else chunks.push(tail);
  }
  return chunks;
}

/**
 * Heading-aware chunking.
 *
 * Sections never share a chunk, except that a section smaller than `minTokens` is folded into the
 * next one (with its heading kept inline). That keeps edits local: changing one section only
 * changes that section's chunks, so only they get re-embedded. Fixed-size sliding windows would
 * shift every chunk after an edit.
 *
 * @returns {{ headingPath: string[], text: string, tokens: number }[]}
 */
export function chunkMarkdown(markdown, { countTokens, minTokens, targetTokens, maxTokens }) {
  const sections = toSections(markdown);
  const merged = [];
  let carry = null;

  for (const section of sections) {
    const blocks = carry ? [...carry.blocks, ...(section.heading ? [section.heading] : []), ...section.blocks] : section.blocks;
    const headingPath = carry ? carry.headingPath : section.headingPath;
    const candidate = { headingPath, blocks };
    const size = countTokens(blocks.join('\n\n'));
    if (size < minTokens) carry = candidate;
    else {
      merged.push(candidate);
      carry = null;
    }
  }
  // A small trailing section joins the previous one if it fits; otherwise it stands alone.
  if (carry) {
    const last = merged.at(-1);
    const sameSection = last && carry.headingPath.join('\u0000') === last.headingPath.join('\u0000');
    const tail = sameSection || !carry.headingPath.length ? carry.blocks : [`## ${carry.headingPath.at(-1)}`, ...carry.blocks];
    if (last && countTokens([...last.blocks, ...tail].join('\n\n')) <= maxTokens) last.blocks.push(...tail);
    else merged.push(carry);
  }

  return merged.flatMap(({ headingPath, blocks }) =>
    packSection(blocks, { countTokens, minTokens, targetTokens, maxTokens }).map((text) => ({ headingPath, text, tokens: countTokens(text) })),
  );
}
