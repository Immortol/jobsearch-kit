// Chat page behaviour: keeps the newest message in view, clears the box after sending,
// and blocks sending while a reply is still being written. Loaded on every page; no-op elsewhere.
(function () {
  function composer() { return document.querySelector("form[data-composer]"); }

  function sync() {
    var form = composer();
    var thread = document.getElementById("thread");
    if (!form || !thread) return;
    var busy = thread.querySelector(".msg.running") !== null;
    var button = form.querySelector("button[type=submit]");
    if (button) button.disabled = busy;
  }

  function scrollDown() {
    var thread = document.getElementById("thread");
    if (thread && thread.lastElementChild) {
      thread.lastElementChild.scrollIntoView({ block: "end", behavior: "smooth" });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    sync();
    scrollDown();
    var form = composer();
    if (!form) return;
    var box = form.querySelector("textarea");
    // Ctrl/Cmd + Enter sends; plain Enter is a new line (comfortable on phones).
    box.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (typeof form.requestSubmit === "function") form.requestSubmit(); else form.submit();
      }
    });
    // Plain (non-htmx) forms: avoid double submits.
    form.addEventListener("submit", function () {
      if (!form.hasAttribute("hx-post")) {
        var b = form.querySelector("button[type=submit]");
        if (b) setTimeout(function () { b.disabled = true; }, 0);
      }
    });
  });

  document.addEventListener("htmx:afterRequest", function (e) {
    var form = composer();
    if (form && e.detail.elt === form && e.detail.successful) {
      form.reset();
      scrollDown();
    }
  });
  document.addEventListener("htmx:afterSettle", function () {
    sync();
  });
})();
