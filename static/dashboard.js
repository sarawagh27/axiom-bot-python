const root = document.querySelector("[data-dashboard]");
let dashboard = root ? JSON.parse(root.dataset.dashboard) : null;
let latestEventId = dashboard?.latest_event_id || Math.max(
  0,
  ...(dashboard?.events || []).map((event) => event.id || 0),
);
const charts = {};

function formatTime(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "";
  return new Date(value * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTimes() {
  document.querySelectorAll("time[data-ts]").forEach((node) => {
    node.textContent = formatTime(node.dataset.ts);
  });
}

function pulse(node) {
  if (!node) return;
  node.classList.remove("pulse");
  void node.offsetWidth;
  node.classList.add("pulse");
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node && node.textContent !== String(value)) {
    node.textContent = value;
    pulse(node);
  }
}

function renderChart(id, series, label, color) {
  const canvas = document.getElementById(id);
  if (!canvas || !window.Chart) return;

  const labels = series.map((point) => point.label);
  const values = series.map((point) => point.value);

  charts[id] = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label,
        data: values,
        borderColor: color,
        backgroundColor: `${color}33`,
        fill: true,
        tension: 0.35,
        pointRadius: 3,
      }],
    },
    options: {
      animation: { duration: 650, easing: "easeOutQuart" },
      responsive: true,
      plugins: {
        legend: {
          labels: { color: "#8fa2b7" },
        },
      },
      scales: {
        x: {
          ticks: { color: "#8fa2b7" },
          grid: { color: "#263444" },
        },
        y: {
          beginAtZero: true,
          ticks: { color: "#8fa2b7", precision: 0 },
          grid: { color: "#263444" },
        },
      },
    },
  });
}

function updateChart(id, series) {
  const chart = charts[id];
  if (!chart) return;
  chart.data.labels = series.map((point) => point.label);
  chart.data.datasets[0].data = series.map((point) => point.value);
  chart.update();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function eventMarkup(event) {
  const command = event.command ? ` &middot; command=/${escapeHtml(event.command)}` : "";
  const user = event.user_id ? ` &middot; user=${escapeHtml(event.user_id)}` : "";
  return `
    <div class="event severity-${escapeHtml(event.severity)} incoming" data-event-id="${escapeHtml(event.id)}">
      <time data-ts="${escapeHtml(event.timestamp)}">${formatTime(event.timestamp)}</time>
      <strong>${escapeHtml(event.event_type)}</strong>
      <span>${escapeHtml(event.severity)}</span>
      <p>source=${escapeHtml(event.source)}${command}${user}</p>
    </div>
  `;
}

function timelineMarkup(item) {
  return `
    <div class="timeline-item severity-${escapeHtml(item.severity)} incoming">
      <time data-ts="${escapeHtml(item.timestamp)}">${formatTime(item.timestamp)}</time>
      <strong>${escapeHtml(item.title)}</strong>
      <p>${escapeHtml(item.description)}</p>
    </div>
  `;
}

function anomalyMarkup(signal) {
  return `
    <div class="anomaly severity-${escapeHtml(signal.severity)} incoming">
      <strong>${escapeHtml(signal.title)}</strong>
      <p>${escapeHtml(signal.description)}</p>
      <span>${escapeHtml(signal.count)} / ${escapeHtml(signal.threshold)} &middot; ${escapeHtml(signal.anomaly_type)}</span>
    </div>
  `;
}

function commandMarkup(command) {
  return `
    <div class="incoming">
      <span>/${escapeHtml(command.command)}</span>
      <strong>${escapeHtml(command.uses)}</strong>
    </div>
  `;
}

function replaceList(selector, html, emptyText) {
  const node = document.querySelector(selector);
  if (!node) return;
  node.innerHTML = html || `<p class="empty">${emptyText}</p>`;
}

function updateDashboard(payload) {
  dashboard = payload;
  latestEventId = payload.latest_event_id || latestEventId;

  setText("[data-guild-id]", payload.guild_id || "No telemetry yet");
  setText("[data-health-score]", payload.health.score);
  setText("[data-health-status]", payload.health.status_label);

  const band = document.querySelector("[data-health-band]");
  if (band) {
    band.className = `health-band health-${payload.health.status}`;
    pulse(band);
  }

  Object.entries(payload.health.factors || {}).forEach(([key, value]) => {
    setText(`[data-factor="${key}"]`, value);
  });

  Object.entries(payload.live_metrics || {}).forEach(([key, value]) => {
    setText(`[data-live-metric="${key}"]`, value);
  });

  Object.entries(payload.analytics || {}).forEach(([key, value]) => {
    if (typeof value === "number") {
      setText(`[data-analytics="${key}"]`, value);
    }
  });

  setText("[data-anomaly-severity]", payload.anomalies.highest_severity);
  setText("[data-event-count]", `${payload.events.length} events`);
  setText("[data-timeline-count]", `${payload.timeline.length} items`);

  replaceList(
    "[data-anomaly-list]",
    payload.anomalies.signals.slice(0, 6).map(anomalyMarkup).join(""),
    "No anomaly thresholds crossed in this window.",
  );
  replaceList(
    "[data-command-list]",
    payload.analytics.top_commands.map(commandMarkup).join(""),
    "No command usage recorded yet.",
  );
  replaceList(
    "[data-timeline]",
    payload.timeline.map(timelineMarkup).join(""),
    "No timeline activity has been recorded yet.",
  );
  replaceList(
    "[data-event-feed]",
    payload.events.map(eventMarkup).join(""),
    "No operational events have been recorded yet.",
  );

  updateChart("commandsChart", payload.analytics.commands_per_hour);
  updateChart("anomaliesChart", payload.analytics.anomalies_per_hour);
  formatTimes();
}

function connectStream() {
  if (!dashboard || !window.EventSource) return;

  const params = new URLSearchParams({
    interval: "3",
    after_id: String(latestEventId),
  });
  if (dashboard.guild_id) {
    params.set("guild_id", dashboard.guild_id);
  }

  const stream = new EventSource(`/dashboard/stream?${params.toString()}`);
  const liveState = document.querySelector("[data-live-state]");

  stream.addEventListener("open", () => {
    liveState?.classList.remove("offline");
  });
  stream.addEventListener("error", () => {
    liveState?.classList.add("offline");
  });
  stream.addEventListener("dashboard", (message) => {
    updateDashboard(JSON.parse(message.data));
  });
}

formatTimes();

if (dashboard) {
  renderChart(
    "commandsChart",
    dashboard.analytics.commands_per_hour,
    "Commands",
    "#60a5fa",
  );
  renderChart(
    "anomaliesChart",
    dashboard.analytics.anomalies_per_hour,
    "Anomalies",
    "#f87171",
  );
  connectStream();
}
