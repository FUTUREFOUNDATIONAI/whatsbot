/**
 * On-demand Tailwind runtime for plugin screens.
 *
 * The core UI ships prebuilt CSS (web/static/css/tailwind.css). Plugins are
 * installed after that file was generated and may use any utility class, so a
 * plugin screen loads the in-browser Tailwind compiler the first time one is
 * opened. It is a no-op for every other page, which keeps the runtime's DOM
 * observers (the main cost of opening a conversation) off the chat.
 */

let _loading = null;

export function ensureTailwindRuntime() {
  if (window.tailwind && window.__wbTailwindReady) return Promise.resolve();
  if (_loading) return _loading;
  _loading = (async () => {
    const [themeRes] = await Promise.all([
      fetch('/static/tailwind-theme.json', { cache: 'no-cache' }).then(r => r.json()),
      new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = '/static/vendor/tailwind.js';
        s.onload = resolve;
        s.onerror = () => reject(new Error('Falha ao carregar o Tailwind dos plugins'));
        document.head.appendChild(s);
      }),
    ]);
    // Assigning the config makes the runtime (re)generate its stylesheet.
    window.tailwind.config = themeRes;
    window.__wbTailwindReady = true;
  })().catch((e) => { _loading = null; throw e; });
  return _loading;
}
