/* Tab bar.

   The signal meter is pinned above this, so switching tabs never interrupts
   the poll - only the area below the meter changes. State lives in the URL
   hash rather than a variable, which makes a tab linkable and makes the back
   button do the obvious thing for free.

   Panels are found through each tab's aria-controls, so the panel ids stay the
   ones the rest of the app and its tests already use. */

(function (zlt) {
  "use strict";

  const TABS = ['signal', 'messages', 'ussd', 'speed'];
  const tabEl = id => zlt.$('tab-' + id);
  const panelEl = id => zlt.$(tabEl(id).getAttribute('aria-controls'));

  const pending = {};   // id -> [fn], first-show callbacks not yet fired
  const shown = {};     // id -> true once the panel has been revealed

  function reveal(id) {
    if (shown[id]) return;
    shown[id] = true;
    const fns = pending[id] || [];
    delete pending[id];
    fns.forEach(fn => fn());
  }

  function show(id, moveFocus) {
    if (TABS.indexOf(id) === -1) id = TABS[0];
    for (const t of TABS) {
      const on = t === id;
      tabEl(t).setAttribute('aria-selected', on ? 'true' : 'false');
      tabEl(t).tabIndex = on ? 0 : -1;
      panelEl(t).hidden = !on;
    }
    if (moveFocus) tabEl(id).focus();
    reveal(id);
  }

  /* Deferring a panel's opening request until someone looks at it is the whole
     reason this registry exists: three of the four panels talk to a slow
     router, and only one of them is on screen. Registering for a panel that is
     already visible fires immediately, so load order cannot race the hash. */
  zlt.tabs = {
    onFirstShow(id, fn) {
      if (shown[id]) { fn(); return; }
      (pending[id] = pending[id] || []).push(fn);
    },
    show(id) { location.hash = id; },
  };

  TABS.forEach((id, i) => {
    const el = tabEl(id);
    el.addEventListener('click', () => { location.hash = id; });
    el.addEventListener('keydown', e => {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      const next = TABS[(i + step + TABS.length) % TABS.length];
      location.hash = next;
      show(next, true);
    });
  });

  const fromHash = () => (location.hash || '').replace(/^#/, '');
  addEventListener('hashchange', () => show(fromHash()));
  show(fromHash());
})(window.zlt);
