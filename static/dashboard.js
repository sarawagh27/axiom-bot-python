const root = document.querySelector("[data-dashboard]");
const dashboard = root ? JSON.parse(root.dataset.dashboard) : null;

function formatTimes() {
  document.querySelectorAll("time[data-ts]").forEach((node) => {
    const seconds = Number(node.dataset.ts);
    if (!Number.isFinite(seconds)) return;
    node.textContent = new Date(seconds * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  });
}

function renderChart(id, series, label, color) {
  const canvas = document.getElementById(id);
  if (!canvas || !window.Chart) return;

  const labels = series.map((point) => point.label);
  const values = series.map((point) => point.value);

  new Chart(canvas, {
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
}
