// Statera web review interface — minimal progressive enhancement.
// No LLM is invoked from the page; this only handles UI concerns.

document.addEventListener('DOMContentLoaded', function () {
  // Confirm before submitting status-change forms that carry the `data-confirm` attribute.
  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      var message = form.getAttribute('data-confirm');
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    });
  });
});
