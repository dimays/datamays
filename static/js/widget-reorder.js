/**
 * Drag-and-drop reordering for the homepage widget list in Preferences.
 *
 * Deliberately not a library: this is one list, reordered by dragging rows
 * within a single container, which native HTML5 drag-and-drop covers on its
 * own. The only state that needs to survive is the resulting slug order,
 * written into a hidden input the form already submits.
 */
(function () {
  "use strict";

  function initReorder(container) {
    var hiddenInput = document.querySelector(container.dataset.orderInput);
    var dragging = null;

    function writeOrder() {
      var slugs = Array.prototype.map.call(
        container.querySelectorAll("[data-widget-row]"),
        function (row) {
          return row.dataset.widgetRow;
        }
      );
      if (hiddenInput) hiddenInput.value = slugs.join(",");
    }

    container.querySelectorAll("[data-widget-row]").forEach(function (row) {
      row.setAttribute("draggable", "true");

      row.addEventListener("dragstart", function () {
        dragging = row;
        row.classList.add("opacity-40");
      });

      row.addEventListener("dragend", function () {
        row.classList.remove("opacity-40");
        dragging = null;
        writeOrder();
      });

      row.addEventListener("dragover", function (event) {
        event.preventDefault();
        if (!dragging || dragging === row) return;

        var rect = row.getBoundingClientRect();
        var after = event.clientY - rect.top > rect.height / 2;
        container.insertBefore(dragging, after ? row.nextSibling : row);
      });
    });

    writeOrder();
  }

  document.querySelectorAll("[data-widget-reorder]").forEach(initReorder);
})();
