import { ROLE } from './roles.js';

// Without Keycloak (VITE_KEYCLOAK_URL empty) the app runs against the in-browser mock backend and you
// pick who to be. The same people exist as Keycloak users in infra/keycloak/import/baton-realm.json.
export const DEMO_PERSONAS = [
  {
    id: 'maya',
    blurb: 'Customer · Plus tier. Asks the assistant for help and gets handed to a person when needed.',
    user: { sub: 'demo-maya', username: 'maya.chen', name: 'Maya Chen', email: 'maya.chen@example.com', roles: [ROLE.CUSTOMER] },
  },
  {
    id: 'alex',
    blurb: 'Support agent. Works the handoff queue with the bot’s brief and copilot drafts.',
    user: { sub: 'demo-alex', username: 'alex.rivera', name: 'Alex Rivera', email: 'alex.rivera@baton.example', roles: [ROLE.AGENT] },
  },
  {
    id: 'jade',
    blurb: 'Admin and agent. Manages agents and handoff policy, sees every conversation.',
    user: { sub: 'demo-jade', username: 'jade.kim', name: 'Jade Kim', email: 'jade.kim@baton.example', roles: [ROLE.ADMIN, ROLE.AGENT] },
  },
];

const KEY = 'baton.demoPersona';

export function loadDemoPersona() {
  try {
    return DEMO_PERSONAS.find((p) => p.id === sessionStorage.getItem(KEY)) ?? null;
  } catch {
    return null;
  }
}

export function saveDemoPersona(id) {
  try {
    if (id) sessionStorage.setItem(KEY, id);
    else sessionStorage.removeItem(KEY);
  } catch {
    // Storage unavailable (private mode): the choice lasts until reload.
  }
}
