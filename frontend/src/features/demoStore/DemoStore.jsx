import { useEffect, useMemo, useState } from 'react';
import { Link } from '../../app/router.jsx';
import { config } from '../../config.js';
import { WidgetApp } from '../widget/WidgetApp.jsx';

// A pretend company website with the Baton widget on it — what your customers see. "Fernwood" is a
// made-up brand. The demo bar on top plays the part of the website's own login: in a real integration
// the website's backend signs the identity token; here the API's demo-only endpoint does.

const PRODUCTS = [
  { name: 'Linen throw', price: 64, tone: 'from-amber-100 to-orange-200' },
  { name: 'Stoneware mugs (set of 4)', price: 38, tone: 'from-stone-100 to-stone-300' },
  { name: 'Oak side table', price: 189, tone: 'from-yellow-100 to-amber-300' },
  { name: 'Wool rug, 160×230', price: 249, tone: 'from-rose-100 to-rose-200' },
  { name: 'Ceramic table lamp', price: 92, tone: 'from-sky-100 to-indigo-200' },
  { name: 'Herb planter trio', price: 45, tone: 'from-emerald-100 to-teal-200' },
];

// Demo-mode customers (the mock backend's seeded profiles); the real stack lists them from the API.
const MOCK_CUSTOMERS = [
  { id: 'cus_maya', name: 'Maya Chen', email: 'maya.chen@example.com' },
  { id: 'cus_jordan', name: 'Jordan Okafor', email: 'jordan@okafor-studio.com' },
  { id: 'cus_sam', name: 'Sam Patel', email: 'sam.patel@example.com' },
];

function guestVisitor() {
  let id = null;
  try {
    id = sessionStorage.getItem('baton.demo.visitor');
    if (!id) sessionStorage.setItem('baton.demo.visitor', (id = Math.random().toString(16).slice(2, 10)));
  } catch {
    id ??= 'guest';
  }
  return { sub: `visitor_${id}`, name: `Visitor ${id.slice(-4).toUpperCase()}`, email: null, roles: ['customer'], visitor: true };
}

/** Real stack: load the embed script once, like any website would. */
function useEmbedScript(enabled) {
  const [ready, setReady] = useState(Boolean(window.Baton?.loaded));
  useEffect(() => {
    if (!enabled || window.Baton?.loaded) return;
    const script = document.createElement('script');
    script.src = '/widget.js';
    script.async = true;
    script.onload = () => setReady(true);
    document.body.appendChild(script);
  }, [enabled]);
  return ready;
}

export function DemoStore() {
  const mock = !config.api.baseUrl;
  const [customers, setCustomers] = useState(mock ? MOCK_CUSTOMERS : []);
  const [signedInAs, setSignedInAs] = useState(''); // '' = guest
  const [note, setNote] = useState(null);
  const embedReady = useEmbedScript(!mock);

  useEffect(() => {
    if (mock) return;
    fetch(`${config.api.baseUrl}/widget/demo-customers`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('Set WIDGET_DEMO_IDENTITY=true to try signed-in customers.'))))
      .then(setCustomers, (e) => setNote(e.message));
  }, [mock]);

  // Real stack: tell the widget who is signed in to the store.
  useEffect(() => {
    if (mock || !embedReady) return;
    if (!signedInAs) {
      window.Baton.logout();
      return;
    }
    fetch(`${config.api.baseUrl}/widget/demo-identity`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ customerId: signedInAs }) })
      .then((res) => res.json())
      .then(({ identity }) => window.Baton.identify(identity), () => setNote('Couldn’t sign in as that customer.'));
  }, [mock, embedReady, signedInAs]);

  const demoUser = useMemo(() => {
    if (!mock) return null;
    const customer = customers.find((c) => c.id === signedInAs);
    return customer ? { sub: customer.id.replace(/^cus_/, ''), name: customer.name, email: customer.email, roles: ['customer'] } : guestVisitor();
  }, [mock, customers, signedInAs]);
  const [widgetState, setWidgetState] = useState({ open: false });

  return (
    <div className="min-h-full bg-stone-50 text-stone-800">
      {/* Demo bar: plays the website's login and links to the staff side. Not part of the store. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 bg-slate-900 px-4 py-2 text-xs text-slate-300">
        <span className="font-semibold text-white">Baton demo</span>
        <span>A pretend shop with the Baton chat widget (bottom right).</span>
        <label className="flex items-center gap-2">
          Signed in to the shop as
          <select value={signedInAs} onChange={(e) => setSignedInAs(e.target.value)} className="rounded border-0 bg-slate-800 py-1 pr-7 pl-2 text-xs text-white ring-1 ring-slate-600">
            <option value="">Guest (not signed in)</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        {note && <span className="text-amber-300">{note}</span>}
        <span className="ml-auto flex gap-3">
          {mock ? (
            <Link to="/desk" className="text-indigo-300 hover:text-white">Agent desk →</Link>
          ) : (
            <a href="/desk" target="_blank" rel="noreferrer" className="text-indigo-300 hover:text-white">Agent desk ↗</a>
          )}
        </span>
      </div>

      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <p className="font-serif text-2xl tracking-tight text-stone-900">Fernwood</p>
          <nav className="hidden gap-6 text-sm text-stone-600 sm:flex">
            <span>Living</span>
            <span>Kitchen</span>
            <span>Garden</span>
            <span>Sale</span>
          </nav>
          <p className="text-sm text-stone-600">{signedInAs ? `Hi, ${customers.find((c) => c.id === signedInAs)?.name.split(' ')[0] ?? ''}` : 'Sign in'} · Basket (0)</p>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        <section className="rounded-3xl bg-gradient-to-br from-amber-100 via-orange-50 to-rose-100 px-8 py-14">
          <p className="text-sm font-medium tracking-wide text-orange-700 uppercase">Autumn collection</p>
          <h1 className="mt-2 max-w-xl font-serif text-4xl leading-tight text-stone-900">Warm textures for slower evenings.</h1>
          <p className="mt-3 max-w-lg text-stone-600">Free delivery over $75, and 30-day returns on everything. Questions? Chat with us — bottom right.</p>
        </section>
        <section className="mt-10 grid grid-cols-2 gap-6 md:grid-cols-3">
          {PRODUCTS.map((p) => (
            <article key={p.name}>
              <div className={`aspect-[4/3] rounded-2xl bg-gradient-to-br ${p.tone}`} />
              <p className="mt-3 text-sm font-medium text-stone-900">{p.name}</p>
              <p className="text-sm text-stone-500">${p.price}</p>
            </article>
          ))}
        </section>
      </main>
      <footer className="border-t border-stone-200 py-8 text-center text-xs text-stone-400">Fernwood is a fictional shop used to demo Baton.</footer>

      {/* Demo mode only: the widget inline, sharing the in-browser mock backend with the desk. The real
          stack embeds it with /widget.js (an iframe) like any website. */}
      {mock && (
        <div className={`fixed right-3 bottom-3 z-50 ${widgetState.open ? 'h-[min(680px,calc(100vh-24px))] w-[min(384px,calc(100vw-24px))]' : ''}`}>
          <WidgetApp key={demoUser?.sub} demoUser={demoUser} onState={setWidgetState} />
        </div>
      )}
    </div>
  );
}
