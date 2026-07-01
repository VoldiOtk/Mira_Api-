/*!
 * mira-api.js — Couche de services centralisée pour l'ESPACE CLIENT Mira (GV TECH).
 *
 * Module unique exposé sur `window.MiraAPI`. Script classique (pas un ES module)
 * pour être chargé via <script src="javascript/mira-api.js"></script> dans les
 * pages HTML statiques de frontend/espace-client/.
 *
 * - Base URL configurable (défaut : même origine que la page).
 * - Auth client JWT : token stocké/lu dans localStorage (clé "mira_client_token").
 *   (Clé DISTINCTE de l'admin, qui utilise "mira_admin_token".)
 * - Wrapper fetch ajoutant automatiquement `Authorization: Bearer <token>`.
 * - Gestion d'erreurs uniforme : toute fonction renvoie { ok, data, error, status }.
 *
 * Endpoints RÉELS : register, login, me (GET/PATCH/DELETE), me/password,
 * keys/*, usage/*, plans, subscription (GET/change), forgot-password,
 * reset-password.
 * Endpoint avec mock de repli (non implémenté côté backend) : billing/invoices.
 */
(function (window) {
  "use strict";

  // ---------------------------------------------------------------------------
  // Configuration
  // ---------------------------------------------------------------------------
  var DEFAULT_BASE_URL = ""; // "" = même origine (ex: appels vers /api/v1/...)
  var TOKEN_STORAGE_KEY = "mira_client_token"; // clé client, séparée de l'admin
  var USER_CACHE_KEY = "mira_client_user"; // cache profil optionnel

  var config = {
    baseUrl: DEFAULT_BASE_URL,
  };

  // ---------------------------------------------------------------------------
  // Stockage du token
  // ---------------------------------------------------------------------------
  function getToken() {
    try {
      return window.localStorage.getItem(TOKEN_STORAGE_KEY) || null;
    } catch (e) {
      return null;
    }
  }

  function setToken(token) {
    try {
      if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
      else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    } catch (e) {
      /* localStorage indisponible */
    }
  }

  function setCachedUser(user) {
    try {
      if (user) window.localStorage.setItem(USER_CACHE_KEY, JSON.stringify(user));
      else window.localStorage.removeItem(USER_CACHE_KEY);
    } catch (e) {
      /* noop */
    }
  }

  function getCachedUser() {
    try {
      var raw = window.localStorage.getItem(USER_CACHE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function isAuthenticated() {
    return !!getToken();
  }

  // ---------------------------------------------------------------------------
  // Wrapper fetch + gestion d'erreurs uniforme
  // ---------------------------------------------------------------------------
  function buildUrl(path) {
    if (/^https?:\/\//i.test(path)) return path;
    var base = config.baseUrl || "";
    // path commence par "/" → on l'utilise tel quel (chemin absolu sur l'origine)
    return base.replace(/\/$/, "") + path;
  }

  /**
   * Effectue une requête et renvoie toujours { ok, data, error, status }.
   * @param {string} path  ex: "/api/v1/auth/login"
   * @param {object} opts  { method, body, auth(bool, default true), headers, raw(bool) }
   */
  function request(path, opts) {
    opts = opts || {};
    var method = opts.method || "GET";
    var useAuth = opts.auth !== false; // auth par défaut
    var headers = Object.assign({ Accept: "application/json" }, opts.headers || {});
    var fetchOpts = { method: method, headers: headers };

    if (opts.body !== undefined && opts.body !== null) {
      headers["Content-Type"] = "application/json";
      fetchOpts.body =
        typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body);
    }

    if (useAuth) {
      var token = getToken();
      if (token) headers["Authorization"] = "Bearer " + token;
    }

    return fetch(buildUrl(path), fetchOpts)
      .then(function (res) {
        var status = res.status;

        // Réponse binaire / fichier (ex: export CSV)
        if (opts.raw) {
          return res.blob().then(function (blob) {
            return { ok: res.ok, data: blob, error: res.ok ? null : "HTTP " + status, status: status };
          });
        }

        var ct = res.headers.get("content-type") || "";
        var parse = ct.indexOf("application/json") !== -1 ? res.json() : res.text();

        return parse.then(function (payload) {
          if (res.ok) {
            return { ok: true, data: payload, error: null, status: status };
          }
          var detail =
            payload && typeof payload === "object" && payload.detail
              ? payload.detail
              : payload || "HTTP " + status;
          return { ok: false, data: null, error: detail, status: status };
        });
      })
      .catch(function (err) {
        return { ok: false, data: null, error: (err && err.message) || "Network error", status: 0 };
      });
  }

  // True si la réponse signale un endpoint inexistant (→ on bascule sur le mock)
  function endpointMissing(res) {
    return res && [404, 405, 501].indexOf(res.status) !== -1;
  }

  // ---------------------------------------------------------------------------
  // AUTH CLIENT (endpoints réels)
  // ---------------------------------------------------------------------------

  // POST /api/v1/auth/register {name,email,password} -> {access_token}
  function register(name, email, password) {
    return request("/api/v1/auth/register", {
      method: "POST",
      auth: false,
      body: { name: name, email: email, password: password },
    }).then(function (res) {
      if (res.ok && res.data && res.data.access_token) setToken(res.data.access_token);
      return res;
    });
  }

  // POST /api/v1/auth/login {email,password} -> {access_token}
  function login(email, password) {
    return request("/api/v1/auth/login", {
      method: "POST",
      auth: false,
      body: { email: email, password: password },
    }).then(function (res) {
      if (res.ok && res.data && res.data.access_token) setToken(res.data.access_token);
      return res;
    });
  }

  function logout() {
    setToken(null);
    setCachedUser(null);
    return { ok: true, data: null, error: null, status: 0 };
  }

  // GET /api/v1/auth/me -> {id,email,name,plan,is_active,created_at}
  function getProfile() {
    return request("/api/v1/auth/me", { method: "GET" }).then(function (res) {
      if (res.ok) setCachedUser(res.data);
      return res;
    });
  }

  // ---------------------------------------------------------------------------
  // CLÉS API (endpoints réels)
  // ---------------------------------------------------------------------------

  // GET /api/v1/keys/ -> [KeySummary]
  function listKeys() {
    return request("/api/v1/keys/", { method: "GET" });
  }

  // POST /api/v1/keys/ {label?,quota,expires_at?} -> CreateKeyResponse (full_key UNE fois)
  function createKey(opts) {
    opts = opts || {};
    var body = { quota: opts.quota != null ? opts.quota : 1000 };
    if (opts.label != null) body.label = opts.label;
    if (opts.expires_at != null) body.expires_at = opts.expires_at;
    return request("/api/v1/keys/", { method: "POST", body: body });
  }

  // DELETE /api/v1/keys/{id} -> 204 (soft-delete = revoke)
  function revokeKey(keyId) {
    return request("/api/v1/keys/" + encodeURIComponent(keyId), { method: "DELETE" });
  }

  // Alias explicite : "revoke" et "delete" pointent sur le même endpoint.
  function deleteKey(keyId) {
    return revokeKey(keyId);
  }

  // POST /api/v1/keys/{id}/rotate -> CreateKeyResponse
  function rotateKey(keyId) {
    return request("/api/v1/keys/" + encodeURIComponent(keyId) + "/rotate", {
      method: "POST",
    });
  }

  // ---------------------------------------------------------------------------
  // USAGE (endpoints réels)
  // ---------------------------------------------------------------------------

  // GET /api/v1/usage/ -> UsageSummary
  function getUsage() {
    return request("/api/v1/usage/", { method: "GET" });
  }

  // GET /api/v1/usage/logs?page&limit&start_date&end_date -> PaginatedLogs
  function getUsageLogs(params) {
    params = params || {};
    var q = [];
    if (params.page != null) q.push("page=" + params.page);
    if (params.limit != null) q.push("limit=" + params.limit);
    if (params.start_date) q.push("start_date=" + encodeURIComponent(params.start_date));
    if (params.end_date) q.push("end_date=" + encodeURIComponent(params.end_date));
    var qs = q.length ? "?" + q.join("&") : "";
    return request("/api/v1/usage/logs" + qs, { method: "GET" });
  }

  // GET /api/v1/usage/export -> CSV blob
  function exportUsage(params) {
    params = params || {};
    var q = [];
    if (params.start_date) q.push("start_date=" + encodeURIComponent(params.start_date));
    if (params.end_date) q.push("end_date=" + encodeURIComponent(params.end_date));
    var qs = q.length ? "?" + q.join("&") : "";
    return request("/api/v1/usage/export" + qs, { method: "GET", raw: true });
  }

  // ---------------------------------------------------------------------------
  // PROFIL / COMPTE — endpoints À CRÉER (mock fallback)
  // ---------------------------------------------------------------------------

  // PATCH /api/v1/auth/me {name?,email?} -> ClientResponse
  function updateProfile(patch) {
    return request("/api/v1/auth/me", { method: "PATCH", body: patch }).then(function (res) {
      if (res.ok) setCachedUser(res.data);
      return res;
    });
  }

  // POST /api/v1/auth/me/password {current_password,new_password} -> 204
  function changePassword(currentPassword, newPassword) {
    return request("/api/v1/auth/me/password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    });
  }

  // DELETE /api/v1/auth/me -> 204
  function deleteAccount() {
    return request("/api/v1/auth/me", { method: "DELETE" }).then(function (res) {
      if (res.ok) logout();
      return res;
    });
  }

  // ---------------------------------------------------------------------------
  // ABONNEMENTS / PLANS / FACTURATION — endpoints À CRÉER (mock fallback)
  // ---------------------------------------------------------------------------

  var MOCK_PLANS = [
    { id: "free", name: "Free", price_eur: 0, period: "mois", quota: 100, features: ["100 requêtes/mois", "Support communautaire"] },
    { id: "starter", name: "Starter", price_eur: 29, period: "mois", quota: 1000, features: ["1 000 requêtes/mois", "Support email"] },
    { id: "pro", name: "Pro", price_eur: 99, period: "mois", quota: 10000, features: ["10 000 requêtes/mois", "Support prioritaire", "Webhooks"] },
    { id: "enterprise", name: "Enterprise", price_eur: null, period: "mois", quota: 100000, features: ["100 000+ requêtes", "SLA dédié", "Support 24/7"] },
  ];

  // GET /api/v1/plans -> [Plan]
  function getPlans() {
    return request("/api/v1/plans", { method: "GET", auth: false }).then(function (res) {
      if (endpointMissing(res)) {
        return { ok: true, data: MOCK_PLANS, error: null, status: 200, _mock: true };
      }
      return res;
    });
  }

  // GET /api/v1/subscription -> {plan,status,quota_total,quota_used,...}
  function getSubscription() {
    return request("/api/v1/subscription", { method: "GET" });
  }

  // POST /api/v1/subscription/change {plan} -> {ok,plan,message}
  function requestPlanChange(plan) {
    return request("/api/v1/subscription/change", { method: "POST", body: { plan: plan } });
  }

  // GET /api/v1/billing/invoices -> [Invoice]  (pas encore implémenté côté backend)
  function getInvoices() {
    return request("/api/v1/billing/invoices", { method: "GET" }).then(function (res) {
      if (endpointMissing(res)) {
        return { ok: true, data: [], error: null, status: 200, _mock: true };
      }
      return res;
    });
  }

  // POST /api/v1/auth/forgot-password {email} -> {message}
  function requestPasswordReset(email) {
    return request("/api/v1/auth/forgot-password", {
      method: "POST",
      auth: false,
      body: { email: email },
    });
  }

  // POST /api/v1/auth/reset-password {token,new_password} -> 200/204
  // Applique le nouveau mot de passe à partir du token reçu par e-mail.
  function resetPassword(token, newPassword) {
    return request("/api/v1/auth/reset-password", {
      method: "POST",
      auth: false,
      body: { token: token, new_password: newPassword },
    });
  }

  // ---------------------------------------------------------------------------
  // API publique du module
  // ---------------------------------------------------------------------------
  var MiraAPI = {
    // config
    configure: function (opts) {
      if (opts && typeof opts.baseUrl === "string") config.baseUrl = opts.baseUrl;
      return config;
    },
    getConfig: function () {
      return { baseUrl: config.baseUrl, tokenKey: TOKEN_STORAGE_KEY };
    },

    // token / session
    getToken: getToken,
    setToken: setToken,
    isAuthenticated: isAuthenticated,
    getCachedUser: getCachedUser,

    // auth (réels)
    register: register,
    login: login,
    logout: logout,
    getProfile: getProfile,
    requestPasswordReset: requestPasswordReset,
    resetPassword: resetPassword,

    // clés API (réels)
    listKeys: listKeys,
    createKey: createKey,
    revokeKey: revokeKey,
    deleteKey: deleteKey,
    rotateKey: rotateKey,

    // usage (réels)
    getUsage: getUsage,
    getUsageLogs: getUsageLogs,
    exportUsage: exportUsage,

    // compte (à créer côté backend — mock fallback)
    updateProfile: updateProfile,
    changePassword: changePassword,
    deleteAccount: deleteAccount,

    // abonnements / facturation (à créer côté backend — mock fallback)
    getPlans: getPlans,
    getSubscription: getSubscription,
    requestPlanChange: requestPlanChange,
    getInvoices: getInvoices,

    // bas niveau (échappatoire)
    request: request,
  };

  window.MiraAPI = MiraAPI;
})(window);
