/**
 * AI_POD Client Tracking, Recommendation & Similar Products SDK (sdk.js)
 * PERSISTENCE MECHANISM: localStorage (Primary) + First-Party Cookie (Fallback)
 * WHY localStorage IS PRIMARY: 1. Zero HTTP Header Overhead 2. Size & Longevity 3. Domain & SameSite Resilience 4. Apple Safari ITP Durability
 * WHY FIRST-PARTY COOKIE IS FALLBACK: Sandboxed iframes / security restrictions fallback to document.cookie.
 * RESILIENCE: Protected in try/catch. Never throws into host page.
 */
(function(window, document) {
  'use strict';
  try {
    var cur = document.currentScript || document.querySelector('script[data-tenant-key]');
    if (!cur) {
      var all = document.getElementsByTagName('script');
      for (var i = all.length - 1; i >= 0; i--) {
        if (all[i].src && all[i].src.indexOf('sdk.js') !== -1) { cur = all[i]; break; }
      }
    }
    var tenantKey = cur ? (cur.getAttribute('data-tenant-key') || (cur.dataset && cur.dataset.tenantKey) || '') : '';
    var scriptCurr = (cur && (cur.getAttribute('data-currency') || (cur.dataset && cur.dataset.currency))) || 'LKR';
    var scriptLoc = (cur && (cur.getAttribute('data-locale') || (cur.dataset && cur.dataset.locale))) || 'en-LK';
    var baseUrl = '';
    if (cur && cur.src) {
      try { baseUrl = new URL(cur.src).origin; } catch(e) {}
    }
    if (!baseUrl && typeof window !== 'undefined' && window.location) baseUrl = window.location.origin;
    if (cur && cur.getAttribute('data-api-base')) baseUrl = cur.getAttribute('data-api-base').replace(/\/+$/, '');

    function escapeHtml(s) {
      return (s === null || s === undefined) ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }
    function sanitizeUrl(u) {
      if (!u || typeof u !== 'string') return '';
      var tr = u.trim();
      return /^(javascript:|data:|vbscript:)/i.test(tr) ? '' : tr;
    }
    function formatPrice(val, curr, loc) {
      if (val === null || val === undefined || isNaN(Number(val))) return '';
      var n = Number(val);
      try { return new Intl.NumberFormat(loc || scriptLoc, { style: 'currency', currency: curr || scriptCurr, maximumFractionDigits: 0 }).format(n); }
      catch(e) { return (curr || scriptCurr) + ' ' + Math.round(n); }
    }
    function renderPriceDiff(d) {
      if (d === null || d === undefined) return '';
      var n = Number(d);
      if (n < 0) return '<span class="aipod-sim-diff aipod-sim-cheaper">-' + formatPrice(Math.abs(n)) + '</span>';
      if (n > 0) return '<span class="aipod-sim-diff aipod-sim-pricier">+' + formatPrice(n) + '</span>';
      return '<span class="aipod-sim-diff aipod-sim-same">Same price</span>';
    }
    function renderImg(u, h) {
      var s = sanitizeUrl(u);
      return s ? '<img src="' + s + '" class="aipod-sim-img" style="max-height:' + (h || 130) + 'px;max-width:100%;object-fit:contain" alt="" loading="lazy">' : '<span style="font-size:2rem;opacity:.3;">📱</span>';
    }
    function apiFetch(p) {
      return fetch((baseUrl ? baseUrl : '') + p, { headers: { 'X-API-Key': tenantKey } }).then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
    }

    var memStore = {};
    function getStore(k) {
      try { if (window.localStorage) { var v = window.localStorage.getItem(k); if (v) return v; } } catch(e) {}
      try {
        var m = (document.cookie || '').split(';');
        for (var i = 0; i < m.length; i++) {
          var p = m[i].trim();
          if (p.indexOf(encodeURIComponent(k) + '=') === 0) return decodeURIComponent(p.slice(k.length + 1));
        }
      } catch(e) {}
      return memStore[k] || null;
    }
    function setStore(k, v) {
      if (!v) return;
      memStore[k] = v;
      try { if (window.localStorage) window.localStorage.setItem(k, v); } catch(e) {}
      try { document.cookie = encodeURIComponent(k) + '=' + encodeURIComponent(v) + '; path=/; max-age=31536000; SameSite=Lax'; } catch(e) {}
    }
    function removeStore(k) {
      delete memStore[k];
      try { if (window.localStorage) window.localStorage.removeItem(k); } catch(e) {}
      try { document.cookie = encodeURIComponent(k) + '=; path=/; max-age=0; SameSite=Lax'; } catch(e) {}
    }
    function genSession() {
      try { if (window.crypto && window.crypto.randomUUID) return 'sess_' + window.crypto.randomUUID().replace(/-/g, '').slice(0, 16); } catch(e) {}
      return 'sess_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    }

    var SESS_KEY = 'aipod_session_id', CUST_KEY = 'aipod_customer_id';
    var sessId = getStore(SESS_KEY);
    if (!sessId) { sessId = genSession(); setStore(SESS_KEY, sessId); }

    function injectCss() {
      if (document.getElementById('aipod-sdk-css')) return;
      var el = document.createElement('style');
      el.id = 'aipod-sdk-css';
      el.textContent =
        '.aipod-widget-root,.aipod-sim-root{font-family:system-ui,-apple-system,sans-serif;width:100%;margin:14px 0}' +
        '.aipod-widget-root *,.aipod-sim-root *{box-sizing:border-box}' +
        '.aipod-widget-title,.aipod-sim-title{font-size:1.1rem;font-weight:700;margin-bottom:12px}' +
        '.aipod-widget-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}' +
        '.aipod-sim-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}' +
        '@media(max-width:640px){.aipod-sim-grid{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;gap:12px;padding-bottom:10px}.aipod-sim-card{scroll-snap-align:start;flex:0 0 78%;max-width:280px}}' +
        '.aipod-product-card,.aipod-sim-card{border:1px solid #e2e8f0;border-radius:10px;padding:12px;background:#fff;display:flex;flex-direction:column;cursor:pointer}' +
        '.aipod-product-card:hover,.aipod-sim-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(0,51,153,.08);border-color:#003399}' +
        '.aipod-card-badge{font-size:.68rem;font-weight:700;color:#003399;background:rgba(0,51,153,.1);padding:2px 6px;border-radius:4px;margin-bottom:6px;align-self:flex-start}' +
        '.aipod-card-name,.aipod-sim-name{font-size:.9rem;font-weight:600;line-height:1.3;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}' +
        '.aipod-card-cat{font-size:.75rem;opacity:.7;margin-bottom:8px}' +
        '.aipod-card-id{font-size:.68rem;opacity:.5;font-family:monospace;margin-top:auto}' +
        '.aipod-widget-empty{font-size:.85rem;opacity:.6;padding:16px 0}' +
        '.aipod-sim-img-wrap{width:100%;height:130px;border-radius:8px;background:#f8fafc;display:flex;align-items:center;justify-content:center;margin-bottom:8px}' +
        '.aipod-sim-img{max-width:100%;max-height:100%;object-fit:contain}' +
        '.aipod-sim-brand,.aipod-sim-sub{font-size:.72rem;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:2px}' +
        '.aipod-sim-pricing{display:flex;align-items:center;gap:8px;margin-top:auto;padding-top:6px;flex-wrap:wrap}' +
        '.aipod-sim-price{font-size:1rem;font-weight:700;color:#003399}' +
        '.aipod-sim-diff{font-size:.72rem;font-weight:600;padding:2px 6px;border-radius:4px}' +
        '.aipod-sim-cheaper{background:#dcfce7;color:#15803d}.aipod-sim-pricier{background:#fee2e2;color:#b91c1c}.aipod-sim-same{background:#f1f5f9;color:#475569}' +
        '.aipod-sim-chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}' +
        '.aipod-sim-chip{font-size:.68rem;background:#eff6ff;color:#1d4ed8;padding:2px 6px;border-radius:999px}' +
        '.aipod-sim-compare-wrap{width:100%;overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;background:#fff;margin:16px 0}' +
        '.aipod-sim-compare-table{width:100%;border-collapse:collapse;font-size:.85rem;text-align:left}' +
        '.aipod-sim-compare-table th,.aipod-sim-compare-table td{padding:10px 12px;border-bottom:1px solid #f1f5f9;border-right:1px solid #f1f5f9;vertical-align:top}' +
        '.aipod-sim-sticky-col{position:sticky;left:0;background:#fff;z-index:2;border-right:2px solid #cbd5e1!important}' +
        '.aipod-sim-target-header{background:#f8fafc;font-weight:700;color:#003399}' +
        '.aipod-sim-best{background:rgba(16,185,129,.15);color:#047857;font-weight:700;border-radius:4px;padding:2px 6px;display:inline-block}';
      document.head.appendChild(el);
    }

    function getSpecDirection(k) {
      if (!k) return null;
      var s = String(k).toLowerCase();
      return /ram|battery|camera|storage|rom|cores?|mah|mp|hz/i.test(s) ? 'high' : (/price|weight/i.test(s) ? 'low' : null);
    }
    function extractNum(v) {
      if (v === null || v === undefined) return null;
      if (typeof v === 'number') return isNaN(v) ? null : v;
      var m = String(v).match(/[-+]?[0-9]*\.?[0-9]+/);
      return m ? parseFloat(m[0]) : null;
    }

    var AIPod = {
      version: '1.2.0',
      escape: escapeHtml,
      sanitizeUrl: sanitizeUrl,
      formatPrice: formatPrice,
      getTenantKey: function() { return tenantKey; },
      getSessionId: function() { return getStore(SESS_KEY) || sessId; },
      getCustomerId: function() { return getStore(CUST_KEY); },
      getBaseUrl: function() { return baseUrl; },
      init: function(c) {
        if (c && typeof c === 'object') {
          if (c.apiKey || c.tenantKey) tenantKey = String(c.apiKey || c.tenantKey).trim();
          if (c.baseUrl || c.apiBase) baseUrl = String(c.baseUrl || c.apiBase).replace(/\/+$/, '');
          if (c.currency) scriptCurr = String(c.currency).trim();
          if (c.locale) scriptLoc = String(c.locale).trim();
          if (c.sessionId) { sessId = String(c.sessionId).trim(); setStore(SESS_KEY, sessId); }
        }
        return this;
      },
      identify: function(cid) {
        if (cid !== null && cid !== undefined) {
          var c = String(cid).trim();
          if (c) setStore(CUST_KEY, c);
        }
        return this;
      },
      track: function(eventType, productId, options) {
        return new Promise(function(resolve) {
          try {
            if (!tenantKey) return resolve({ status: 'error', detail: 'Missing tenant public key' });
            options = options || {};
            var pId = String(productId || '').trim();
            if (!pId) return resolve({ status: 'error', detail: 'productId is required' });
            var payload = {
              event_type: String(eventType || 'view').trim(),
              product_id: pId,
              session_id: options.sessionId || AIPod.getSessionId(),
              customer_id: options.customerId || AIPod.getCustomerId(),
              quantity: (typeof options.quantity === 'number') ? options.quantity : (Number(options.quantity) || 1),
              timestamp: new Date().toISOString()
            };
            if (options.source) payload.source = String(options.source).trim();
            if (options.rec_id || options.recId) payload.rec_id = String(options.rec_id || options.recId).trim();
            var json = JSON.stringify(payload);
            var u = (baseUrl ? baseUrl : '') + '/v1/track';
            if (options.useBeacon && navigator && navigator.sendBeacon) {
              try { if (navigator.sendBeacon(u, new Blob([json], { type: 'application/json' }))) return resolve({ status: 'accepted', beacon: true }); } catch(b) {}
            }
            fetch(u, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'X-API-Key': tenantKey },
              body: json,
              keepalive: Boolean(options.keepalive || payload.event_type === 'click')
            }).then(function(r) { return r.json().catch(function() { return { status: r.ok ? 'accepted' : 'error' }; }); })
              .then(resolve)
              .catch(function(err) { resolve({ status: 'network_failed', error: err ? err.message : 'Network error' }); });
          } catch(e) {
            resolve({ status: 'client_error', error: e ? e.message : 'Unknown error' });
          }
        });
      },
      trackSimilarClick: function(item, recId) {
        var pid = (item && typeof item === 'object') ? (item.product_id || item.id) : item;
        return AIPod.track('click', pid, { source: 'similar', rec_id: recId || (item && item.rec_id), keepalive: true });
      },
      getRecommendations: function(customerId, options) {
        options = options || {};
        var target = customerId ? String(customerId).trim() : (AIPod.getCustomerId() || 'guest');
        return apiFetch('/v1/recommendations?customer_id=' + encodeURIComponent(target) + '&top_n=' + encodeURIComponent(options.topN || options.top_n || 5))
          .then(function(json) {
            var list = (json && Array.isArray(json.recommendations)) ? json.recommendations : [];
            list.fallback = Boolean(json && json.fallback);
            list.rec_id = (json && json.rec_id) || null;
            list.forEach(function(it) { if (it && typeof it === 'object') it.rec_id = list.rec_id; });
            return list;
          }).catch(function() { return []; });
      },
      renderWidget: function(containerId, products, options) {
        try {
          var container = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
          if (!container) return null;
          options = options || {};
          injectCss();
          function render(items) {
            try {
              container.innerHTML = '';
              var root = document.createElement('div');
              root.className = 'aipod-widget-root';
              if (options.title) root.innerHTML = '<div class="aipod-widget-title">' + escapeHtml(options.title) + '</div>';
              if (!items || !items.length) {
                if (options.emptyMessage) root.innerHTML += '<div class="aipod-widget-empty">' + escapeHtml(options.emptyMessage) + '</div>';
                container.appendChild(root);
                return;
              }
              var grid = document.createElement('div');
              grid.className = 'aipod-widget-grid';
              grid.innerHTML = items.map(function(prod, idx) {
                if (!prod) return '';
                var pid = prod.product_id || (typeof prod === 'string' ? prod : '');
                return '<div class="aipod-product-card" data-sim-idx="' + idx + '">' +
                  '<span class="aipod-card-badge">#' + (prod.rank || idx + 1) + '</span>' +
                  '<div class="aipod-card-name">' + escapeHtml(prod.product_name || prod.title || prod.name || pid) + '</div>' +
                  (prod.category ? '<div class="aipod-card-cat">' + escapeHtml(prod.category) + '</div>' : '') +
                  '<div class="aipod-card-id">ID: ' + escapeHtml(pid) + '</div>' +
                '</div>';
              }).join('');
              grid.addEventListener('click', function(e) {
                var card = e.target.closest('[data-sim-idx]');
                if (!card) return;
                var prod = items[Number(card.getAttribute('data-sim-idx'))];
                if (!prod) return;
                var pid = prod.product_id || (typeof prod === 'string' ? prod : '');
                if (options.trackClicks !== false) {
                  AIPod.track('click', pid, { source: 'recommendation', rec_id: prod.rec_id || (items ? items.rec_id : null), keepalive: true });
                }
                if (typeof options.onProductClick === 'function') options.onProductClick(prod, e);
              });
              root.appendChild(grid);
              container.appendChild(root);
            } catch(e) {}
          }
          if (products && typeof products.then === 'function') products.then(render).catch(function() { render([]); });
          else render(products);
          return container;
        } catch(e) { return null; }
      },
      getSimilar: function(p) {
        p = p || {};
        var pid = p.product_id || p.productId || '';
        var cId = p.containerId || p.container;
        if (!tenantKey || !pid) {
          if (p.onError) p.onError(new Error(tenantKey ? 'product_id required' : 'API key missing'));
          return Promise.resolve({ product_id: pid, similar_products: [], total: 0 });
        }
        return apiFetch('/v1/recommendations/similar/' + encodeURIComponent(pid) + '?top_n=' + encodeURIComponent(p.top_n || p.topN || 5) + '&same_category=' + Boolean(p.same_category))
          .then(function(d) {
            if (cId) AIPod._renderSimilarCards(cId, d, p);
            if (p.onRender) p.onRender(d);
            return d;
          }).catch(function(err) {
            if (p.onError) p.onError(err);
            return { product_id: pid, similar_products: [], total: 0 };
          });
      },
      _renderSimilarCards: function(cId, data, opts) {
        try {
          var container = typeof cId === 'string' ? document.getElementById(cId) : cId;
          if (!container) return;
          injectCss();
          opts = opts || {};
          var items = (data && data.similar_products) || [];
          var recId = data ? data.rec_id : null;
          container.innerHTML = '';
          var root = document.createElement('div');
          root.className = 'aipod-sim-root';
          if (opts.title) root.innerHTML = '<div class="aipod-sim-title">' + escapeHtml(opts.title) + '</div>';
          if (!items.length) {
            if (opts.emptyMessage) root.innerHTML += '<div class="aipod-widget-empty">' + escapeHtml(opts.emptyMessage) + '</div>';
            container.appendChild(root);
            return;
          }
          var grid = document.createElement('div');
          grid.className = 'aipod-sim-grid';
          grid.innerHTML = items.map(function(it, idx) {
            if (!it) return '';
            if (typeof opts.template === 'function') return '<div data-sim-idx="' + idx + '">' + opts.template(it, recId) + '</div>';
            var chips = '';
            var rs = it.reasons || [];
            if (rs.length) {
              chips = rs.slice(0, 3).map(function(r) { return '<span class="aipod-sim-chip">' + escapeHtml(r.replace(/_/g, ' ')) + '</span>'; }).join('');
            } else if (it.specs) {
              chips = Object.keys(it.specs).slice(0, 2).map(function(k) { return '<span class="aipod-sim-chip">' + escapeHtml(k + ': ' + it.specs[k]) + '</span>'; }).join('');
            }
            return '<div class="aipod-sim-card" data-sim-idx="' + idx + '">' +
              '<div class="aipod-sim-img-wrap">' + renderImg(it.image_url, 130) + '</div>' +
              (it.brand ? '<div class="aipod-sim-brand">' + escapeHtml(it.brand) + '</div>' : '') +
              '<div class="aipod-sim-name">' + escapeHtml(it.product_name || it.product_id) + '</div>' +
              '<div class="aipod-sim-pricing">' +
                (it.price !== null && it.price !== undefined ? '<span class="aipod-sim-price">' + formatPrice(it.price) + '</span>' : '') +
                renderPriceDiff(it.price_diff) +
              '</div>' +
              (chips ? '<div class="aipod-sim-chips">' + chips + '</div>' : '') +
            '</div>';
          }).join('');
          grid.addEventListener('click', function(e) {
            var card = e.target.closest('[data-sim-idx]');
            if (!card) return;
            var it = items[Number(card.getAttribute('data-sim-idx'))];
            if (it) {
              AIPod.trackSimilarClick(it, recId);
              if (typeof opts.onProductClick === 'function') opts.onProductClick(it, e);
            }
          });
          root.appendChild(grid);
          container.appendChild(root);
        } catch(e) {}
      },
      compare: function(p) {
        p = p || {};
        var pid = p.product_id || p.productId || '';
        var cId = p.containerId || p.container;
        if (!pid || !cId) {
          if (p.onError) p.onError(new Error('product_id and containerId required'));
          return Promise.resolve(null);
        }
        return AIPod.getSimilar({ product_id: pid, top_n: p.max_items || p.maxItems || 3, same_category: p.same_category })
          .then(function(d) {
            if (!d || !d.target) {
              if (p.onError) p.onError(new Error('Target not found'));
              return null;
            }
            AIPod._renderCompareTable(cId, d, p);
            if (p.onRender) p.onRender(d);
            return d;
          }).catch(function(err) {
            if (p.onError) p.onError(err);
            return null;
          });
      },
      _renderCompareTable: function(cId, data, opts) {
        try {
          var container = typeof cId === 'string' ? document.getElementById(cId) : cId;
          if (!container) return;
          injectCss();
          var target = data.target, items = (data && data.similar_products) || [], recId = data.rec_id;
          container.innerHTML = '';
          var hHtml = '<tr><th class="aipod-sim-sticky-col aipod-sim-target-header">Specification</th><th class="aipod-sim-target-header"><div class="aipod-sim-sub" style="color:#003399">Current Model</div><strong>' + escapeHtml(target.product_name) + '</strong></th>' +
            items.map(function(it, idx) { return '<th><div class="aipod-sim-sub">Similar #' + (idx + 1) + '</div><strong>' + escapeHtml(it.product_name) + '</strong></th>'; }).join('') + '</tr>';
          function buildRow(label, tVal, sVals, dir, isPrice) {
            var vals = [tVal].concat(sVals), bestIdx = -1;
            if (dir) {
              var nums = vals.map(extractNum), valid = nums.filter(function(n) { return n !== null; });
              if (valid.length > 1) {
                var minV = Math.min.apply(null, valid), maxV = Math.max.apply(null, valid);
                if (minV !== maxV) bestIdx = nums.indexOf(dir === 'high' ? maxV : minV);
              }
            }
            function cell(v, idx, isTarget) {
              var txt = isPrice ? formatPrice(v) : (v !== null && v !== undefined ? String(v) : '-');
              var c = (bestIdx === idx) ? '<span class="aipod-sim-best">' + escapeHtml(txt) + '</span>' : escapeHtml(txt);
              if (isPrice && !isTarget && items[idx - 1].price_diff !== null && items[idx - 1].price_diff !== undefined) {
                c += ' ' + renderPriceDiff(items[idx - 1].price_diff);
              }
              return isTarget ? '<td style="background:#fcfdfe">' + c + '</td>' : '<td style="cursor:pointer" data-sim-idx="' + (idx - 1) + '">' + c + '</td>';
            }
            return '<tr><td class="aipod-sim-sticky-col"><strong>' + escapeHtml(label) + '</strong></td>' +
              cell(tVal, 0, true) +
              sVals.map(function(v, i) { return cell(v, i + 1, false); }).join('') + '</tr>';
          }
          var bRows = '<tr><td class="aipod-sim-sticky-col"><strong>Preview</strong></td><td>' + renderImg(target.image_url, 80) + '</td>' +
            items.map(function(it, idx) { return '<td style="cursor:pointer" data-sim-idx="' + idx + '">' + renderImg(it.image_url, 80) + '</td>'; }).join('') + '</tr>' +
            buildRow('Brand', target.brand, items.map(function(it) { return it.brand; }), null, false) +
            buildRow('Price', target.price, items.map(function(it) { return it.price; }), 'low', true);
          var specKeys = {}, tSpecs = (target.specs && typeof target.specs === 'object') ? target.specs : {};
          for (var k in tSpecs) specKeys[k] = 1;
          for (var j = 0; j < items.length; j++) {
            var sp = items[j].specs;
            if (sp && typeof sp === 'object') for (var sk in sp) specKeys[sk] = 1;
          }
          for (var sk in specKeys) {
            var dir = getSpecDirection(sk);
            var tVal = tSpecs[sk] !== undefined ? tSpecs[sk] : null;
            var sVals = items.map(function(it) {
              var s = it.specs;
              return (s && s[sk] !== undefined) ? s[sk] : null;
            });
            bRows += buildRow(sk.replace(/_/g, ' '), tVal, sVals, dir, false);
          }
          var wrap = document.createElement('div');
          wrap.className = 'aipod-sim-compare-wrap';
          wrap.innerHTML = '<table class="aipod-sim-compare-table"><thead>' + hHtml + '</thead><tbody>' + bRows + '</tbody></table>';
          wrap.addEventListener('click', function(e) {
            var td = e.target.closest('[data-sim-idx]');
            if (td) {
              var it = items[Number(td.getAttribute('data-sim-idx'))];
              if (it) AIPod.trackSimilarClick(it, recId);
            }
          });
          container.appendChild(wrap);
        } catch(e) {}
      },
      reset: function() {
        try {
          removeStore(CUST_KEY);
          sessId = genSession();
          setStore(SESS_KEY, sessId);
        } catch(e) {}
        return this;
      }
    };
    window.AIPod = AIPod;
    window.aipod = AIPod;
    if (window.aipod_queue && Array.isArray(window.aipod_queue)) {
      try {
        var q = window.aipod_queue;
        window.aipod_queue = [];
        q.forEach(function(cmd) {
          if (Array.isArray(cmd) && cmd.length && typeof AIPod[cmd[0]] === 'function') {
            AIPod[cmd[0]].apply(AIPod, cmd.slice(1));
          }
        });
      } catch(e) {}
    }
  } catch(gErr) {}
})(typeof window !== 'undefined' ? window : this, typeof document !== 'undefined' ? document : {});
