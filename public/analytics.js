// Funnel event tracking for GA4 (G-MCDDGJ3XEC).
//
// One delegated click listener fires named events for the things that matter on a
// launch site — outbound clicks to GitHub / X / LinkedIn (the conversion goals)
// and internal navigation between pages (the funnel) — so the analytics can answer
// "do visitors convert and how do they move", not just "which page did they land on".
//
// window.track(name, params) is exposed for page-specific events.
(function () {
  "use strict";

  function track(name, params) {
    if (typeof window.gtag === "function") {
      window.gtag("event", name, params || {});
    }
  }
  window.track = track;

  function currentPage() {
    var p = location.pathname.replace(/^\//, "");
    return p === "" ? "index.html" : p;
  }

  // Capture phase so the beacon is queued before the browser follows the link.
  document.addEventListener(
    "click",
    function (event) {
      var anchor = event.target && event.target.closest ? event.target.closest("a[href]") : null;
      if (!anchor) return;

      var href = anchor.getAttribute("href") || "";
      if (!href || href.charAt(0) === "#") return;

      var url;
      try {
        url = new URL(href, location.href);
      } catch (_) {
        return;
      }

      var linkText = (anchor.textContent || "").trim().slice(0, 80);

      // Internal navigation between site pages.
      if (url.host === location.host) {
        if (/\.html$/.test(url.pathname) || url.pathname === "/") {
          track("nav_click", {
            destination: url.pathname.replace(/^\//, "") || "index.html",
            from_page: currentPage(),
            link_text: linkText,
          });
        }
        return;
      }

      // Outbound clicks — name the important conversion targets explicitly so they
      // can be marked as key events in GA with one click.
      var domain = url.hostname.replace(/^www\./, "");
      var name = "outbound_click";
      if (domain === "github.com") name = "outbound_github";
      else if (domain === "x.com" || domain === "twitter.com") name = "outbound_x";
      else if (domain === "linkedin.com") name = "outbound_linkedin";

      track(name, {
        link_url: url.href,
        link_domain: domain,
        link_text: linkText,
        from_page: currentPage(),
      });
    },
    true
  );
})();
