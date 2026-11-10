// Gives the setup skill's questionnaire page the storage it expects in the Claude app
// (window.claude.use("db"), documents "intake/prefill" and "intake/answers"), backed by the
// panel's own endpoints. Decision 0010.
(function () {
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
        return fetch(url, {
          method: "PUT", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
        }).then(function (r) { if (!r.ok) throw new Error("save " + r.status); });
      },
    };
  }
  window.claude = {
    use: function (capability) {
      return Promise.resolve(capability === "db" ? { doc: doc } : null);
    },
  };
})();
