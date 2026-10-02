import { useDispatch } from 'react-redux';
import { Brand } from '../../components/brand/Brand.jsx';
import { Avatar, Badge, Icon } from '../../components/ui/index.js';
import { signedIn } from '../authSlice.js';
import { DEMO_PERSONAS, saveDemoPersona } from '../demoPersonas.js';
import { ROLE, ROLE_LABEL } from '../roles.js';

/** Demo mode only (no Keycloak): choose who to be. Each persona sees a different workspace. */
export function DemoSignIn() {
  const dispatch = useDispatch();

  const choose = (persona) => {
    saveDemoPersona(persona.id);
    dispatch(signedIn(persona.user));
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-gradient-to-b from-slate-900 to-slate-800 px-4 py-10">
      <div className="w-full max-w-lg space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <Brand size="lg" subtitle="Support that knows when to pass the baton" />
        </div>

        <div className="rounded-2xl bg-white p-5 shadow-xl">
          <h1 className="text-sm font-semibold text-slate-900">Sign in to the demo as…</h1>
          <p className="mt-1 text-xs text-slate-500">
            Demo mode runs on an in-browser mock backend. Set <code className="rounded bg-slate-100 px-1">VITE_KEYCLOAK_URL</code> to sign in with Keycloak instead.
          </p>
          <ul className="mt-4 space-y-2">
            {DEMO_PERSONAS.map((persona) => (
              <li key={persona.id}>
                <button
                  type="button"
                  onClick={() => choose(persona)}
                  className="group flex w-full items-center gap-3 rounded-xl p-3 text-left ring-1 ring-slate-200 transition hover:bg-indigo-50/60 hover:ring-indigo-300"
                >
                  <Avatar name={persona.user.name} />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-medium text-slate-900">{persona.user.name}</span>
                      {persona.user.roles.map((role) => (
                        <Badge key={role} tone={role === ROLE.ADMIN ? 'violet' : role === ROLE.AGENT ? 'indigo' : 'sky'}>
                          {ROLE_LABEL[role]}
                        </Badge>
                      ))}
                    </span>
                    <span className="mt-0.5 block text-xs text-slate-500">{persona.blurb}</span>
                  </span>
                  <Icon name="arrowRight" className="size-4 text-slate-300 transition group-hover:text-indigo-500" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
