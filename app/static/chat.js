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
    // A chat opens at its newest message; a vacancy card opens at its top (the assessment).
    if (location.pathname.indexOf("/chats/") === 0) scrollDown();
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

  function showFileName(input) {
    var label = input.closest(".attach");
    var name = label && label.querySelector("[data-attach-name]");
    if (!name) return;
    if (!name.dataset.empty) name.dataset.empty = name.textContent;
    var file = input.files && input.files[0];
    var more = input.files && input.files.length > 1 ? " +" + (input.files.length - 1) : "";
    name.textContent = file ? file.name + more : name.dataset.empty;
    label.classList.toggle("has-file", !!file);
  }

  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches("input[data-attach]")) showFileName(e.target);
  });

  document.addEventListener("htmx:beforeRequest", function (e) {
    // Answer buttons belong to the question just answered: remove them once anything is sent.
    if (e.detail.elt.closest && (e.detail.elt.closest("[data-choices]") ||
        e.detail.elt.matches("form[data-composer]"))) {
      document.querySelectorAll("[data-choices]").forEach(function (el) {
        el.classList.add("answered");
      });
    }
  });

  document.addEventListener("htmx:afterRequest", function (e) {
    var form = composer();
    if (form && e.detail.elt === form && e.detail.successful) {
      form.reset();
      var input = form.querySelector("input[data-attach]");
      if (input) showFileName(input);
    }
    if (e.detail.successful) {
      document.querySelectorAll("[data-choices].answered").forEach(function (el) { el.remove(); });
      // Scroll only when the person sent something. The once-a-second refresh of a running
      // reply must not move the page: they may be reading something else.
      if ((e.detail.requestConfig || {}).verb === "post") scrollDown();
    } else {
      document.querySelectorAll("[data-choices].answered").forEach(function (el) {
        el.classList.remove("answered");
      });
    }
  });
  document.addEventListener("htmx:afterSettle", function () {
    sync();
  });
})();

// Tracker: a status change saves at once.
document.addEventListener("change", function (e) {
  if (e.target.matches && e.target.matches("select[data-autosubmit]")) e.target.form.submit();
});
