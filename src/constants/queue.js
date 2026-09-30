import { config } from '../config.js';

export const QUEUE_VIEW = Object.freeze({
  NEEDS_AGENT: 'needs_agent',
  MINE: 'mine',
  BOT_LIVE: 'bot_live',
  ALL: 'all',
});

export const QUEUE_VIEWS = [
  { id: QUEUE_VIEW.NEEDS_AGENT, label: 'Waiting' },
  { id: QUEUE_VIEW.MINE, label: 'Mine' },
  { id: QUEUE_VIEW.BOT_LIVE, label: 'Bot live' },
  { id: QUEUE_VIEW.ALL, label: 'All' },
];

export const POLLING_INTERVAL_MS = config.api.pollingIntervalMs;
