/* Helpers every panel needs.

   Each panel used to carry its own copy of these three. They are identical
   because the API is: FastAPI reports every failure as a non-2xx with a
   {detail} body, and every panel disables its own buttons while a router call
   is in flight. */

window.zlt = window.zlt || {};

(function (zlt) {
  "use strict";

  zlt.$ = id => document.getElementById(id);

  zlt.fetchJSON = async function (url, opts) {
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || 'HTTP ' + r.status);
    return data;
  };

  zlt.postJSON = function (url, body) {
    return zlt.fetchJSON(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  };

  zlt.setBusy = function (panel, state) {
    panel.querySelectorAll('button').forEach(b => { b.disabled = state; });
  };

  zlt.say = function (el, msg, isError) {
    el.textContent = msg || '';
    el.classList.toggle('error', !!isError);
  };
})(window.zlt);
