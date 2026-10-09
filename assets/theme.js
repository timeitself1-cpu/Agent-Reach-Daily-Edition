// Applies the reader's saved colour theme before the page paints (the CSP allows no inline scripts).
// "Auto" (nothing saved) follows the system setting; the footer control in site.js saves a choice.
(function () {
  try {
    var t = localStorage.getItem('theme');
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
  } catch (e) { /* storage unavailable: follow the system */ }
})();
