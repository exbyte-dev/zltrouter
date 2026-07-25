/* Messages.

   Every row is built with createElement/textContent rather than innerHTML.
   The sender and body of an SMS arrive off the mobile network, which makes
   them the one thing on this page a stranger gets to write.

   The inbox is read when the tab is first opened, after a send, after a
   mark-read or delete, and on the explicit Refresh - never on the status poll.
   A read holds the same router lock the signal poll needs, and the device is
   slow enough that polling both would make the panel fight itself.

   Select mode follows the USSD panel's Manage toggle for the same reason it
   does: until you opt in, no destructive control sits next to something you
   meant to read. */

(function (zlt) {
  "use strict";
  const $ = zlt.$;
  const panel = $('sms-panel');
  const listEl = $('sms-list');
  const emptyEl = $('sms-empty');
  const badgeEl = $('sms-badge');
  const tabEl = $('tab-messages');
  const statusEl = $('sms-status');
  const form = $('sms-compose');
  const numberInput = $('sms-number');
  const textInput = $('sms-text');
  const refreshBtn = $('sms-refresh');
  const selectBtn = $('sms-select');
  const allBtn = $('sms-all');
  const bar = $('sms-bar');
  const countEl = $('sms-count');
  const barActions = $('sms-bar-actions');
  const barConfirm = $('sms-bar-confirm');

  let busy = false;
  let loaded = false;
  let selecting = false;
  let confirming = false;
  let messages = [];
  let unreadCount = 0;
  const picked = new Set();

  function setBusy(state) {
    busy = state;
    zlt.setBusy(panel, state);
  }

  const say = (msg, isError) => zlt.say(statusEl, msg, isError);

  function setBadge(unread) {
    badgeEl.textContent = unread ? String(unread) : '';
    tabEl.setAttribute('aria-label', unread ? 'Messages, ' + unread + ' unread' : 'Messages');
  }

  /* Chrome: the action bar, the Select/Done and Select all links, and the
     compose form, which hides in select mode to give the bar its room. */
  function renderChrome() {
    selectBtn.textContent = selecting ? 'Done' : 'Select';
    allBtn.hidden = !selecting;
    form.hidden = selecting;
    bar.hidden = !selecting || picked.size === 0;
    barActions.hidden = confirming;
    barConfirm.hidden = !confirming;
    countEl.textContent = confirming
      ? 'Delete ' + picked.size + ' permanently?'
      : picked.size + ' selected';
    const everyOne = messages.length > 0 && picked.size === messages.length;
    allBtn.textContent = everyOne ? 'Select none' : 'Select all';
  }

  function pick(id, on) {
    if (on) picked.add(id); else picked.delete(id);
    confirming = false;
    renderChrome();
    for (const row of listEl.children) {
      row.classList.toggle('selected', picked.has(row.dataset.id));
    }
  }

  function render(list, unread) {
    messages = list;
    unreadCount = unread;
    listEl.innerHTML = '';
    emptyEl.hidden = list.length > 0;
    setBadge(unread);
    for (const m of list) {
      const row = document.createElement('div');
      row.className = m.unread ? 'sms-msg unread' : 'sms-msg';
      row.dataset.id = m.id;
      if (picked.has(m.id)) row.classList.add('selected');

      const head = document.createElement('div');
      head.className = 'sms-head';
      if (m.unread) {
        const dot = document.createElement('span');
        dot.className = 'sms-dot';
        head.appendChild(dot);
      }
      const from = document.createElement('span');
      from.className = 'sms-from';
      from.textContent = m.outgoing ? 'to ' + m.number : m.number;
      const when = document.createElement('span');
      when.className = 'sms-when';
      when.textContent = m.date;
      head.append(from, when);

      const body = document.createElement('div');
      body.className = 'sms-body';
      body.textContent = m.text;

      if (!selecting) {
        row.append(head, body);
      } else {
        const wrap = document.createElement('label');
        wrap.className = 'sms-pick';
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.className = 'sms-check';
        box.checked = picked.has(m.id);
        box.setAttribute('aria-label', 'Select message from ' + m.number);
        box.addEventListener('change', () => pick(m.id, box.checked));
        const inner = document.createElement('div');
        inner.className = 'sms-pick-body';
        inner.append(head, body);
        wrap.append(box, inner);
        row.appendChild(wrap);
      }
      listEl.appendChild(row);
    }
    renderChrome();
  }

  async function load() {
    if (busy) return;
    setBusy(true);
    try {
      const data = await zlt.fetchJSON('/api/sms');
      render(data.messages, data.unread);
      loaded = true;
      say('');
    } catch (e) {
      say('inbox: ' + (e.message || e), true);
    } finally {
      setBusy(false);
    }
  }

  /* Called from two places: the Messages tab opening for the first time, and
     once from signal.js after the first good poll purely to put a number on
     the tab. Whichever arrives first does the read and the other is a no-op,
     so landing straight on #messages still costs one inbox read, not two. A
     failed read leaves 'loaded' false so the next caller retries. */
  function ensureLoaded() {
    if (loaded || busy) return;
    load();
  }

  /* Both actions end the same way: drop the selection, leave select mode, and
     re-read the inbox, which is also what refreshes the tab badge. */
  async function act(url, verb) {
    if (busy || picked.size === 0) return;
    const ids = Array.from(picked);
    setBusy(true);
    say(verb + '…');
    try {
      const data = await zlt.postJSON(url, { ids: ids });
      picked.clear();
      confirming = false;
      selecting = false;
      say(verb === 'deleting' ? 'deleted ' + data.count : 'marked ' + data.count + ' read');
    } catch (e) {
      say(verb + ' failed: ' + (e.message || e), true);
    } finally {
      setBusy(false);
    }
    load();
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (busy) return;
    const number = numberInput.value.trim();
    const text = textInput.value.trim();
    if (!number || !text) {
      say('A number and a message are both required.', true);
      return;
    }
    setBusy(true);
    say('sending…');
    try {
      await zlt.postJSON('/api/sms/send', { number: number, text: text });
      textInput.value = '';
      say('sent');
    } catch (e) {
      say('send failed: ' + (e.message || e), true);
    } finally {
      setBusy(false);
    }
    load();
  });

  refreshBtn.addEventListener('click', load);

  selectBtn.addEventListener('click', () => {
    selecting = !selecting;
    picked.clear();
    confirming = false;
    say('');
    render(messages, unreadCount);
  });

  allBtn.addEventListener('click', () => {
    const everyOne = picked.size === messages.length;
    picked.clear();
    if (!everyOne) for (const m of messages) picked.add(m.id);
    confirming = false;
    render(messages, unreadCount);
  });

  $('sms-mark').addEventListener('click', () => act('/api/sms/read', 'marking'));
  $('sms-delete').addEventListener('click', () => { confirming = true; renderChrome(); });
  $('sms-delete-no').addEventListener('click', () => { confirming = false; renderChrome(); });
  $('sms-delete-yes').addEventListener('click', () => act('/api/sms/delete', 'deleting'));

  zlt.sms = { ensureLoaded };
  zlt.tabs.onFirstShow('messages', ensureLoaded);
})(window.zlt);
