/*!
 * mira-espace.js — Logique commune des pages PRIVÉES de l'espace client Mira.
 *
 * À charger APRÈS mira-api.js et AVANT (ou après) main.js sur chaque page privée.
 * Rôles :
 *   1. Garde d'accès : redirige vers connexion.html si non authentifié.
 *      (La garde est aussi posée en tête de page, en ligne, pour bloquer AVANT le rendu.)
 *   2. Déconnexion : branche les liens « Déconnexion » (header + sidebar) sur MiraAPI.logout().
 *   3. Identité : remplit le nom (et l'organisation/role) dans le header et la sidebar
 *      à partir du profil réel (cache immédiat puis rafraîchissement via getProfile()).
 *
 * Expose window.MiraEspace.{ guard, ready, escapeHtml, formatDate, errText, toast }.
 */
(function (window, document) {
  "use strict";

  function guard() {
    if (!window.MiraAPI || !window.MiraAPI.isAuthenticated()) {
      window.location.replace("connexion.html");
      return false;
    }
    return true;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Transforme l'erreur uniforme {error} de MiraAPI en texte lisible.
  function errText(err, fallback) {
    fallback = fallback || "Une erreur est survenue.";
    if (!err) return fallback;
    if (typeof err === "string") return err;
    if (Array.isArray(err)) {
      return err
        .map(function (e) { return e && e.msg ? e.msg : (typeof e === "string" ? e : JSON.stringify(e)); })
        .join(" ");
    }
    if (err.msg) return err.msg;
    if (err.detail) return typeof err.detail === "string" ? err.detail : errText(err.detail, fallback);
    return fallback;
  }

  function formatDate(value, withTime) {
    if (!value) return "—";
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    var opts = withTime
      ? { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }
      : { day: "2-digit", month: "long", year: "numeric" };
    try { return d.toLocaleDateString("fr-FR", opts); } catch (e) { return d.toISOString(); }
  }

  // Petit toast non bloquant (succès/erreur) réutilisé par toutes les pages.
  function toast(message, kind) {
    var box = document.getElementById("mira-toast");
    if (!box) {
      box = document.createElement("div");
      box.id = "mira-toast";
      box.style.cssText =
        "position:fixed;top:18px;right:18px;z-index:9999;max-width:340px;padding:13px 16px;" +
        "border-radius:8px;font-size:13px;font-family:sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.4);" +
        "transition:opacity .3s;opacity:0;";
      document.body.appendChild(box);
    }
    var ok = kind !== "err";
    box.style.background = ok ? "rgba(4,174,198,.16)" : "rgba(255,45,120,.16)";
    box.style.border = "1px solid " + (ok ? "rgba(4,174,198,.45)" : "rgba(255,45,120,.45)");
    box.style.color = ok ? "#7fe3ef" : "#ff8db5";
    box.textContent = message;
    box.style.opacity = "1";
    clearTimeout(box._t);
    box._t = setTimeout(function () { box.style.opacity = "0"; }, 4000);
  }

  // Branche TOUS les liens « Déconnexion » de la page sur logout() + redirection.
  function wireLogout() {
    function onLogout(e) {
      if (e) e.preventDefault();
      if (window.MiraAPI) window.MiraAPI.logout();
      window.location.replace("connexion.html");
    }
    // Lien de la sidebar (li.logout) + tout lien dont le titre vaut « Déconnexion ».
    var nodes = document.querySelectorAll(
      '.sidebar-nav li.logout a, a[title="Déconnexion"], .dropdown-menu a'
    );
    Array.prototype.forEach.call(nodes, function (a) {
      var label = (a.textContent || "").trim().toLowerCase();
      var titleAttr = (a.getAttribute("title") || "").trim().toLowerCase();
      if (label === "déconnexion" || titleAttr === "déconnexion") {
        a.setAttribute("href", "#");
        a.addEventListener("click", onLogout);
      }
    });
  }

  // Le main.js du template traite la sidebar comme des onglets SPA et fait
  // preventDefault sur le clic → les vrais liens ne naviguent pas. On rétablit
  // la navigation réelle : en phase CAPTURE (avant le handler "onglet" du <li>),
  // on stoppe la propagation et on ouvre la page cible.
  function wireSidebarNav() {
    var links = document.querySelectorAll(
      ".vertical-navigation .sidebar-nav a[href], .vertical-navigation .user-options a[href]"
    );
    Array.prototype.forEach.call(links, function (a) {
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#") return; // ancres / déconnexion gérées ailleurs
      a.addEventListener(
        "click",
        function (e) {
          e.stopPropagation();
          window.location.href = href;
        },
        true
      );
    });
  }

  // Surligne l'entrée de sidebar correspondant à la PAGE COURANTE (déduite de
  // l'URL), au lieu de se fier au data-page recopié/au main.js du template.
  function highlightActiveNav() {
    var current = (window.location.pathname.split("/").pop() || "").toLowerCase();
    if (!current) return;
    var items = document.querySelectorAll(".vertical-navigation .sidebar-nav > li");
    Array.prototype.forEach.call(items, function (li) {
      var a = li.querySelector("a[href]");
      var href = a ? (a.getAttribute("href") || "").split("/").pop().toLowerCase() : "";
      if (href && href === current) li.classList.add("active");
      else li.classList.remove("active");
    });
  }

  // Met à jour le nom affiché dans le header (.user .info .name) et la sidebar.
  function applyIdentity(user) {
    if (!user) return;
    var name = user.name || user.email || "Client Mira";
    // Header : nom + sous-texte (on met le plan en sous-texte si présent).
    Array.prototype.forEach.call(document.querySelectorAll(".info-right .user .info .name"), function (el) {
      el.textContent = name;
    });
    var planLabel = user.plan ? ("Offre " + String(user.plan).charAt(0).toUpperCase() + String(user.plan).slice(1)) : "Espace client";
    Array.prototype.forEach.call(document.querySelectorAll(".info-right .user .info .address"), function (el) {
      el.textContent = planLabel;
    });
    // Sidebar : nom.
    Array.prototype.forEach.call(document.querySelectorAll(".vertical-navigation .user-options .name a"), function (el) {
      el.textContent = name;
    });
  }

  // Rafraîchit l'identité : cache immédiat, puis appel réseau.
  function refreshIdentity() {
    if (!window.MiraAPI) return;
    var cached = window.MiraAPI.getCachedUser();
    if (cached) applyIdentity(cached);
    window.MiraAPI.getProfile().then(function (res) {
      if (res && res.ok && res.data) applyIdentity(res.data);
      else if (res && (res.status === 401 || res.status === 403)) {
        // Token invalide/expiré → on déconnecte proprement.
        window.MiraAPI.logout();
        window.location.replace("connexion.html");
      }
    });
  }

  // Point d'entrée commun : à appeler au DOMContentLoaded de chaque page privée.
  function ready(cb) {
    if (!guard()) return; // stoppe tout si non authentifié
    function run() {
      wireSidebarNav();
      wireLogout();
      refreshIdentity();
      // Après main.js (qui peut forcer le mauvais item) : on (re)pose l'actif.
      setTimeout(highlightActiveNav, 30);
      if (typeof cb === "function") {
        try { cb(); } catch (e) { if (window.console) console.error("[mira-espace] page init error", e); }
      }
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", run);
    } else {
      run();
    }
  }

  window.MiraEspace = {
    guard: guard,
    ready: ready,
    escapeHtml: escapeHtml,
    errText: errText,
    formatDate: formatDate,
    toast: toast,
    applyIdentity: applyIdentity,
  };
})(window, document);
