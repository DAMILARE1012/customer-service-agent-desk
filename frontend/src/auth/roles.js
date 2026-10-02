// The three kinds of people who use Baton, as Keycloak realm roles, and the workspace each one gets.

export const ROLE = Object.freeze({
  CUSTOMER: 'customer',
  AGENT: 'agent',
  ADMIN: 'admin',
});

export const isStaff = (user) => user.roles.includes(ROLE.AGENT) || user.roles.includes(ROLE.ADMIN);

// Order = where each person lands after sign-in (the first workspace they can use).
export const WORKSPACES = [
  { id: 'desk', path: '/desk', label: 'Desk', icon: 'inbox', description: 'Handoff queue and conversations', allows: (u) => u.roles.includes(ROLE.AGENT) },
  { id: 'admin', path: '/admin', label: 'Admin', icon: 'sliders', description: 'Agents, policy and insights', allows: (u) => u.roles.includes(ROLE.ADMIN) },
  // Staff accounts never chat as customers (the API refuses it too).
  { id: 'chat', path: '/chat', label: 'Support chat', icon: 'chat', description: 'Get help from Baton', allows: (u) => u.roles.includes(ROLE.CUSTOMER) && !isStaff(u) },
];

export const workspacesFor = (user) => WORKSPACES.filter((w) => w.allows(user));

export const workspaceAt = (path) => WORKSPACES.find((w) => path === w.path || path.startsWith(`${w.path}/`));

export const homePathFor = (user) => workspacesFor(user)[0]?.path ?? '/no-access';

export const ROLE_LABEL = { [ROLE.CUSTOMER]: 'Customer', [ROLE.AGENT]: 'Agent', [ROLE.ADMIN]: 'Admin' };
