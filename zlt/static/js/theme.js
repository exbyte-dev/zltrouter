/* Theme toggle.

   The other half of this lives inline in index.html's <head>: that one runs
   before first paint so the page never flashes the wrong background, which is
   the one thing an external file cannot do. This half only wires the button. */

(function (zlt) {
  "use strict";
  const root = document.documentElement;
  const btn = zlt.$('theme');

  function applyTheme(t) {
    root.dataset.theme = t;
    btn.setAttribute('aria-label',
      t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
  }

  applyTheme(root.dataset.theme);

  btn.addEventListener('click', () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('zlt-theme', next); } catch (e) {}
  });

  /* Keep following the OS until an explicit choice has been made. */
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    let saved = null;
    try { saved = localStorage.getItem('zlt-theme'); } catch (err) {}
    if (!saved) applyTheme(e.matches ? 'dark' : 'light');
  });
})(window.zlt);
