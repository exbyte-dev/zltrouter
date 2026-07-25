/* The live signal view: status poll, pinned meter, walk test, readings.

   The poll runs on every tab, not just the Signal one. The meter it feeds is
   pinned above the tab bar and always visible, and the walk-test history has
   to stay continuous whether or not you happen to be looking at the graph. */

(function (zlt) {
  "use strict";
  const $ = zlt.$;
  const root = document.documentElement;

  /* --- signal quality ------------------------------------------------------- */
  const METRIC = {
    rsrp: { min:-125, max:-70, fair:-100, good:-90, excellent:-80 },
    rssi: { min:-100, max:-45, fair:-75,  good:-65, excellent:-55 },
  };
  function quality(kind, v){
    const m = METRIC[kind];
    if (v >= m.excellent) return ['excellent', 'var(--good)'];
    if (v >= m.good)      return ['good',      'var(--good)'];
    if (v >= m.fair)      return ['fair',      'var(--fair)'];
    return ['poor', 'var(--poor)'];
  }

  /* --- the meter collapses once you scroll ---------------------------------
     At full size the pinned block would hold a third of a phone screen
     hostage. Past the first few pixels of scroll it folds to a single line, so
     the reading stays on screen while an inbox scrolls underneath it. */
  const headbar = $('headbar');
  let compact = false;
  function onScroll(){
    const want = scrollY > 24;
    if (want === compact) return;
    compact = want;
    headbar.classList.toggle('compact', want);
  }
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* --- walk-test history ---------------------------------------------------- */
  const HIST_MS = 15*60*1000;
  const hist = [];
  function pushHist(rsrp, rssi){
    const now = Date.now();
    hist.push({t:now, rsrp, rssi});
    while (hist.length && now - hist[0].t > HIST_MS) hist.shift();
  }
  function drawSpark(){
    const svg = $('spark');
    if (hist.length < 2){ svg.innerHTML = ''; return; }
    const t0 = hist[0].t, span = Math.max(hist[hist.length-1].t - t0, 1);
    const y = v => 92 - (Math.min(Math.max(v,-120),-45) + 120) / 75 * 88;
    /* var() must go through style=, not a presentation attribute. */
    const line = (key, cssVar, w) => {
      const pts = hist.filter(h => h[key] != null)
        .map(h => `${((h.t-t0)/span*800).toFixed(1)},${y(h[key]).toFixed(1)}`);
      return pts.length > 1
        ? `<polyline points="${pts.join(' ')}" fill="none" style="stroke:${cssVar}"
            stroke-width="${w}" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>` : '';
    };
    svg.innerHTML = line('rssi','var(--trace)',1.2) + line('rsrp','var(--q)',1.8);
    $('sparkCaption').textContent = hist.some(h => h.rsrp != null)
      ? 'rsrp · rssi in grey · last 15 min' : 'rssi · last 15 min';
  }

  /* --- readings list -------------------------------------------------------- */
  const ROWS = [
    ['network_type','Network'], ['lte_band','Band'], ['signalbar','Bars (of 5)'],
    ['lte_snr','SNR (dB)'], ['lte_rsrq','RSRQ (dB)'], ['rssi','RSSI (dBm)'],
    ['lte_pci','Cell PCI'], ['ppp_status','Connection'],
  ];
  function drawReadings(d){
    $('readings').innerHTML = ROWS.map(([k,label]) =>
      `<div class="row"><span class="k">${label}</span><span class="v">${d[k] ?? ''}</span></div>`
    ).join('');
  }

  /* --- status polling ------------------------------------------------------- */
  let timer = null, paused = false, pollBusy = false;
  let pollFails = 0, everLoaded = false;
  const POLL_FAIL_THRESHOLD = 2;
  async function poll(){
    if (pollBusy) return;
    pollBusy = true;
    try {
      const s = await zlt.fetchJSON('/api/status');
      $('banner').classList.remove('show');
      pollFails = 0;
      const first = !everLoaded;
      everLoaded = true;
      $('host').textContent = s.host.replace(/^https?:\/\//,'');
      $('dot').className = 'dot ' + (s.authed ? 'on' : 'off');
      $('sessionWord').textContent = s.authed ? 'logged in' : 'open data';
      if (s.note){ $('note').textContent = s.note; $('note').classList.add('show'); }
      else $('note').classList.remove('show');

      const d = s.data;
      const num = x => (x !== '' && x != null && !isNaN(Number(x))) ? Number(x) : null;
      const rsrp = num(d.lte_rsrp), rssi = num(d.rssi);
      const kind = rsrp != null ? 'rsrp' : 'rssi';
      const val  = rsrp != null ? rsrp : rssi;
      const m = METRIC[kind];
      $('bigLabel').textContent = kind.toUpperCase();
      $('barMin').textContent = m.min; $('barMax').textContent = m.max;
      if (val != null){
        const [word, color] = quality(kind, val);
        root.style.setProperty('--q', color);
        $('bigVal').textContent = val;
        $('qualityWord').textContent = word;
        $('fill').style.width =
          ((Math.min(Math.max(val,m.min),m.max) - m.min) / (m.max - m.min) * 100) + '%';
      } else {
        root.style.setProperty('--q', 'var(--faint)');
        $('bigVal').textContent = '—';
        $('qualityWord').textContent = 'no reading';
        $('fill').style.width = '0%';
      }
      pushHist(rsrp, rssi);
      drawSpark();
      drawReadings(d);
      $('stamp').textContent = 'updated ' + new Date().toLocaleTimeString();

      /* One inbox read on the first good poll, only to put a number on the
         Messages tab. It is deliberately not repeated: an inbox read takes the
         same router lock this poll wants, and the device is slow enough that
         doing both on a timer makes the two fight. */
      if (first && zlt.sms) zlt.sms.ensureLoaded();
    } catch (e) {
      pollFails++;
      if (pollFails >= POLL_FAIL_THRESHOLD) {
        if (everLoaded) {
          $('banner').textContent = 'status: ' + e.message;
          $('banner').classList.add('show');
        } else {
          $('qualityWord').textContent = 'connection issue';
        }
      }
    } finally {
      pollBusy = false;
    }
  }
  function schedule(){
    clearInterval(timer);
    if (!paused) timer = setInterval(poll, Number($('interval').value));
  }
  $('interval').addEventListener('change', schedule);
  $('pause').addEventListener('click', () => {
    paused = !paused;
    $('pause').textContent = paused ? 'Resume' : 'Pause';
    schedule();
    if (!paused) poll();
  });

  drawReadings({});
  poll();
  schedule();
})(window.zlt);
