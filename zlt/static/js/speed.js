/* Speed test.

   The transfer runs browser-to-target with no backend in the middle: proxying
   it through the dashboard would measure the serving machine's link instead of
   this one's, and push every byte over the 4G link twice. The backend only
   says where to aim (/api/speedtest/config).

   Both directions are time-boxed rather than fixed-size, because the same
   payload that takes 2s on a good LTE cell takes minutes on a bad one. The
   download streams and stops reading at the cap; the upload cannot be measured
   mid-flight, so it sizes the real run from a small probe. */

(function (zlt) {
  "use strict";
  const $ = zlt.$;
  const runBtn = $('speed-run');
  const statusEl = $('speed-status');
  const resultsEl = $('speed-results');
  const captionEl = $('speed-caption');

  const ROWS = [['down', 'Download (Mbps)'], ['up', 'Upload (Mbps)'], ['ping', 'Ping (ms)']];
  const TARGET_SECONDS = 5;      // aim each phase at roughly this long
  const DOWN_CAP_SECONDS = 8;    // hard stop for the download stream
  const UP_PROBE_BYTES = 512 * 1024;
  const PING_SAMPLES = 4;

  const result = { down: null, up: null, ping: null };
  const mbps = (bytes, seconds) => seconds > 0 ? bytes * 8 / seconds / 1e6 : 0;
  const round1 = n => Math.round(n * 10) / 10;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const sized = (url, bytes) =>
    url + (url.includes('?') ? '&' : '?') + 'bytes=' + bytes;

  function render(liveKey, liveValue) {
    resultsEl.innerHTML = ROWS.map(([k, label]) => {
      const live = k === liveKey && liveValue != null;
      const v = live ? liveValue : result[k];
      return `<div class="row"><span class="k">${label}</span>` +
             `<span class="${live ? 'v live' : 'v'}">${v == null ? '' : v}</span></div>`;
    }).join('');
  }

  const say = (msg, isError) => zlt.say(statusEl, msg, isError);

  let cfg = null;
  async function config() {
    if (cfg) return cfg;
    const r = await fetch('/api/speedtest/config');
    if (!r.ok) throw new Error('speed test unavailable (' + r.status + ')');
    cfg = await r.json();
    return cfg;
  }

  async function measurePing(c) {
    const url = sized(c.down_url, 0);
    const samples = [];
    for (let i = 0; i < PING_SAMPLES; i++) {
      const started = performance.now();
      const resp = await fetch(url, { cache: 'no-store' });
      if (!resp.ok) throw new Error('ping failed (' + resp.status + ')');
      await resp.arrayBuffer();
      samples.push(performance.now() - started);
    }
    /* Best of N: the floor is the honest round trip, the rest is jitter. */
    return Math.round(Math.min.apply(null, samples));
  }

  async function measureDown(c) {
    const started = performance.now();
    const resp = await fetch(sized(c.down_url, c.down_bytes), { cache: 'no-store' });
    if (!resp.ok) throw new Error('download failed (' + resp.status + ')');
    const elapsed = () => (performance.now() - started) / 1000;

    if (!resp.body || !resp.body.getReader) {
      const buf = await resp.arrayBuffer();       /* no streaming: time the lot */
      return round1(mbps(buf.byteLength, elapsed()));
    }
    const reader = resp.body.getReader();
    let got = 0, painted = 0;
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      got += chunk.value.length;
      const now = performance.now();
      if (elapsed() >= DOWN_CAP_SECONDS) {
        reader.cancel().catch(() => {});          /* enough to measure with */
        break;
      }
      if (now - painted > 200) {                  /* keep the number moving */
        painted = now;
        render('down', round1(mbps(got, elapsed())));
      }
    }
    return round1(mbps(got, elapsed()));
  }

  async function postBytes(url, bytes) {
    const started = performance.now();
    const resp = await fetch(url, {
      method: 'POST', body: new Uint8Array(bytes), cache: 'no-store',
    });
    if (!resp.ok) throw new Error('upload failed (' + resp.status + ')');
    await resp.arrayBuffer();
    const seconds = (performance.now() - started) / 1000;
    return { bytes, seconds, rate: seconds > 0 ? bytes / seconds : 0 };
  }

  async function measureUp(c) {
    const floor = Math.min(UP_PROBE_BYTES, c.up_bytes);
    const probe = await postBytes(c.up_url, floor);
    const size = clamp(Math.round(probe.rate * TARGET_SECONDS), floor, c.up_bytes);
    const run = await postBytes(c.up_url, size);
    return round1(mbps(run.bytes, run.seconds));
  }

  let running = false;
  runBtn.addEventListener('click', async () => {
    if (running) return;
    running = true;
    runBtn.disabled = true;
    result.down = result.up = result.ping = null;
    render();
    try {
      const c = await config();
      say('measuring latency…');
      result.ping = await measurePing(c);
      render();
      say('downloading…');
      result.down = await measureDown(c);
      render();
      say('uploading…');
      result.up = await measureUp(c);
      render();
      say('');
      captionEl.textContent = new Date().toLocaleTimeString();
    } catch (e) {
      say(e.message || String(e), true);
    } finally {
      running = false;
      runBtn.disabled = false;
    }
  });

  render();
})(window.zlt);
