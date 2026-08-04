/**
 * Chart setup for the finance dashboards.
 *
 * Charts read their data from a <script type="application/json"> next to the
 * canvas rather than from inline script, so no page needs inline JS and the
 * data survives being escaped by the template engine.
 */
(function () {
  "use strict";

  // Pulled from the site's Tailwind tokens so charts match the rest of the app.
  var COLORS = [
    "#4F46E5", "#14B8A6", "#F59E0B", "#EF4444", "#22C55E",
    "#A78BFA", "#38BDF8", "#FB7185", "#FBBF24", "#34D399",
  ];

  var GRID = "rgba(46, 58, 73, 0.6)";
  var TEXT = "#9CA3AF";

  function readData(canvas) {
    var holder = document.getElementById(canvas.dataset.source);
    if (!holder) return null;
    try {
      return JSON.parse(holder.textContent);
    } catch (error) {
      return null;
    }
  }

  function money(value) {
    if (value === null || value === undefined) return "—";
    var number = Number(value);
    var formatted = Math.abs(number).toLocaleString("en-US", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    });
    // Sign outside the symbol: "-$275,000" rather than "$-275,000".
    return (number < 0 ? "-$" : "$") + formatted;
  }

  /**
   * Open a bar's linked transaction list in a new tab.
   *
   * `elements` comes from Chart.js's own onClick — it is already resolved to
   * "which bar, in which dataset" by the time this runs, so there is no
   * pixel math here. `noopener` matters: the opened tab must not be able to
   * reach back into this one via window.opener.
   */
  function openLinkForElement(links, elements) {
    if (!links || !elements.length) return;

    var url = links[elements[0].index];
    if (url) window.open(url, "_blank", "noopener");
  }

  /**
   * Fresh options per chart.
   *
   * Deliberately a factory rather than a cloned constant: structured cloning
   * via JSON silently drops functions, which quietly stripped the currency
   * formatter and tooltips from every line and doughnut chart.
   */
  function makeOptions(options) {
    options = options || {};

    var config = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      onHover: options.links
        ? function (event, elements) {
            event.native.target.style.cursor = elements.length ? "pointer" : "default";
          }
        : undefined,
      onClick: options.links
        ? function (event, elements) {
            openLinkForElement(options.links, elements);
          }
        : undefined,
      plugins: {
        legend: {
          position: options.legendPosition || "top",
          labels: { color: TEXT, boxWidth: 12, usePointStyle: true },
        },
        tooltip: {
          callbacks: {
            label: function (context) {
              if (options.shape === "doughnut") {
                return context.label + ": " + money(context.parsed);
              }
              return context.dataset.label + ": " + money(context.parsed.y);
            },
          },
        },
      },
    };

    if (options.shape !== "doughnut") {
      config.scales = {
        x: {
          ticks: {
            color: TEXT,
            maxRotation: 0,
            autoSkip: true,
            // A year of daily points would otherwise run its date labels
            // together into an unreadable smear.
            maxTicksLimit: 6,
            autoSkipPadding: 16,
          },
          grid: { color: GRID },
        },
        y: {
          ticks: { color: TEXT, callback: money },
          grid: { color: GRID },
          // Balances are rarely near zero, so forcing the axis to include it
          // would flatten every interesting movement.
          beginAtZero: options.beginAtZero !== false,
        },
      };
    }

    return config;
  }

  function buildBar(canvas, data) {
    return new Chart(canvas, {
      type: "bar",
      data: {
        labels: data.labels,
        datasets: [{ label: canvas.dataset.label || "Spend", data: data.values, backgroundColor: COLORS[0], borderRadius: 4 }],
      },
      options: makeOptions({ links: data.links }),
    });
  }

  function buildDoughnut(canvas, data) {
    return new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: data.labels,
        datasets: [{ data: data.values, backgroundColor: COLORS, borderWidth: 0 }],
      },
      options: makeOptions({ shape: "doughnut", legendPosition: "bottom" }),
    });
  }

  function buildLines(canvas, data) {
    var datasets = (data.series || []).map(function (series, index) {
      return {
        label: series.label,
        data: series.values,
        borderColor: COLORS[index % COLORS.length],
        backgroundColor: COLORS[index % COLORS.length],
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.25,
        spanGaps: true,
      };
    });

    return new Chart(canvas, {
      type: "line",
      data: { labels: data.labels, datasets: datasets },
      options: makeOptions({ beginAtZero: false }),
    });
  }

  function buildSingleLine(canvas, data) {
    return buildLines(canvas, {
      labels: data.labels,
      series: [{ label: canvas.dataset.label || "Total", values: data.values }],
    });
  }

  function buildBudgets(canvas, data) {
    var series = (data || []).find(function (entry) {
      return entry.name === canvas.dataset.budget;
    });
    if (!series) return null;

    return new Chart(canvas, {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: [
          { label: "Actual", data: series.actual, backgroundColor: COLORS[0], borderRadius: 4 },
          { label: "Target", data: series.target, type: "line", borderColor: COLORS[2], borderWidth: 2, pointRadius: 0 },
        ],
      },
      options: makeOptions({ links: series.links }),
    });
  }

  var BUILDERS = {
    bar: buildBar,
    doughnut: buildDoughnut,
    lines: buildLines,
    line: buildSingleLine,
    budgets: buildBudgets,
  };

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
      var data = readData(canvas);
      var builder = BUILDERS[canvas.dataset.chart];
      if (data && builder) builder(canvas, data);
    });
  });
})();
