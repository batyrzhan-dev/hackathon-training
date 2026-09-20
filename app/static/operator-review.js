// A normal form POST runs Python scoring; no scoring rules live in JavaScript.
for (const form of document.querySelectorAll('.override-form')) {
  form.querySelector('select').addEventListener('change', () => form.requestSubmit());
}
