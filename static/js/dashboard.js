(() => {
  const root = document.getElementById('monitor-root');
  if (!root) return;

  const apiUrl = root.dataset.apiUrl;
  const streamUrl = root.dataset.streamUrl;
  const fallbackInterval = Number(root.dataset.pollInterval || 2000);
  const MAX_HISTORY = 180;
  const MAX_ECG_SAMPLES = 700;

  let history = [];
  let ecgSamples = [];
  let eventSource = null;
  let fallbackTimer = null;
  let reconnectTimer = null;
  let lastSuccess = 0;

  const valueFields = ['bpm', 'temperature', 'ecg', 'sensor_timestamp'];

  function asFiniteNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function cleanNumber(value, decimals = 0) {
    const number = asFiniteNumber(value);
    if (number === null) return '—';
    if (Number.isInteger(number)) return String(number);
    return number.toFixed(decimals).replace(/\.0+$/, '');
  }

  function setText(selector, value) {
    document.querySelectorAll(selector).forEach(el => { el.textContent = value; });
  }

  function setConnection(type, title, detail) {
    const el = document.getElementById('connection-state');
    if (!el) return;
    el.className = `live-state ${type}`;
    const strong = el.querySelector('strong');
    const small = el.querySelector('small');
    if (strong) strong.textContent = title;
    if (small) small.textContent = detail;
  }

  function updateStatus(field, status) {
    const el = document.querySelector(`[data-status="${field}"]`);
    if (!el) return;
    const level = status?.level || 'unknown';
    const label = status?.label || 'No signal';
    el.className = `status-pill status-${level}`;
    el.innerHTML = `<i></i>${label}`;
  }

  function appendReading(reading) {
    const point = {
      bpm: asFiniteNumber(reading.bpm),
      temperature: asFiniteNumber(reading.temperature),
      ecg: asFiniteNumber(reading.ecg),
      sensor_timestamp: asFiniteNumber(reading.sensor_timestamp),
      recorded_at: reading.received_at || new Date().toISOString(),
    };
    const previous = history[history.length - 1];
    const samePacket = previous && valueFields.every(key => previous[key] === point[key]);
    if (!samePacket) history.push(point);
    if (history.length > MAX_HISTORY) history = history.slice(-MAX_HISTORY);
  }

  // The ECG strip is intentionally separate from the stored history.
  // It uses only unique live ECG packets received from Firebase and never
  // inserts a synthetic heartbeat or interpolated sample.
  function appendRealEcgSample(reading) {
    const value = asFiniteNumber(reading.ecg);
    if (value === null) return false;

    const sensorTimestamp = asFiniteNumber(reading.sensor_timestamp);
    const receivedAt = Date.parse(reading.received_at || '') || Date.now();
    const previous = ecgSamples[ecgSamples.length - 1];

    if (previous) {
      // When the sensor supplies Timestamp, treat it as the sample identity.
      // This prevents BPM/Temperature-only Firebase updates from duplicating ECG points.
      if (sensorTimestamp !== null && previous.sensorTimestamp !== null) {
        if (sensorTimestamp === previous.sensorTimestamp) return false;
      } else if (value === previous.value && receivedAt - previous.receivedAt < 250) {
        return false;
      }
    }

    ecgSamples.push({
      value,
      sensorTimestamp,
      receivedAt,
    });
    if (ecgSamples.length > MAX_ECG_SAMPLES) {
      ecgSamples = ecgSamples.slice(-MAX_ECG_SAMPLES);
    }
    return true;
  }

  function canvasSize(canvas) {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    return {width, height, dpr};
  }

  function drawLine(canvas, values, {stroke = '#54e39b', fill = null, thick = 2} = {}) {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const {width, height, dpr} = canvasSize(canvas);
    ctx.clearRect(0, 0, width, height);

    const nums = values.filter(v => Number.isFinite(v));
    if (!nums.length) return;
    let min = Math.min(...nums);
    let max = Math.max(...nums);
    if (min === max) { min -= 1; max += 1; }
    const padding = Math.max(5 * dpr, height * 0.12);
    const usableH = Math.max(1, height - padding * 2);
    const xStep = values.length > 1 ? width / (values.length - 1) : width;

    const coords = [];
    values.forEach((value, index) => {
      if (!Number.isFinite(value)) return;
      const x = index * xStep;
      const normalized = (value - min) / (max - min);
      const y = height - padding - normalized * usableH;
      coords.push([x, y]);
    });
    if (!coords.length) return;

    if (fill) {
      const gradient = ctx.createLinearGradient(0, 0, 0, height);
      gradient.addColorStop(0, fill);
      gradient.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.beginPath();
      coords.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
      ctx.lineTo(coords[coords.length - 1][0], height);
      ctx.lineTo(coords[0][0], height);
      ctx.closePath();
      ctx.fillStyle = gradient;
      ctx.fill();
    }

    ctx.beginPath();
    coords.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.strokeStyle = stroke;
    ctx.lineWidth = thick * dpr;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.shadowBlur = 10 * dpr;
    ctx.shadowColor = stroke;
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  function percentile(sorted, p) {
    if (!sorted.length) return 0;
    const index = (sorted.length - 1) * p;
    const lower = Math.floor(index);
    const upper = Math.ceil(index);
    if (lower === upper) return sorted[lower];
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
  }

  function ecgDisplayRange(samples) {
    const values = samples.map(sample => sample.value).filter(Number.isFinite).sort((a, b) => a - b);
    if (!values.length) return {min: 0, max: 1, center: 0.5};

    // Robust range stops one electrical spike from flattening the entire live strip.
    // No sample values are modified. This affects only the vertical viewport.
    let low = values.length >= 20 ? percentile(values, 0.02) : values[0];
    let high = values.length >= 20 ? percentile(values, 0.98) : values[values.length - 1];
    let span = high - low;
    if (!Number.isFinite(span) || span < 1) {
      const center = (high + low) / 2 || values[values.length - 1] || 0;
      span = Math.max(10, Math.abs(center) * 0.02, 1);
      low = center - span / 2;
      high = center + span / 2;
    }
    const padding = span * 0.18;
    return {
      min: low - padding,
      max: high + padding,
      center: (low + high) / 2,
    };
  }

  function ecgXPositions(samples, width) {
    if (samples.length < 2) return samples.map(() => width * 0.5);

    const timestamps = samples.map(sample => sample.sensorTimestamp);
    const validSensorTime = timestamps.every(Number.isFinite);
    if (validSensorTime) {
      let strictlyIncreasing = true;
      for (let i = 1; i < timestamps.length; i += 1) {
        if (timestamps[i] <= timestamps[i - 1]) {
          strictlyIncreasing = false;
          break;
        }
      }
      if (strictlyIncreasing) {
        const minT = timestamps[0];
        const maxT = timestamps[timestamps.length - 1];
        const span = maxT - minT;
        if (span > 0) return timestamps.map(value => ((value - minT) / span) * width);
      }
    }

    const first = samples[0].receivedAt;
    const last = samples[samples.length - 1].receivedAt;
    const receiveSpan = last - first;
    if (receiveSpan > 0) {
      return samples.map(sample => ((sample.receivedAt - first) / receiveSpan) * width);
    }

    return samples.map((_, index) => (index / Math.max(1, samples.length - 1)) * width);
  }

  function setEcgScaleLabels(range) {
    const max = document.getElementById('ecg-axis-max');
    const mid = document.getElementById('ecg-axis-mid');
    const min = document.getElementById('ecg-axis-min');
    if (max) max.textContent = cleanNumber(range.max, 1);
    if (mid) mid.textContent = cleanNumber(range.center, 1);
    if (min) min.textContent = cleanNumber(range.min, 1);
  }

  function updateEcgRate() {
    const rateEl = document.getElementById('ecg-stream-rate');
    const countEl = document.getElementById('ecg-samples');
    if (countEl) countEl.textContent = `${ecgSamples.length} live samples`;
    if (!rateEl) return;

    if (ecgSamples.length < 2) {
      rateEl.textContent = 'Waiting for samples';
      return;
    }

    const recent = ecgSamples.slice(-Math.min(80, ecgSamples.length));
    const seconds = (recent[recent.length - 1].receivedAt - recent[0].receivedAt) / 1000;
    if (seconds <= 0) {
      rateEl.textContent = 'Live stream';
      return;
    }
    const rate = (recent.length - 1) / seconds;
    rateEl.textContent = `${rate.toFixed(rate >= 10 ? 0 : 1)} updates/s`;
  }

  function drawRealEcg(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const {width, height, dpr} = canvasSize(canvas);
    ctx.clearRect(0, 0, width, height);

    const samples = ecgSamples.filter(sample => Number.isFinite(sample.value));
    const range = ecgDisplayRange(samples);
    setEcgScaleLabels(range);
    updateEcgRate();

    if (!samples.length) {
      ctx.fillStyle = 'rgba(122, 164, 184, .55)';
      ctx.font = `${11 * dpr}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
      ctx.fillText('WAITING FOR LIVE /patient/ECG SAMPLES', 22 * dpr, height / 2);
      return;
    }

    const leftPad = 0;
    const rightPad = 0;
    const topPad = 24 * dpr;
    const bottomPad = 24 * dpr;
    const plotW = width - leftPad - rightPad;
    const plotH = Math.max(1, height - topPad - bottomPad);
    const xPositions = ecgXPositions(samples, plotW).map(x => x + leftPad);

    const valueToY = value => {
      const normalized = (value - range.min) / Math.max(0.000001, range.max - range.min);
      return height - bottomPad - normalized * plotH;
    };

    // Subtle center guide for orientation. It is not a generated ECG baseline.
    const centerY = valueToY(range.center);
    ctx.beginPath();
    ctx.moveTo(0, centerY);
    ctx.lineTo(width, centerY);
    ctx.strokeStyle = 'rgba(89, 239, 170, .09)';
    ctx.lineWidth = 1 * dpr;
    ctx.setLineDash([4 * dpr, 6 * dpr]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw straight segments through the real samples only. No Bezier smoothing,
    // no inserted points and no artificial QRS complexes.
    ctx.beginPath();
    samples.forEach((sample, index) => {
      const x = xPositions[index];
      const y = valueToY(sample.value);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = '#63f3ae';
    ctx.lineWidth = 2 * dpr;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.shadowBlur = 10 * dpr;
    ctx.shadowColor = 'rgba(99,243,174,.6)';
    ctx.stroke();
    ctx.shadowBlur = 0;

    const lastIndex = samples.length - 1;
    const lastX = xPositions[lastIndex];
    const lastY = valueToY(samples[lastIndex].value);

    // A sweep marker follows the newest real sample.
    const sweep = ctx.createLinearGradient(Math.max(0, lastX - 38 * dpr), 0, lastX + 2 * dpr, 0);
    sweep.addColorStop(0, 'rgba(99,243,174,0)');
    sweep.addColorStop(1, 'rgba(99,243,174,.18)');
    ctx.fillStyle = sweep;
    ctx.fillRect(Math.max(0, lastX - 38 * dpr), 0, 40 * dpr, height);

    ctx.beginPath();
    ctx.moveTo(lastX, 0);
    ctx.lineTo(lastX, height);
    ctx.strokeStyle = 'rgba(99,243,174,.22)';
    ctx.lineWidth = 1 * dpr;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(lastX, lastY, 3.2 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = '#b9ffda';
    ctx.shadowBlur = 14 * dpr;
    ctx.shadowColor = '#63f3ae';
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  function redrawCharts() {
    drawLine(document.querySelector('[data-chart="bpm"]'), history.map(x => x.bpm), {
      stroke: '#ff738c', fill: 'rgba(255,93,122,.14)', thick: 1.5
    });
    drawLine(document.querySelector('[data-chart="temperature"]'), history.map(x => x.temperature), {
      stroke: '#ffc45c', fill: 'rgba(255,196,92,.12)', thick: 1.5
    });
    drawLine(document.querySelector('[data-chart="ecg"]'), ecgSamples.map(x => x.value), {
      stroke: '#54e39b', fill: 'rgba(84,227,155,.12)', thick: 1.5
    });
    drawRealEcg(document.getElementById('ecg-chart'));
  }

  function updateDashboard(data) {
    const reading = data.reading || {};
    setText('[data-value="bpm"]', cleanNumber(reading.bpm, 1));
    setText('[data-value="temperature"]', cleanNumber(reading.temperature, 2));
    setText('[data-value="ecg"]', cleanNumber(reading.ecg, 3));
    setText('[data-value="ecg-large"]', cleanNumber(reading.ecg, 3));
    setText('[data-value="sensor_timestamp"]', cleanNumber(reading.sensor_timestamp, 3));

    valueFields.forEach(field => {
      setText(`[data-contract-value="${field}"]`, cleanNumber(reading[field], field === 'ecg' ? 3 : 2));
      updateStatus(field, data.status?.[field]);
    });

    appendReading(reading);
    appendRealEcgSample(reading);
    redrawCharts();

    const receivedAt = new Date(reading.received_at || Date.now());
    const receivedText = Number.isNaN(receivedAt.valueOf()) ? '—' : receivedAt.toLocaleTimeString();
    const lastPacket = document.getElementById('last-packet');
    const lastPacketMini = document.getElementById('last-packet-mini');
    const dataSource = document.getElementById('data-source');
    const sampleCount = document.getElementById('sample-count');
    const sensorClock = document.getElementById('sensor-clock');
    const signalIntegrity = document.getElementById('signal-integrity');

    if (lastPacket) lastPacket.textContent = receivedText;
    if (lastPacketMini) lastPacketMini.textContent = receivedText;
    if (dataSource) dataSource.textContent = reading.source?.includes('realtime') ? 'Firebase realtime' : 'Firebase snapshot';
    if (sampleCount) sampleCount.textContent = ecgSamples.length;
    if (sensorClock) sensorClock.textContent = cleanNumber(reading.sensor_timestamp, 3);
    if (signalIntegrity) signalIntegrity.textContent = reading.ecg == null ? 'No sensor signal' : 'Raw sample received';

    lastSuccess = Date.now();
    setConnection('connected', 'Firebase live', `Receiving /${data.firebase?.path?.replace(/^\//, '') || 'patient'} telemetry`);
  }

  async function hydrateInitialSnapshot() {
    try {
      const response = await fetch(apiUrl, {headers: {'Accept': 'application/json'}, cache: 'no-store'});
      const data = await response.json();
      if (response.status === 401) {
        window.location.assign('/login/?next=/');
        return false;
      }
      if (!response.ok || !data.ok) throw new Error(data.detail || data.error || 'Telemetry request failed');
      updateDashboard(data);
      return true;
    } catch (error) {
      setConnection('disconnected', 'Firebase unavailable', error.message || 'Unable to read /patient');
      return false;
    }
  }

  function stopFallbackPolling() {
    if (!fallbackTimer) return;
    clearInterval(fallbackTimer);
    fallbackTimer = null;
  }

  function startFallbackPolling() {
    if (fallbackTimer) return;
    fallbackTimer = setInterval(async () => {
      try {
        const response = await fetch(apiUrl, {headers: {'Accept': 'application/json'}, cache: 'no-store'});
        const data = await response.json();
        if (response.status === 401) {
          stopFallbackPolling();
          window.location.assign('/login/?next=/');
          return;
        }
        if (!response.ok || !data.ok) throw new Error(data.detail || data.error || 'Telemetry request failed');
        updateDashboard(data);
      } catch (error) {
        setConnection('disconnected', 'Connection lost', error.message || 'Retrying Firebase');
      }
    }, Math.max(1000, fallbackInterval));
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectRealtime();
    }, 5000);
  }

  function connectRealtime() {
    if (!streamUrl || !window.EventSource) {
      setConnection('fallback', 'Polling Firebase', 'Refreshing the snapshot automatically');
      startFallbackPolling();
      return;
    }

    if (eventSource) eventSource.close();
    stopFallbackPolling();
    setConnection('connecting', 'Connecting', 'Opening Firebase /patient stream');
    eventSource = new EventSource(streamUrl);

    eventSource.addEventListener('telemetry', event => {
      try {
        const data = JSON.parse(event.data);
        if (!data.ok) throw new Error(data.detail || data.error || 'Realtime telemetry failed');
        updateDashboard(data);
        stopFallbackPolling();
      } catch (error) {
        setConnection('disconnected', 'Realtime data error', error.message || 'Invalid telemetry packet');
      }
    });

    eventSource.addEventListener('telemetry_error', event => {
      let detail = 'Firebase realtime stream disconnected';
      try {
        const data = JSON.parse(event.data);
        detail = data.detail || data.error || detail;
      } catch (_) {}
      setConnection('disconnected', 'Firebase stream lost', detail);
      eventSource?.close();
      eventSource = null;
      startFallbackPolling();
      scheduleReconnect();
    });

    eventSource.onerror = () => {
      setConnection('disconnected', 'Reconnecting', 'Realtime stream interrupted');
      startFallbackPolling();
      scheduleReconnect();
    };
  }

  hydrateInitialSnapshot().finally(connectRealtime);

  setInterval(() => {
    if (lastSuccess && Date.now() - lastSuccess > 12000) {
      setConnection('disconnected', 'Stale telemetry', 'No recent Firebase packet received');
    }
  }, 2500);

  window.addEventListener('resize', redrawCharts);
  window.addEventListener('beforeunload', () => {
    eventSource?.close();
    if (reconnectTimer) clearTimeout(reconnectTimer);
    stopFallbackPolling();
  });
})();
