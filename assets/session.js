(function () {
  function root() { return document.getElementById("session-root"); }
  function attr(name) { var el = root(); return el ? el.getAttribute(name) || "" : ""; }
  function url(name) { return attr("data-base") + "_session/" + name; }

  setInterval(function () {
    var sid = attr("data-sid");
    if (sid) fetch(url("ping"), { method: "POST", body: sid, keepalive: true }).catch(function () {});
  }, 20000);

  window.addEventListener("pagehide", function () {
    var sid = attr("data-sid");
    if (sid && navigator.sendBeacon) navigator.sendBeacon(url("end"), sid);
  });

  window.addEventListener("pageshow", function (event) {
    if (event.persisted) window.location.reload();
  });
})();
