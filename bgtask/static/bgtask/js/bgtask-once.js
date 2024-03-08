// Add bgtask.js into the page just once, allowing this to be added many times on the same page
// without running into errors due to redeclaring variables etc.
//
// Must be executed syncronously, so without the async flag to <script>
(() => {
  if (window.BG_TASK_ADDED) {
    // Have already bootstrapped.
    return;
  }

  // Get the URL of the current script. This only works if this script is executed synchronously.
  const scripts = document.getElementsByTagName('script');
  const thisScript = scripts[scripts.length - 1];
  const src = thisScript.src;
  const baseSrc = src.replace(/[^\/]+$/, '');

  // Use document.write() to inject the main script immediately.
  document.write(`<script src="${baseSrc}bgtask.js"></script>`);
})();
