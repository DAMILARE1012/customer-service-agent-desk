import { ROLE } from './roles.js';

// Without Keycloak (VITE_KEYCLOAK_URL empty) the staff app runs against the in-browser mock backend and you
// pick which staff member to be. Customers use the widget on the demo store (/demo-store). The same
// staff exist as Keycloak users in infra/keycloak/import/baton-realm.json.
export const DEMO_PERSONAS = [
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
