/* USSD: send a code, answer an interactive menu, manage saved codes. */

(function (zlt) {
  "use strict";
  const $ = zlt.$;
  const panel = $('ussd-panel');
  const out = $('ussd-out');
  const sendForm = $('ussd-form');
  const codeInput = $('ussd-code');
  const replyForm = $('ussd-reply-form');
  const replyInput = $('ussd-reply');
  const spinner = $('ussd-spinner');
  const savedBox = $('ussd-saved');
  const manageBtn = $('ussd-manage');
  const manageCard = $('ussd-manage-card');
  const manageList = $('ussd-manage-list');
  const saveForm = $('ussd-save-form');
  const saveLabel = $('ussd-save-label');
  const saveCode = $('ussd-save-code');
  const manageMsg = $('ussd-manage-msg');

  let busy = false;
  const setBusy = state => zlt.setBusy(panel, state);

  /* show() is contracted for the {text, state} shape that send/reply return.
     The cancel endpoint returns {ok: true} instead, so cancel must never be
     routed through here - see the dedicated onCancelled() handler below. */
  function show(result) {
    out.hidden = false;
    out.classList.toggle('error', result.state === 'error' || result.state === 'timeout');
    out.textContent = result.state === 'timeout'
      ? '(no response from network)'
      : (result.state === 'error' ? 'USSD error: ' + result.text : result.text);
    replyForm.hidden = result.state !== 'prompt';
  }

  function onCancelled() {
    out.hidden = false;
    out.classList.remove('error');
    out.textContent = 'cancelled';
    replyForm.hidden = true;
  }

  /* onResult, when given, replaces the default show() handling of a
     successful response - used by cancel, whose {ok} payload does not match
     show()'s {text, state} contract. Failures still go through show(), since
     {state: 'error', text} always matches that contract. */
  async function call(url, payload, onResult) {
    if (busy) return;
    busy = true;
    setBusy(true);
    spinner.hidden = false;
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload ? JSON.stringify(payload) : undefined,
      });
      if (!r.ok) { show({ state: 'error', text: 'request failed (' + r.status + ')' }); return; }
      const data = await r.json();
      (onResult || show)(data);
    } catch (e) {
      show({ state: 'error', text: String(e) });
    } finally {
      spinner.hidden = true;
      setBusy(false);
      busy = false;
    }
  }

  /* Saved-code management is deliberately kept off the call()/show() path:
     these endpoints return {codes}, not the {text, state} shape show() is
     contracted for, and a failure to save should not overwrite a USSD reply. */
  let saved = [];
  let managing = false;

  function note(msg) {
    manageMsg.hidden = !msg;
    manageMsg.textContent = msg || '';
  }

  function renderSaved() {
    savedBox.innerHTML = '';
    manageList.innerHTML = '';
    if (!managing) {
      for (const c of saved) {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = c.label;
        b.title = c.code;
        b.onclick = () => call('/api/ussd/send', { code: c.code });
        savedBox.appendChild(b);
      }
      return;
    }
    for (const c of saved) {
      const row = document.createElement('div');
      row.className = 'ussd-manage-row';
      const meta = document.createElement('span');
      meta.className = 'ussd-manage-meta';
      const lbl = document.createElement('span');
      lbl.className = 'lbl';
      lbl.textContent = c.label;
      const code = document.createElement('span');
      code.className = 'code';
      code.textContent = c.code;
      meta.append(lbl, code);
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'ussd-x';
      x.textContent = '×';
      x.setAttribute('aria-label', 'Remove ' + c.label);
      x.onclick = () => store('DELETE', { label: c.label });
      row.append(meta, x);
      manageList.appendChild(row);
    }
  }

  async function store(method, body) {
    if (busy) return;
    busy = true;
    setBusy(true);
    try {
      const r = await fetch('/api/ussd/codes', {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        note(detail.detail || 'could not save (' + r.status + ')');
        return;
      }
      saved = (await r.json()).codes;
      note('');
      renderSaved();
    } catch (e) {
      note(String(e));
    } finally {
      setBusy(false);
      busy = false;
    }
  }

  async function loadSaved() {
    try {
      saved = (await zlt.fetchJSON('/api/ussd/codes')).codes;
    } catch (e) {
      saved = [];
    }
    renderSaved();
  }

  sendForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const code = codeInput.value.trim();
    if (code) call('/api/ussd/send', { code });
  });
  replyForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = replyInput.value.trim();
    if (!text) return;
    call('/api/ussd/reply', { text });
    replyInput.value = '';
  });
  $('ussd-cancel').addEventListener('click', () => {
    replyForm.hidden = true;
    call('/api/ussd/cancel', null, onCancelled).then(loadSaved);
  });

  /* Manage mode keeps the default row clean: saved codes are plain one-click
     send buttons until you opt in, so a remove control is never sitting next
     to a button you meant to press. */
  manageBtn.addEventListener('click', () => {
    managing = !managing;
    manageBtn.textContent = managing ? 'Done' : 'Manage';
    manageCard.hidden = !managing;
    note('');
    if (managing && !saveCode.value) saveCode.value = codeInput.value.trim();
    renderSaved();
    if (managing) saveLabel.focus();
  });

  saveForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const label = saveLabel.value.trim();
    const code = saveCode.value.trim();
    if (!label || !code) { note('Both a label and a code are required.'); return; }
    store('POST', { label, code }).then(() => {
      if (!manageMsg.textContent) { saveLabel.value = ''; saveCode.value = ''; saveLabel.focus(); }
    });
  });

  zlt.tabs.onFirstShow('ussd', loadSaved);
})(window.zlt);
