/**
 * AI_POD Client Tracking & Recommendation SDK (sdk.js)
 *
 * Lightweight, self-contained client-side snippet for e-commerce and web applications.
 *
 * Usage:
 *   <script src="https://your-engine.com/sdk.js" data-tenant-key="pk_live_xxxxx"></script>
 *
 * Architectural Design & Persistence Decision (Step 22):
 * --------------------------------------------------------
 * PERSISTENCE MECHANISM: localStorage (Primary) + First-Party Cookie (Fallback)
 *
 * WHY localStorage IS PRIMARY:
 * 1. Zero HTTP Header Overhead: Cookies are automatically appended to EVERY outgoing HTTP
 *    request made by the browser to the host domain (images, CSS, HTML, API calls). Placing
 *    tracking session identifiers in cookies adds unnecessary byte bloat to every asset download.
 *    localStorage is purely client-side and transmits data only when explicitly requested.
 * 2. Size & Longevity: Cookies are hard-capped at 4KB per cookie and 20-50 per domain.
 *    localStorage affords 5MB–10MB of reliable storage that does not expire upon browser closing.
 * 3. Domain & SameSite Resilience: Setting cookies across varying customer environments
 *    (e.g., www.store.com vs store.com vs checkout.store.com) frequently encounters SameSite,
 *    Domain attribute, and Secure context mismatch issues. localStorage is origin-scoped and deterministic.
 * 4. Apple Safari ITP Durability: Under Apple's Intelligent Tracking Prevention (ITP),
 *    client-set `document.cookie` values are capped to a 7-day or 24-hour lifetime. localStorage
 *    within the first-party application remains intact across browsing sessions.
 *
 * WHY FIRST-PARTY COOKIE IS FALLBACK:
 * - In restricted browsing modes or cross-domain sandboxed iframes where localStorage access
 *   throws a SecurityError or QuotaExceededError, the SDK seamlessly falls back to a first-party
 *   cookie ('aipod_session_id=...; path=/; max-age=31536000; SameSite=Lax') to ensure no visitor
 *   session is lost.
 * - An in-memory fallback is also maintained so tracking calls within the active page never fail.
 *
 * RESILIENCE & ZERO HOST CRASH GUARANTEE:
 * - Every public method, initialization step, and network fetch is wrapped in protective try/catch
 *   blocks. If the network is offline or the endpoint fails, the SDK fails silently without ever
 *   throwing an uncaught exception into the host application.
 */

(function (window, document) {
  'use strict';

  try {
    // -------------------------------------------------------------------------
    // 1. Script Discovery & Configuration Extraction
    // -------------------------------------------------------------------------
    var currentScript = document.currentScript;
    if (!currentScript) {
      var candidates = document.querySelectorAll('script[data-tenant-key]');
      if (candidates && candidates.length > 0) {
        currentScript = candidates[candidates.length - 1];
      } else {
        var allScripts = document.getElementsByTagName('script');
        for (var i = allScripts.length - 1; i >= 0; i--) {
          var s = allScripts[i];
          if (s.src && (s.src.indexOf('/sdk.js') !== -1 || s.src.indexOf('sdk.js') !== -1)) {
            currentScript = s;
            break;
          }
        }
      }
    }

    var tenantKey = currentScript
      ? (currentScript.getAttribute('data-tenant-key') || (currentScript.dataset ? currentScript.dataset.tenantKey : ''))
      : '';

    // Auto-resolve API base URL from script origin or current host
    var resolvedBaseUrl = '';
    if (currentScript && currentScript.src) {
      try {
        var parsedUrl = new URL(currentScript.src);
        resolvedBaseUrl = parsedUrl.origin;
      } catch (e) {
        resolvedBaseUrl = '';
      }
    }
    if (!resolvedBaseUrl && typeof window !== 'undefined' && window.location) {
      resolvedBaseUrl = window.location.origin;
    }
    // Allow custom override via data-api-base attribute
    if (currentScript) {
      var customBase = currentScript.getAttribute('data-api-base');
      if (customBase) {
        resolvedBaseUrl = customBase.replace(/\/+$/, '');
      }
    }

    // -------------------------------------------------------------------------
    // 2. Storage Helpers (localStorage -> Cookie -> Memory)
    // -------------------------------------------------------------------------
    var inMemoryStore = {};

    function getStorageItem(key) {
      // 1. Try localStorage
      try {
        if (window.localStorage) {
          var val = window.localStorage.getItem(key);
          if (val) return val;
        }
      } catch (e) {}

      // 2. Try Cookie
      try {
        var namePrefix = encodeURIComponent(key) + '=';
        var cookieStr = document.cookie || '';
        var parts = cookieStr.split(';');
        for (var idx = 0; idx < parts.length; idx++) {
          var trimmed = parts[idx].trim();
          if (trimmed.indexOf(namePrefix) === 0) {
            return decodeURIComponent(trimmed.substring(namePrefix.length));
          }
        }
      } catch (e) {}

      // 3. Fallback to in-memory store
      return inMemoryStore[key] || null;
    }

    function setStorageItem(key, value) {
      if (!value) return;
      inMemoryStore[key] = value;

      // 1. Persist to localStorage
      try {
        if (window.localStorage) {
          window.localStorage.setItem(key, value);
        }
      } catch (e) {}

      // 2. Persist to first-party cookie as fallback (1-year expiration)
      try {
        var maxAge = 365 * 24 * 60 * 60;
        document.cookie =
          encodeURIComponent(key) +
          '=' +
          encodeURIComponent(value) +
          '; path=/; max-age=' +
          maxAge +
          '; SameSite=Lax';
      } catch (e) {}
    }

    function removeStorageItem(key) {
      delete inMemoryStore[key];
      try {
        if (window.localStorage) {
          window.localStorage.removeItem(key);
        }
      } catch (e) {}
      try {
        document.cookie =
          encodeURIComponent(key) +
          '=; path=/; max-age=0; SameSite=Lax';
      } catch (e) {}
    }

    function generateSessionId() {
      // Use crypto.randomUUID if available, else high-entropy alphanumeric generator
      if (typeof window.crypto !== 'undefined' && typeof window.crypto.randomUUID === 'function') {
        try {
          return 'sess_' + window.crypto.randomUUID().replace(/-/g, '').substring(0, 16);
        } catch (e) {}
      }
      var rand = Math.random().toString(36).substring(2, 12);
      var time = Date.now().toString(36);
      return 'sess_' + rand + time;
    }

    // -------------------------------------------------------------------------
    // 3. Session & Identity Initialization
    // -------------------------------------------------------------------------
    var SESSION_KEY = 'aipod_session_id';
    var CUSTOMER_KEY = 'aipod_customer_id';

    var sessionId = getStorageItem(SESSION_KEY);
    if (!sessionId) {
      sessionId = generateSessionId();
      setStorageItem(SESSION_KEY, sessionId);
    }

    // -------------------------------------------------------------------------
    // 4. AIPod Global Interface Definition
    // -------------------------------------------------------------------------
    var AIPod = {
      version: '1.0.0',

      /**
       * Retrieve or override the active tenant public key.
       */
      getTenantKey: function () {
        return tenantKey;
      },

      /**
       * Retrieve the current persistent session ID.
       */
      getSessionId: function () {
        return getStorageItem(SESSION_KEY) || sessionId;
      },

      /**
       * Retrieve the identified customer ID if set, else null.
       */
      getCustomerId: function () {
        return getStorageItem(CUSTOMER_KEY) || null;
      },

      /**
       * Retrieve the configured API base URL.
       */
      getBaseUrl: function () {
        return resolvedBaseUrl;
      },

      /**
       * Programmatically reconfigure tenant key or API base URL.
       */
      init: function (config) {
        try {
          if (config && typeof config === 'object') {
            if (config.apiKey || config.tenantKey) {
              tenantKey = String(config.apiKey || config.tenantKey).trim();
            }
            if (config.baseUrl || config.apiBase) {
              resolvedBaseUrl = String(config.baseUrl || config.apiBase).replace(/\/+$/, '');
            }
            if (config.sessionId) {
              sessionId = String(config.sessionId).trim();
              setStorageItem(SESSION_KEY, sessionId);
            }
          }
        } catch (e) {}
        return this;
      },

      /**
       * Identify the active customer (e.g. upon user login, account creation, or checkout).
       * Stores customerId in local storage so subsequent track() calls automatically include it.
       *
       * @param {string|number} customerId - Unique customer identifier in host database.
       * @returns {object} AIPod instance for method chaining.
       */
      identify: function (customerId) {
        try {
          if (customerId === null || customerId === undefined) {
            return this;
          }
          var cleanId = String(customerId).trim();
          if (cleanId) {
            setStorageItem(CUSTOMER_KEY, cleanId);
          }
        } catch (e) {
          // Never throw uncaught exceptions into host page
        }
        return this;
      },

      /**
       * Ingest an interaction event into POST /v1/track.
       *
       * @param {string} eventType - Event action ('view', 'add_to_cart', 'purchase').
       * @param {string|number} productId - Unique product or service identifier.
       * @param {object} [options] - Optional metadata (quantity, customerId override, sessionId override).
       * @returns {Promise<object>} Resolves with response status or safe fallback object.
       */
      track: function (eventType, productId, options) {
        return new Promise(function (resolve) {
          try {
            if (!tenantKey) {
              console.warn('[AIPod] Missing data-tenant-key. Call AIPod.init({ apiKey: ... }) or add data-tenant-key to script tag.');
              return resolve({ status: 'error', detail: 'Missing tenant public key' });
            }

            options = options || {};
            var activeSession = options.sessionId || AIPod.getSessionId();
            var activeCustomer = options.customerId || AIPod.getCustomerId();

            var cleanType = String(eventType || 'view').trim();
            var cleanProduct = String(productId || '').trim();

            if (!cleanProduct) {
              return resolve({ status: 'error', detail: 'productId is required' });
            }

            var quantity = 1;
            if (typeof options.quantity === 'number') {
              quantity = options.quantity;
            } else if (options.quantity) {
              var parsedQ = Number(options.quantity);
              if (!isNaN(parsedQ)) quantity = parsedQ;
            }

            var payload = {
              event_type: cleanType,
              product_id: cleanProduct,
              session_id: activeSession,
              customer_id: activeCustomer || null,
              quantity: quantity,
              timestamp: new Date().toISOString(),
            };

            var url = (resolvedBaseUrl ? resolvedBaseUrl : '') + '/v1/track';

            fetch(url, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-API-Key': tenantKey,
              },
              body: JSON.stringify(payload),
            })
              .then(function (res) {
                return res.json().catch(function () {
                  return { status: res.ok ? 'accepted' : 'error' };
                });
              })
              .then(function (data) {
                resolve(data);
              })
              .catch(function (networkErr) {
                // Fail silently on network errors
                resolve({ status: 'network_failed', error: networkErr ? networkErr.message : 'Network error' });
              });
          } catch (e) {
            // Fail silently on runtime exceptions
            resolve({ status: 'client_error', error: e ? e.message : 'Unknown error' });
          }
        });
      },

      /**
       * Retrieve personalized recommendations for a customer via GET /v1/recommendations.
       *
       * @param {string|number} [customerId] - Customer to score (defaults to identified customer or 'guest').
       * @param {object} [options] - Options dictionary ({ topN: 5 }).
       * @returns {Promise<Array>} Promise resolving to list of recommended products.
       */
      getRecommendations: function (customerId, options) {
        return new Promise(function (resolve) {
          try {
            if (!tenantKey) {
              console.warn('[AIPod] Missing data-tenant-key. Cannot fetch recommendations.');
              return resolve([]);
            }

            options = options || {};
            var topN = options.topN || options.top_n || 5;

            var targetCustomer = customerId ? String(customerId).trim() : (AIPod.getCustomerId() || 'guest');
            if (!targetCustomer) targetCustomer = 'guest';

            var base = resolvedBaseUrl ? resolvedBaseUrl : '';
            var url =
              base +
              '/v1/recommendations?customer_id=' +
              encodeURIComponent(targetCustomer) +
              '&top_n=' +
              encodeURIComponent(topN);

            fetch(url, {
              method: 'GET',
              headers: {
                'X-API-Key': tenantKey,
              },
            })
              .then(function (res) {
                if (!res.ok) {
                  return [];
                }
                return res.json().then(function (json) {
                  if (json && Array.isArray(json.recommendations)) {
                    var list = json.recommendations;
                    // Attach fallback indicator as property on list for convenience
                    list.fallback = Boolean(json.fallback);
                    return list;
                  }
                  return [];
                });
              })
              .then(function (products) {
                resolve(products);
              })
              .catch(function (networkErr) {
                // Network failure: resolve to empty list, never throw
                resolve([]);
              });
          } catch (e) {
            // Exception: resolve to empty list, never throw
            resolve([]);
          }
        });
      },

      /**
       * Optional Helper: Render a simple, minimally-styled product recommendation card widget
       * into a given container element.
       *
       * Designed for companies who want immediate UI rendering without writing their own display code.
       * Fully optional: frontend teams can call AIPod.getRecommendations() directly and ignore this helper.
       *
       * @param {string|HTMLElement} containerId - Element ID string or DOM element reference.
       * @param {Array|Promise<Array>} products - Product list returned by getRecommendations() (or Promise).
       * @param {object} [options] - Optional display options ({ title, onProductClick, trackClicks, emptyMessage }).
       * @returns {HTMLElement|null} The container element, or null if failed.
       */
      renderWidget: function (containerId, products, options) {
        try {
          // Resolve container element
          var container = null;
          if (typeof containerId === 'string') {
            container = document.getElementById(containerId);
          } else if (containerId && containerId.nodeType === 1) {
            container = containerId;
          }

          if (!container) {
            console.warn('[AIPod] renderWidget: container element not found:', containerId);
            return null;
          }

          options = options || {};

          // Inject scoped styles once into document head
          var styleId = 'aipod-widget-injected-styles';
          if (!document.getElementById(styleId)) {
            var styleEl = document.createElement('style');
            styleEl.id = styleId;
            styleEl.textContent =
              '.aipod-widget-root { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-sizing: border-box; width: 100%; margin: 12px 0; }' +
              '.aipod-widget-root * { box-sizing: border-box; }' +
              '.aipod-widget-title { font-size: 1rem; font-weight: 600; margin-bottom: 10px; color: inherit; display: flex; align-items: center; justify-content: space-between; }' +
              '.aipod-widget-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }' +
              '.aipod-product-card { border: 1px solid rgba(128,128,128,0.22); border-radius: 8px; padding: 12px; background: rgba(128,128,128,0.04); display: flex; flex-direction: column; justify-content: space-between; cursor: pointer; transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease; text-decoration: none; color: inherit; min-height: 110px; }' +
              '.aipod-product-card:hover { transform: translateY(-2px); border-color: rgba(99,102,241,0.5); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }' +
              '.aipod-card-badge { display: inline-block; font-size: 0.68rem; font-weight: 700; color: #6366f1; background: rgba(99,102,241,0.12); padding: 2px 6px; border-radius: 4px; margin-bottom: 6px; align-self: flex-start; }' +
              '.aipod-card-name { font-size: 0.88rem; font-weight: 600; line-height: 1.3; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }' +
              '.aipod-card-cat { font-size: 0.75rem; opacity: 0.7; margin-bottom: 8px; }' +
              '.aipod-card-id { font-size: 0.68rem; opacity: 0.5; font-family: monospace; margin-top: auto; }' +
              '.aipod-widget-empty { font-size: 0.85rem; opacity: 0.6; padding: 16px 0; }';
            document.head.appendChild(styleEl);
          }

          function doRender(items) {
            try {
              container.innerHTML = '';

              var root = document.createElement('div');
              root.className = 'aipod-widget-root';

              // Optional Section Title
              if (options.title) {
                var titleEl = document.createElement('div');
                titleEl.className = 'aipod-widget-title';
                titleEl.textContent = String(options.title);
                root.appendChild(titleEl);
              }

              if (!items || !Array.isArray(items) || items.length === 0) {
                if (options.emptyMessage) {
                  var emptyEl = document.createElement('div');
                  emptyEl.className = 'aipod-widget-empty';
                  emptyEl.textContent = String(options.emptyMessage);
                  root.appendChild(emptyEl);
                }
                container.appendChild(root);
                return;
              }

              var grid = document.createElement('div');
              grid.className = 'aipod-widget-grid';

              for (var i = 0; i < items.length; i++) {
                (function (prod) {
                  if (!prod) return;
                  var pid = prod.product_id || (typeof prod === 'string' ? prod : '');
                  var pname = prod.product_name || prod.title || prod.name || pid;
                  var pcat = prod.category || prod.type || '';
                  var rank = prod.rank || (i + 1);

                  var card = document.createElement('div');
                  card.className = 'aipod-product-card';
                  card.setAttribute('data-product-id', pid);
                  card.setAttribute('role', 'button');
                  card.setAttribute('tabindex', '0');

                  var badge = document.createElement('span');
                  badge.className = 'aipod-card-badge';
                  badge.textContent = '#' + rank;
                  card.appendChild(badge);

                  var nameEl = document.createElement('div');
                  nameEl.className = 'aipod-card-name';
                  nameEl.textContent = pname;
                  card.appendChild(nameEl);

                  if (pcat) {
                    var catEl = document.createElement('div');
                    catEl.className = 'aipod-card-cat';
                    catEl.textContent = pcat;
                    card.appendChild(catEl);
                  }

                  var idEl = document.createElement('div');
                  idEl.className = 'aipod-card-id';
                  idEl.textContent = 'ID: ' + pid;
                  card.appendChild(idEl);

                  // Interactive click / touch behavior
                  card.addEventListener('click', function (evt) {
                    try {
                      // Auto-track view if enabled (default true)
                      if (options.trackClicks !== false) {
                        AIPod.track('view', pid);
                      }
                      if (typeof options.onProductClick === 'function') {
                        options.onProductClick(prod, evt);
                      }
                    } catch (e) {}
                  });

                  grid.appendChild(card);
                })(items[i]);
              }

              root.appendChild(grid);
              container.appendChild(root);
            } catch (err) {}
          }

          // Handle Promise if getRecommendations() Promise was passed directly
          if (products && typeof products.then === 'function') {
            products.then(function (resolvedItems) {
              doRender(resolvedItems);
            }).catch(function () {
              doRender([]);
            });
          } else {
            doRender(products);
          }

          return container;
        } catch (e) {
          // Fail silently and never throw into host page
          return null;
        }
      },

      /**
       * Reset identity and generate a fresh session ID (useful on logout).
       */
      reset: function () {
        try {
          removeStorageItem(CUSTOMER_KEY);
          sessionId = generateSessionId();
          setStorageItem(SESSION_KEY, sessionId);
        } catch (e) {}
        return this;
      },
    };

    // -------------------------------------------------------------------------
    // 5. Expose Global Object
    // -------------------------------------------------------------------------
    window.AIPod = AIPod;

    // Process any pre-queued calls if async snippet loader pattern was used
    if (window.aipod_queue && Array.isArray(window.aipod_queue)) {
      try {
        var queue = window.aipod_queue;
        window.aipod_queue = [];
        for (var qIdx = 0; qIdx < queue.length; qIdx++) {
          var item = queue[qIdx];
          if (Array.isArray(item) && item.length > 0) {
            var fnName = item[0];
            var fnArgs = item.slice(1);
            if (typeof AIPod[fnName] === 'function') {
              AIPod[fnName].apply(AIPod, fnArgs);
            }
          }
        }
      } catch (e) {}
    }
  } catch (globalErr) {
    // Fail silently: a broken snippet must never break the host website
  }
})(typeof window !== 'undefined' ? window : this, typeof document !== 'undefined' ? document : {});
