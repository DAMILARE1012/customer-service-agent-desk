import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

// Your own content: drop Markdown files into CONTENT_DIR. Optional front matter:
//
//   ---
//   title: Return policy
//   category: Returns & refunds
//   audience: customer        # or "agent" for internal procedures
//   url: /help/returns
//   ---

async function listMarkdownFiles(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true, recursive: true }).catch(() => []);
  return entries
    .filter((e) => e.isFile() && /\.mdx?$/i.test(e.name))
    .map((e) => path.join(e.parentPath ?? e.path, e.name))
    .sort();
}

function parseFrontMatter(source) {
  const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!match) return { meta: {}, body: source };
  const meta = Object.fromEntries(
    match[1]
      .split(/\r?\n/)
      .map((line) => line.match(/^\s*([\w-]+)\s*:\s*(.*?)(?:\s+#.*)?\s*$/)) // "# comment" needs a leading space, so url: /a#b survives
      .filter(Boolean)
      .map(([, key, value]) => [key, value.replace(/^["']|["']$/g, '')]),
  );
  return { meta, body: source.slice(match[0].length) };
}

export const localMarkdownAdapter = {
  id: 'local',
  label: 'Local content',
  boilerplate: [],

  // Local files are cheap to hash, so the "version" is a hash over every file's path and contents.
  async sync({ contentDir, previous }) {
    const hash = createHash('sha256');
    for (const file of await listMarkdownFiles(contentDir)) {
      hash.update(path.relative(contentDir, file)).update('\0').update(await fs.readFile(file)).update('\0');
    }
    const version = hash.digest('hex');
    return { changed: version !== previous.version, version, contentHash: version };
  },

  async *documents({ contentDir, limit }) {
    let count = 0;
    for (const file of await listMarkdownFiles(contentDir)) {
      if (limit && count >= limit) return;
      count += 1;
      const { meta, body } = parseFrontMatter(await fs.readFile(file, 'utf8'));
      const relative = path.relative(contentDir, file).replace(/\\/g, '/');
      const titleFromHeading = body.match(/^#\s+(.+)$/m)?.[1];
      yield {
        id: relative.replace(/\.mdx?$/i, ''),
        title: meta.title ?? titleFromHeading ?? path.basename(file, path.extname(file)),
        url: meta.url ?? relative,
        category: meta.category ?? path.dirname(relative).split('/')[0],
        audience: meta.audience === 'agent' ? 'agent' : 'customer',
        // The H1 duplicates the title, which is already prepended to every chunk's embedding input.
        markdown: titleFromHeading && !meta.title ? body.replace(/^#\s+.+$/m, '') : body,
      };
    }
  },
};
