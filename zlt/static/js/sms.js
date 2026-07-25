/* Messages.

   Every row is built with createElement/textContent rather than innerHTML.
   The sender and body of an SMS arrive off the mobile network, which makes
   them the one thing on this page a stranger gets to write.

   The inbox is read when the tab is first opened, after a send, and on the
   explicit Refresh - never on the status poll. A read holds the same router
   lock the signal poll needs, and the device is slow enough that polling both
   would make the panel fight itself. */

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

  let busy = false;
  let loaded = false;

  function setBusy(state) {
    busy = state;
    zlt.setBusy(panel, state);
  }

  const say = (msg, isError) => zlt.say(statusEl, msg, isError);

  function setBadge(unread) {
    badgeEl.textContent = unread ? String(unread) : '';
    tabEl.setAttribute('aria-label', unread ? 'Messages, ' + unread + ' unread' : 'Messages');
  }

  function render(messages, unread) {
    listEl.innerHTML = '';
    emptyEl.hidden = messages.length > 0;
    setBadge(unread);
    for (const m of messages) {
      const row = document.createElement('div');
      row.className = m.unread ? 'sms-msg unread' : 'sms-msg';

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

      row.append(head, body);
      listEl.appendChild(row);
    }
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

  zlt.sms = { ensureLoaded };
  zlt.tabs.onFirstShow('messages', ensureLoaded);
})(window.zlt);
