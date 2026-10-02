import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import App from './App.jsx';
import { usePath } from './app/router.jsx';
import { store } from './app/store.js';
import { DemoStore } from './features/demoStore/DemoStore.jsx';
import { WidgetFrame } from './features/widget/WidgetFrame.jsx';
import './index.css';

// Three entry points in one build:
//   /widget       the customer chat widget, inside the iframe /widget.js creates on a website (no sign-in)
//   /demo-store   a pretend website with the widget on it (no sign-in)
//   everything else  the staff app — agent desk and admin — behind Keycloak
function Root() {
  const path = usePath();
  if (path.startsWith('/widget')) return <WidgetFrame />;
  if (path.startsWith('/demo-store')) return <DemoStore />;
  return <App />;
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Provider store={store}>
      <Root />
    </Provider>
  </StrictMode>,
);
