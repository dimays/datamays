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
   * formatter and tooltips from every line chart.
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
              return context.dataset.label + ": " + money(context.parsed.y);
            },
          },
        },
      },
    };

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

  function buildStackedBar(canvas, data) {
    var datasets = (data.series || []).map(function (series, index) {
      return {
        label: series.label,
        data: series.values,
        backgroundColor: COLORS[index % COLORS.length],
        stack: "spend",
        borderRadius: 2,
      };
    });

    var options = makeOptions({});
    options.scales.x.stacked = true;
    options.scales.y.stacked = true;

    return new Chart(canvas, {
      type: "bar",
      data: { labels: data.labels, datasets: datasets },
      options: options,
    });
  }

  /**
   * One horizontal bar per top-level category, ranked largest-first. The
   * "Breakout by subcategory" checkbox next to it (wired in
   * initBreakoutToggles(), not here) swaps every category's single bar for
   * one bar per subcategory all at once, without disturbing category-level
   * rank — a category's subcategories render in exactly the row range its
   * own bar used to occupy.
   */
  function buildCategoryBreakdown(canvas, data, expanded) {
    var rows = [];

    (data.categories || []).forEach(function (category) {
      var children = category.subcategories || [];

      if (expanded && children.length) {
        children.forEach(function (child) {
          rows.push({ label: category.name + " › " + child.name, value: child.total });
        });
      } else {
        rows.push({ label: category.name, value: category.total });
      }
    });

    // Fixed row height so the chart reads consistently whether it's 6
    // categories or 60 — the scrollable wrapper (set in the template)
    // handles the rest rather than squeezing bars to fit.
    canvas.style.height = Math.max(240, rows.length * 32) + "px";

    var options = makeOptions({});
    options.indexAxis = "y";
    options.plugins.legend.display = false;
    options.plugins.tooltip.callbacks.label = function (context) {
      return money(context.parsed.x);
    };
    options.scales = {
      x: { beginAtZero: true, ticks: { color: TEXT, callback: money }, grid: { color: GRID } },
      y: { ticks: { color: TEXT, autoSkip: false }, grid: { display: false } },
    };

    var config = {
      labels: rows.map(function (row) { return row.label; }),
      datasets: [
        { data: rows.map(function (row) { return row.value; }), backgroundColor: COLORS[0], borderRadius: 3 },
      ],
    };

    return new Chart(canvas, { type: "bar", data: config, options: options });
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
    lines: buildLines,
    line: buildSingleLine,
    budgets: buildBudgets,
    categoryBreakdown: buildCategoryBreakdown,
  };

  /**
   * A chart with a "split by category" checkbox: rebuilds in place between
   * its normal single-series view and a stacked-by-category view sharing
   * the same canvas, rather than being auto-built by the loop below.
   */
  function initToggles() {
    document.querySelectorAll("[data-chart-toggle]").forEach(function (toggle) {
      var canvas = document.querySelector(
        'canvas[data-toggle="' + toggle.dataset.chartToggle + '"]'
      );
      if (!canvas) return;

      var combined = readData(canvas);
      var stackedHolder = document.getElementById(canvas.dataset.sourceStacked);
      var stacked = null;
      try {
        stacked = stackedHolder ? JSON.parse(stackedHolder.textContent) : null;
      } catch (error) {
        stacked = null;
      }

      var chart = null;

      function render() {
        if (chart) chart.destroy();
        chart =
          toggle.checked && stacked
            ? buildStackedBar(canvas, stacked)
            : buildBar(canvas, combined);
      }

      if (combined) render();
      toggle.addEventListener("change", render);
    });
  }

  /**
   * A category-breakdown chart with a "Breakout by subcategory" checkbox:
   * rebuilds in place, expanding or collapsing every category at once
   * (buildCategoryBreakdown's `expanded` flag), rather than being
   * auto-built by the loop below.
   */
  function initBreakoutToggles() {
    document.querySelectorAll("[data-breakout-toggle]").forEach(function (toggle) {
      var canvas = document.querySelector(
        'canvas[data-breakout-target="' + toggle.dataset.breakoutToggle + '"]'
      );
      if (!canvas) return;

      var data = readData(canvas);
      var chart = null;

      function render() {
        if (chart) chart.destroy();
        chart = buildCategoryBreakdown(canvas, data, toggle.checked);
      }

      if (data) render();
      toggle.addEventListener("change", render);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
      if (canvas.dataset.toggle) return; // owned by initToggles() instead
      if (canvas.dataset.breakoutTarget) return; // owned by initBreakoutToggles() instead
      var data = readData(canvas);
      var builder = BUILDERS[canvas.dataset.chart];
      if (data && builder) builder(canvas, data);
    });

    initToggles();
    initBreakoutToggles();
  });
})();
