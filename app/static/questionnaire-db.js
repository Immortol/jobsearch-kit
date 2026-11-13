// Gives the setup skill's questionnaire page the storage it expects in the Claude app
// (window.claude.use("db"), documents "intake/prefill" and "intake/answers"), backed by the
// panel's own endpoints. Decision 0010.
(function () {
  var pending = Promise.resolve();

  function doc(path) {
    var name = String(path).split("/").pop();
    var url = "/questionnaire/data/" + encodeURIComponent(name);
    return {
      get: function () {
        return fetch(url, { credentials: "same-origin", cache: "no-store" })
          .then(function (r) { if (!r.ok) throw new Error("load " + r.status); return r.json(); })
          .then(function (body) {
            return { exists: !!body.exists, data: function () { return body.data || {}; } };
          });
      },
      set: function (data) {
        var request = fetch(url, {
          method: "PUT", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
        }).then(function (r) { if (!r.ok) throw new Error("save " + r.status); });
        pending = request.catch(function () {});
        return request;
      },
    };
  }
  // "Done" in the panel's bar: let the page's autosave (0.8 s after the last change) finish first.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("form[data-jsk-done]") || form.dataset.ready) return;
    e.preventDefault();
    var button = form.querySelector("button");
    if (button) button.disabled = true;
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    setTimeout(function () {
      pending.then(function () { form.dataset.ready = "1"; form.submit(); });
    }, 1000);
  });

  window.claude = {
    use: function (capability) {
      return Promise.resolve(capability === "db" ? { doc: doc } : null);
    },
  };
})();
