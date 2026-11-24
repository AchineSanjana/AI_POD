import { useState, useEffect } from 'react';
import { getSimilarProducts } from '../api/client';
import { Package, AlertCircle, CheckCircle2, Sliders, Layers } from 'lucide-react';

function isValidHttpUrl(string) {
  if (!string || typeof string !== 'string') return false;
  try {
    const url = new URL(string);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

function formatLKR(amount) {
  if (amount == null || isNaN(amount)) return '—';
  return `LKR ${Number(amount).toLocaleString('en-LK', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatPriceDiff(diff, pct) {
  if (diff == null || isNaN(diff)) return null;
  const num = Number(diff);
  if (Math.abs(num) < 0.01) return 'Same price';
  const sign = num > 0 ? '+' : '-';
  const absFormatted = Math.abs(num).toLocaleString('en-LK', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const pctStr = pct != null && !isNaN(pct) ? ` (${num > 0 ? '+' : ''}${Math.round(pct)}%)` : '';
  return `${sign}LKR ${absFormatted}${pctStr}`;
}

export default function SimilarResults({
  productId,
  pk = null,
  initialTopN = 4,
  initialSameCategory = true,
  showControls = true,
  onTopNChange,
  onSameCategoryChange,
}) {
  const [topN, setTopN] = useState(initialTopN);
  const [sameCategory, setSameCategory] = useState(initialSameCategory);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Keep internal topN / sameCategory in sync if props change
  useEffect(() => {
    setTopN(initialTopN);
  }, [initialTopN]);

  useEffect(() => {
    setSameCategory(initialSameCategory);
  }, [initialSameCategory]);

  useEffect(() => {
    if (!productId) {
      setData(null);
      setError('');
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError('');

    getSimilarProducts(productId, { topN, sameCategory }, pk)
      .then((res) => {
        if (isMounted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err?.message || 'Failed to fetch similar products');
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [productId, topN, sameCategory, pk]);

  const handleTopNSelect = (n) => {
    setTopN(n);
    if (onTopNChange) onTopNChange(n);
  };

  const handleSameCategoryToggle = (val) => {
    setSameCategory(val);
    if (onSameCategoryChange) onSameCategoryChange(val);
  };

  if (!productId) {
    return (
      <div style={{ textAlign: 'center', padding: '36px 16px', color: 'var(--text-muted)' }}>
        <Package size={32} style={{ opacity: 0.35, marginBottom: 12 }} />
        <p style={{ fontSize: 14, margin: 0 }}>Select an active product to preview similar recommendations.</p>
      </div>
    );
  }

  const items = data?.similar || data?.similar_products || [];
  const target = data?.target;
  const isFallback = Boolean(data?.fallback);
  const fallbackReason = data?.reason;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Controls */}
      {showControls && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12,
            background: 'var(--bg-surface)',
            padding: '10px 14px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Sliders size={14} color="var(--text-secondary)" />
            <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>Top N:</span>
            <div style={{ display: 'flex', gap: 4 }}>
              {[3, 4, 5, 6, 7, 8].map((n) => (
                <button
                  key={n}
                  type="button"
                  className={`btn btn-sm ${topN === n ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ padding: '2px 8px', fontSize: 12, minWidth: 28 }}
                  onClick={() => handleTopNSelect(n)}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 13,
              color: 'var(--text-primary)',
              cursor: 'pointer',
              userSelect: 'none',
            }}
          >
            <input
              type="checkbox"
              checked={sameCategory}
              onChange={(e) => handleSameCategoryToggle(e.target.checked)}
              style={{ width: 16, height: 16, cursor: 'pointer' }}
            />
            Limit to same category
          </label>
        </div>
      )}

      {/* Error alert */}
      {error && (
        <div className="alert alert-error" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Fallback Banner */}
      {isFallback && !loading && (
        <div
          style={{
            background: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            borderRadius: 'var(--radius-sm)',
            padding: '12px 16px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
          }}
        >
          <AlertCircle size={18} color="#f59e0b" style={{ flexShrink: 0, marginTop: 2 }} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#f59e0b' }}>
              Fallback Recommendations Active
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
              Showing popular products in this category (Reason: <code>{fallbackReason || 'popular_fallback'}</code>).
            </div>
          </div>
        </div>
      )}

      {/* Target product info */}
      {target && !loading && (
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            padding: '12px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: 14,
          }}
        >
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 8,
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
              flexShrink: 0,
            }}
          >
            {isValidHttpUrl(target.image_url) ? (
              <img
                src={target.image_url}
                alt=""
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                }}
              />
            ) : (
              <Package size={22} color="var(--text-muted)" />
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Target Product ({target.product_id})
            </div>
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                color: 'var(--text-primary)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {target.product_name}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
              {target.category && <span>{target.category}</span>}
              {target.brand && <span> • {target.brand}</span>}
              {target.price != null && <span> • <strong>{formatLKR(target.price)}</strong></span>}
            </div>
          </div>
        </div>
      )}

      {/* Loading Skeletons */}
      {loading && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 16 }}>
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card" style={{ padding: 16 }}>
              <div className="skeleton" style={{ height: 120, borderRadius: 8, marginBottom: 12 }} />
              <div className="skeleton" style={{ height: 16, width: '80%', marginBottom: 8 }} />
              <div className="skeleton" style={{ height: 14, width: '50%', marginBottom: 12 }} />
              <div className="skeleton" style={{ height: 24, width: '40%' }} />
            </div>
          ))}
        </div>
      )}

      {/* Results Cards Grid */}
      {!loading && !error && items.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
            gap: 16,
          }}
        >
          {items.map((item, idx) => {
            const priceDiffStr = formatPriceDiff(item.price_diff, item.price_diff_pct);
            const isDiffPositive = (item.price_diff || 0) > 0;
            const isDiffNegative = (item.price_diff || 0) < 0;

            return (
              <div
                key={item.product_id || idx}
                className="card aipod-sim-card"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  padding: 16,
                  position: 'relative',
                  border: '1px solid var(--border)',
                }}
              >
                {/* Header: Rank + Similarity */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                  <span className="badge badge-blue" style={{ fontSize: 11, padding: '2px 6px' }}>
                    #{item.rank || idx + 1}
                  </span>
                  {item.similarity != null && (
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: 'var(--accent-1)',
                        background: 'rgba(59, 130, 246, 0.1)',
                        padding: '2px 8px',
                        borderRadius: 10,
                      }}
                    >
                      {Math.round(item.similarity * 100)}% match
                    </span>
                  )}
                </div>

                {/* Product Image */}
                <div
                  style={{
                    width: '100%',
                    height: 120,
                    borderRadius: 6,
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: 12,
                    overflow: 'hidden',
                  }}
                >
                  {isValidHttpUrl(item.image_url) ? (
                    <img
                      src={item.image_url}
                      alt=""
                      style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                      onError={(e) => {
                        e.currentTarget.style.display = 'none';
                      }}
                    />
                  ) : (
                    <Package size={36} color="var(--text-muted)" style={{ opacity: 0.5 }} />
                  )}
                </div>

                {/* Name & Brand */}
                <div style={{ flex: 1 }}>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      lineHeight: 1.3,
                      marginBottom: 4,
                    }}
                  >
                    {item.product_name}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8 }}>
                    {item.brand && <span>{item.brand}</span>}
                    {item.brand && item.category && <span> • </span>}
                    {item.category && <span>{item.category}</span>}
                  </div>

                  {/* Price & Price Difference */}
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                    <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {formatLKR(item.price)}
                    </span>
                    {priceDiffStr && (
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 500,
                          color: isDiffPositive ? '#ef4444' : isDiffNegative ? '#10b981' : 'var(--text-muted)',
                        }}
                      >
                        {priceDiffStr}
                      </span>
                    )}
                  </div>

                  {/* Reasons Chips */}
                  {Array.isArray(item.reasons) && item.reasons.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                      {item.reasons.map((reason, rIdx) => (
                        <span
                          key={rIdx}
                          style={{
                            fontSize: 11,
                            padding: '2px 6px',
                            borderRadius: 4,
                            background: 'var(--bg-surface)',
                            color: 'var(--text-secondary)',
                            border: '1px solid var(--border)',
                          }}
                        >
                          {reason}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Specs */}
                  {item.specs && typeof item.specs === 'object' && Object.keys(item.specs).length > 0 && (
                    <div
                      style={{
                        fontSize: 11,
                        color: 'var(--text-muted)',
                        background: 'var(--bg-surface)',
                        padding: '6px 8px',
                        borderRadius: 4,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 2,
                        marginTop: 4,
                      }}
                    >
                      {Object.entries(item.specs).slice(0, 4).map(([k, v]) => (
                        <div key={k} style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span>{k}:</span>
                          <span style={{ fontWeight: 500, color: 'var(--text-secondary)' }}>{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Empty items */}
      {!loading && !error && items.length === 0 && (
        <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-muted)' }}>
          <Package size={28} style={{ opacity: 0.35, marginBottom: 8 }} />
          <p style={{ fontSize: 14, margin: 0 }}>No similar products found for this product.</p>
        </div>
      )}
    </div>
  );
}

