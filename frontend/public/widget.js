/*!
 * Baton chat widget — embed on your website with one tag:
 *
 *   <script src="https://YOUR-BATON-HOST/widget.js" async></script>
 *
 * Customers never sign in to Baton. Guests chat anonymously. For a customer already signed in to your
 * site, have your backend sign a short-lived identity token (see the README) and pass it in:
 *
 *   Baton.identify(identityToken)   // on every page load while they're signed in
 *   Baton.logout()                  // when they sign out of your site
 *   Baton.open() / Baton.close()
 *
 * Calls made before this script finishes loading are queued: window.Baton = window.Baton || { q: [] }.
 * The chat runs in an iframe, so your page's styles can't break it and it can't read your page.
 */
(function () {
  if (window.Baton && window.Baton.loaded) return;
  var script = document.currentScript;
  var origin = (script && script.getAttribute('data-baton-url')) || new URL(script ? script.src : '/', location.href).origin;
  var queued = (window.Baton && window.Baton.q) || [];
  var ready = false;
  var pending = [];
  var open = false;

  var frame = document.createElement('iframe');
  frame.src = origin + '/widget';
  frame.title = 'Support chat';
  frame.setAttribute('allowtransparency', 'true');
  frame.style.cssText = 'position:fixed;right:12px;bottom:12px;width:76px;height:76px;border:0;background:transparent;color-scheme:normal;z-index:2147483000;';

  function size() {
    if (!open) {
      frame.style.cssText += 'width:76px;height:76px;right:12px;bottom:12px;top:auto;left:auto;';
    } else if (window.innerWidth < 480) {
      frame.style.cssText += 'width:100%;height:100%;right:0;bottom:0;top:0;left:0;'; // phones: full screen
    } else {
      frame.style.cssText += 'width:' + Math.min(400, window.innerWidth - 24) + 'px;height:' + Math.min(680, window.innerHeight - 24) + 'px;right:12px;bottom:12px;top:auto;left:auto;';
    }
  }

  function post(message) {
    if (ready) frame.contentWindow.postMessage(message, origin);
    else pending.push(message);
  }

  window.addEventListener('message', function (event) {
    if (event.source !== frame.contentWindow || event.origin !== origin || !event.data) return;
    if (event.data.type === 'baton:ready') {
      ready = true;
      pending.splice(0).forEach(post);
    }
    if (event.data.type === 'baton:state') {
      open = Boolean(event.data.open);
      size();
    }
  });
  window.addEventListener('resize', size);

  var api = {
    loaded: true,
    identify: function (token) { post({ type: 'baton:identify', token: token }); },
    logout: function () { post({ type: 'baton:logout' }); },
    open: function () { post({ type: 'baton:open' }); },
    close: function () { post({ type: 'baton:close' }); },
  };
  window.Baton = api;
  queued.forEach(function (call) { if (api[call[0]]) api[call[0]].apply(null, call.slice(1)); });

  function mount() { document.body.appendChild(frame); }
  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
