import fs from 'node:fs/promises';
import path from 'node:path';
import { syncRemoteFile } from '../remoteFile.js';

const GUIDELINES_URL = 'https://raw.githubusercontent.com/asappresearch/abcd/master/data/guidelines.json';
const REPO_URL = 'https://github.com/asappresearch/abcd';

const slug = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

function renderSubflow(flow, subflow, { actions = [], instructions = [] }) {
  const [intro, ...outro] = instructions;
  const steps = actions.map((action, i) => {
    const button = action.button && action.button !== 'N/A' ? ` [${action.button}]` : '';
    const detail = action.subtext.map((line) => `  - ${line}`).join('\n');
    return `${i + 1}.${button} ${action.text.replace(/\s+/g, ' ').trim()}${detail ? `\n${detail}` : ''}`;
  });
  return [flow.description && `Flow: ${flow.description}.`, intro, steps.join('\n'), ...outro].filter(Boolean).join('\n\n');
}

/**
 * Agent procedures from the ABCD dataset (ASAPP, MIT): 55 step-by-step flows such as refunds,
 * identity verification and order issues. Agent-only — never used to answer customers directly.
 */
export const abcdAdapter = {
  id: 'abcd',
  label: 'ABCD agent guidelines',
  boilerplate: [],

  async sync({ rawDir, previous }) {
    return syncRemoteFile({ url: GUIDELINES_URL, dest: path.join(rawDir, 'guidelines.json'), previous });
  },

  async *documents({ rawDir, limit }) {
    const guidelines = JSON.parse(await fs.readFile(path.join(rawDir, 'guidelines.json'), 'utf8'));
    let count = 0;
    for (const [flowName, flow] of Object.entries(guidelines)) {
      for (const [subflowName, subflow] of Object.entries(flow.subflows)) {
        if (limit && count >= limit) return;
        count += 1;
        yield {
          id: `${slug(flowName)}/${slug(subflowName)}`,
          title: `${flowName}: ${subflowName}`,
          url: `${REPO_URL}#${slug(subflowName)}`,
          category: flowName,
          audience: 'agent',
          markdown: renderSubflow(flow, subflowName, subflow),
        };
      }
    }
  },
};
