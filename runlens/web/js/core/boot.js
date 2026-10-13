/* core/boot.js: loaded first. Any error the page hits is counted on <html data-errors>, so a test that
   opens the page in a headless browser can tell a clean render from a broken one. */

function reportError(err) {
  const root = document.documentElement;
  root.dataset.errors = String(Number(root.dataset.errors || 0) + 1);
  root.dataset.lastError = String((err && (err.message || err.reason)) || err).slice(0, 300);
}
window.addEventListener("error", (e) => reportError(e.error || e.message));
window.addEventListener("unhandledrejection", (e) => reportError(e.reason));
