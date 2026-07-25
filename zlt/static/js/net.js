/* Network mode switcher: the same SET_BEARER_PREFERENCE write as 'zlt net set',
   re-read after each change so the buttons show what the router actually did
   rather than what was asked for. */

(function (zlt) {
  "use strict";
  const $ = zlt.$;
  const hint = $('modehint');

  let modeBusy = false;
  const segButtons = () => document.querySelectorAll('#seg button');

  function markMode(friendly){
    segButtons().forEach(b => b.classList.toggle('active', b.dataset.mode === friendly));
  }

  async function loadMode(){
    try {
      const j = await zlt.fetchJSON('/api/net');
      markMode(j.friendly);
      hint.textContent = j.configured ? `router reports ${j.configured}` : '';
    } catch (e) {
      hint.textContent = 'mode: ' + e.message;
    }
  }

  segButtons().forEach(btn => {
    btn.addEventListener('click', async () => {
      if (modeBusy) return;
      modeBusy = true;
      segButtons().forEach(b => b.disabled = true);
      hint.textContent = 'setting ' + btn.textContent + '…';
      try {
        const j = await zlt.postJSON('/api/net', { mode: btn.dataset.mode });
        markMode(j.friendly);
        hint.textContent = `set — router reports ${j.configured || 'unknown'}`;
      } catch (e) {
        hint.textContent = 'set failed: ' + e.message;
        loadMode();
      } finally {
        modeBusy = false;
        segButtons().forEach(b => b.disabled = false);
      }
    });
  });

  loadMode();
})(window.zlt);
