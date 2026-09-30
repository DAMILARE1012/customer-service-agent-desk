import { parseArgs } from 'node:util';
import { config } from '../config.js';
import { runIngestion } from './pipeline.js';

const HELP = `Usage: npm run ingest -- [options]

Builds or incrementally updates the knowledge index in ${config.paths.index}

  (no options)      Respect each source's refresh window; re-embed only new/changed text
  --check           Ask every source for changes now, ignoring refresh windows
  --rebuild         Re-parse every source even if unchanged (vectors still reused for identical text)
  --reembed         Discard cached vectors and embed everything again
  --source=a,b      Only these sources (others are kept as they are)
  --limit=N         Only the first N documents per source (quick experiments)
  --help`;

const { values } = parseArgs({
  options: {
    check: { type: 'boolean', default: false },
    rebuild: { type: 'boolean', default: false },
    reembed: { type: 'boolean', default: false },
    source: { type: 'string' },
    limit: { type: 'string' },
    help: { type: 'boolean', default: false },
  },
});

if (values.help) {
  console.log(HELP);
  process.exit(0);
}

const limit = values.limit ? Number(values.limit) : null;
if (limit !== null && (!Number.isInteger(limit) || limit < 1)) {
  console.error('--limit must be a positive integer');
  process.exit(1);
}

const time = () => new Date().toLocaleTimeString();

try {
  const report = await runIngestion({
    check: values.check,
    rebuild: values.rebuild,
    reembed: values.reembed,
    only: values.source?.split(',').map((s) => s.trim()),
    limit,
    log: (message) => console.log(`${time()}  ${message}`),
  });

  console.log('\nSources');
  for (const s of report.sources) {
    const docs = s.documents
      ? ` · docs +${s.documents.added} ~${s.documents.changed} -${s.documents.removed} =${s.documents.unchanged}`
      : '';
    console.log(`  ${s.source.padEnd(8)} ${s.action.padEnd(10)} ${String(s.chunks).padStart(6)} chunks${docs}${s.reason ? ` · ${s.reason}` : ''}`);
  }
  if (report.removedSources.length) console.log(`  removed: ${report.removedSources.join(', ')}`);

  console.log(
    `\nIndex    ${report.total} chunks · embedded ${report.embedded} · reused ${report.reused}` +
      (report.resumed ? ` · resumed ${report.resumed}` : '') +
      (report.duplicates != null ? ` · ${report.duplicates} duplicates share a vector` : '') +
      ` · removed ${report.removedChunks}\n         wrote ${report.wrote} in ${(report.durationMs / 1000).toFixed(1)}s`,
  );
} catch (error) {
  console.error(`\nIngestion failed: ${error.message}`);
  process.exit(1);
}
