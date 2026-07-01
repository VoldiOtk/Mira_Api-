/*!
 * mira-client.js — Module partagé de l'espace client Mira (GV TECH).
 *
 * Fournit l'interface d'accès à l'API backend, les helpers d'auth, les toasts
 * et le guard de navigation pour toutes les pages de frontend/espace-client/.
 *
 * La couche complète de services (appels réseau, cache, pagination, export CSV…)
 * se trouve dans javascript/mira-api.js + javascript/mira-espace.js, qui sont
 * chargés par chaque page privée. Ce module expose l'interface simplifiée de la
 * spec et délègue vers ces deux couches quand elles sont présentes.
 *
 * Utilisation dans une page :
 *   <script src="js/mira-client.js"></script>
 *   Les fonctions ci-dessous sont disponibles directement dans la portée globale.
 */
(function (window) {
  "use strict";

  /* ---------------------------------------------------------------------------
   * Base URL
   * Priorité : window.MIRA_API_BASE (injecté par un script config) → défaut.
   * --------------------------------------------------------------------------- */
  var MIRA_API_BASE = window.MIRA_API_BASE || "http://localhost:8000";
  var TOKEN_KEY = "mira_client_token";

  /* ---------------------------------------------------------------------------
   * Helpers token
   * --------------------------------------------------------------------------- */
  function getToken() {
    try { return window.localStorage.getItem(TOKEN_KEY) || null; } catch (e) { return null; }
  }
  function saveToken(t) {
    try {
      if (t) window.localStorage.setItem(TOKEN_KEY, t);
      else window.localStorage.removeItem(TOKEN_KEY);
    } catch (e) {}
  }
  function clearToken() { saveToken(null); }

  function authHeaders() {
    var t = getToken();
    return t
      ? { "Authorization": "Bearer " + t, "Content-Type": "application/json" }
      : { "Content-Type": "application/json" };
  }

  /* ---------------------------------------------------------------------------
   * apiFetch — wrapper fetch centralisé
   *
   * Renvoie la réponse JSON décodée, ou null pour les 204.
   * Redirige vers connexion.html sur 401 (token expiré / invalide).
   * Lance une exception { status, detail } sur toute autre erreur HTTP.
   * --------------------------------------------------------------------------- */
  function apiFetch(path, options) {
    options = options || {};
    var merged = Object.assign({}, authHeaders(), options.headers || {});
    var fetchOpts = Object.assign({}, options);
    fetchOpts.headers = merged;

    return fetch(MIRA_API_BASE + path, fetchOpts).then(function (res) {
      if (res.status === 401) {
        clearToken();
        window.location.replace("connexion.html");
        return;
      }
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (err) {
          throw { status: res.status, detail: (err && (err.detail || err.message)) || "Erreur serveur " + res.status };
        });
      }
      if (res.status === 204) return null;
      var ct = res.headers.get("content-type") || "";
      return ct.indexOf("application/json") !== -1 ? res.json() : res.text();
    });
  }

  /* ---------------------------------------------------------------------------
   * Toast non bloquant
   * --------------------------------------------------------------------------- */
  function showToast(message, type) {
    type = type || "success";
    var box = document.getElementById("mira-client-toast");
    if (!box) {
      box = document.createElement("div");
      box.id = "mira-client-toast";
      box.style.cssText =
        "position:fixed;top:18px;right:18px;z-index:9999;max-width:360px;" +
        "padding:13px 16px;border-radius:8px;font-size:13px;font-family:sans-serif;" +
        "box-shadow:0 10px 30px rgba(0,0,0,.4);transition:opacity .3s;opacity:0;";
      document.body.appendChild(box);
    }
    var ok = (type === "success" || type === "ok");
    box.style.background = ok ? "rgba(4,174,198,.16)" : "rgba(255,45,120,.16)";
    box.style.border = "1px solid " + (ok ? "rgba(4,174,198,.45)" : "rgba(255,45,120,.45)");
    box.style.color = ok ? "#7fe3ef" : "#ff8db5";
    box.textContent = message;
    box.style.opacity = "1";
    clearTimeout(box._t);
    box._t = setTimeout(function () { box.style.opacity = "0"; }, 4000);
  }

  function showError(message) { showToast(message, "danger"); }

  /* ---------------------------------------------------------------------------
   * Déconnexion
   * --------------------------------------------------------------------------- */
  function logout() {
    clearToken();
    try {
      window.localStorage.removeItem("mira_client_user");
      window.localStorage.removeItem("mira_client_prefs");
    } catch (e) {}
    window.location.replace("connexion.html");
  }

  /* ---------------------------------------------------------------------------
   * Expose dans window — interface spec
   * --------------------------------------------------------------------------- */
  window.MIRA_API_BASE = MIRA_API_BASE;
  window.getToken    = getToken;
  window.saveToken   = saveToken;
  window.clearToken  = clearToken;
  window.authHeaders = authHeaders;
  window.apiFetch    = apiFetch;
  window.showToast   = showToast;
  window.showError   = showError;
  window.logout      = logout;

  /* Si javascript/mira-api.js est également chargé, on synchronise la base URL
   * pour que les deux couches pointent vers le même backend. */
  if (window.MiraAPI && typeof window.MiraAPI.configure === "function") {
    window.MiraAPI.configure({ baseUrl: MIRA_API_BASE });
  }

})(window);
