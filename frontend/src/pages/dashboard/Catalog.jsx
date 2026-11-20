import { useState, useEffect, useCallback, useTransition } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Package, Plus, Upload, History, RotateCcw, Search,
  CheckCircle2, AlertTriangle, AlertCircle, X, Download,
  Trash2, Archive, RefreshCw, FileText, ChevronLeft, ChevronRight,
  Layers, Check, ArrowRight
} from 'lucide-react';
import {
  getCatalogProducts,
  getCatalogSummary,
  addCatalogProduct,
  patchCatalogProduct,
  archiveCatalogProduct,
  permanentDeleteCatalogProduct,
  restoreCatalogProduct,
  bulkCatalogAction,
  downloadCatalogTemplate,
  previewCatalogUpload,
  commitCatalogUpload,
  getCatalogHistory,
  undoCatalogCommit,
  onboardTrain,
} from '../../api/client';

export default function Catalog() {
  const navigate = useNavigate();
  const [, startTransition] = useTransition();

  // Primary data state
  const [products, setProducts] = useState([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [summary, setSummary] = useState(null);

  // Filters & Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('active'); // active | archived | all

  // UI state
  const [loading, setLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState('');
  const [conflictError, setConflictError] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);

  // Selection
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Drawers & Modals
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState(null); // null = Add, object = Edit
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [permanentDeleteModal, setPermanentDeleteModal] = useState(null); // product to delete
  const [bulkConfirmModal, setBulkConfirmModal] = useState(null); // { action, count }
  const [undoConfirmOpen, setUndoConfirmOpen] = useState(false);
  const [undoCommitInfo, setUndoCommitInfo] = useState(null);
  const [undoError, setUndoError] = useState('');

  // Debounce search query (300ms)
  useEffect(() => {
    const handler = setTimeout(() => {
      startTransition(() => {
        setDebouncedQuery(searchQuery);
        setPage(1);
      });
    }, 300);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  // Toast notification auto-dismiss
  useEffect(() => {
    if (!toastMessage) return;
    const t = setTimeout(() => setToastMessage(null), 4000);
    return () => clearTimeout(t);
  }, [toastMessage]);

  // Fetch summary
  const loadSummary = useCallback(async () => {
    try {
      const data = await getCatalogSummary();
      setSummary(data);
    } catch (err) {
      if (err?.code === 'conflict') setConflictError(true);
      else console.error('Failed to load summary:', err);
    }
  }, []);

  // Fetch products
  const loadProducts = useCallback(async (isInitial = false) => {
    if (isInitial) setLoading(true);
    else setTableLoading(true);
    setError('');

    try {
      const res = await getCatalogProducts({
        query: debouncedQuery,
        category: categoryFilter,
        status: statusFilter,
        page,
        pageSize,
      });
      setProducts(res.items || []);
      setTotal(res.total || 0);
      setTotalPages(res.total_pages || 1);
      setConflictError(false);
    } catch (err) {
      if (err?.code === 'conflict') {
        setConflictError(true);
      } else {
        setError(err?.message || 'Failed to fetch catalogue products');
      }
    } finally {
      setLoading(false);
      setTableLoading(false);
    }
  }, [debouncedQuery, categoryFilter, statusFilter, page, pageSize]);

  // Initial load
  useEffect(() => {
    loadSummary();
    loadProducts(true);
  }, [loadSummary, loadProducts]);

  // Reload everything (for conflict button & general refresh)
  const handleReload = () => {
    setConflictError(false);
    setSelectedIds(new Set());
    loadSummary();
    loadProducts(false);
  };

  // Checkbox selection
  const handleSelectAll = (e) => {
    if (e.target.checked) {
      const allCurrent = new Set(products.map(p => p.product_id));
      setSelectedIds(allCurrent);
    } else {
      setSelectedIds(new Set());
    }
  };

  const handleToggleSelect = (pid) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });
  };

  const isAllCurrentSelected = products.length > 0 && products.every(p => selectedIds.has(p.product_id));
  const isSomeSelected = selectedIds.size > 0 && !isAllCurrentSelected;

  // Single product archive / restore
  const handleArchiveSingle = async (p, e) => {
    e.stopPropagation();
    setActionLoading(true);
    try {
      await archiveCatalogProduct(p.product_id);
      setToastMessage({ type: 'success', text: `Product "${p.product_name}" archived.` });
      handleReload();
    } catch (err) {
      if (err?.code === 'conflict') setConflictError(true);
      else setError(err?.message || 'Failed to archive product');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRestoreSingle = async (p, e) => {
    e.stopPropagation();
    setActionLoading(true);
    try {
      await restoreCatalogProduct(p.product_id);
      setToastMessage({ type: 'success', text: `Product "${p.product_name}" restored.` });
      handleReload();
    } catch (err) {
      if (err?.code === 'conflict') setConflictError(true);
      else setError(err?.message || 'Failed to restore product');
    } finally {
      setActionLoading(false);
    }
  };

  // Bulk actions
  const handleExecuteBulk = async () => {
    if (!bulkConfirmModal) return;
    const { action } = bulkConfirmModal;
    const pids = Array.from(selectedIds);
    if (pids.length > 500) {
      setError('Cannot execute bulk action on more than 500 products at once.');
      setBulkConfirmModal(null);
      return;
    }
    setActionLoading(true);
    try {
      const res = await bulkCatalogAction({ action, product_ids: pids });
      setToastMessage({ type: 'success', text: `Successfully ${action}d ${res.affected} product(s).` });
      setSelectedIds(new Set());
      setBulkConfirmModal(null);
      handleReload();
    } catch (err) {
      if (err?.code === 'conflict') setConflictError(true);
      else setError(err?.message || `Failed to ${action} products`);
      setBulkConfirmModal(null);
    } finally {
      setActionLoading(false);
    }
  };

  // Retrain navigation
  const [retraining, setRetraining] = useState(false);
  const handleRetrain = async () => {
    setRetraining(true);
    try {
      await onboardTrain();
    } catch {
      // Navigate to training view regardless of conflict
    }
    navigate('/onboarding/training');
  };

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 24, paddingBottom: 80 }}>
      {/* Toast */}
      {toastMessage && (
        <div style={{
          position: 'fixed',
          top: 24,
          right: 24,
          zIndex: 9999,
          background: toastMessage.type === 'error' ? 'var(--danger)' : '#10b981',
          color: '#fff',
          padding: '12px 20px',
          borderRadius: 'var(--radius)',
          boxShadow: '0 8px 30px rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          fontWeight: 600,
          fontSize: 14,
          animation: 'fadeUp 0.3s ease forwards',
        }}>
          {toastMessage.type === 'error' ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
          {toastMessage.text}
        </div>
      )}

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h2 style={{ fontFamily: 'Outfit', fontWeight: 700, fontSize: '1.8rem', display: 'flex', alignItems: 'center', gap: 10 }}>
            <Package size={28} color="var(--accent-1)" /> Product Catalogue
          </h2>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginTop: 4 }}>
            Manage active products, prices, and stock. Catalogue changes reflect immediately in recommendations.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setHistoryOpen(true)}
            title="View recent catalogue audit changes"
          >
            <History size={15} /> History
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setUploadModalOpen(true)}
            title="Import or update products via CSV/JSON/XLSX"
          >
            <Upload size={15} /> Upload File
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => { setEditingProduct(null); setDrawerOpen(true); }}
            title="Add a single new product"
          >
            <Plus size={16} /> Add Product
          </button>
        </div>
      </div>

      {/* 409 Conflict Banner */}
      {conflictError && (
        <div className="alert alert-warning animate-fade-in" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <AlertTriangle size={20} />
            <span>The catalogue was changed in another tab or by another user. Reload to see the latest version.</span>
          </div>
          <button className="btn btn-primary btn-sm" onClick={handleReload}>
            <RefreshCw size={14} /> Reload
          </button>
        </div>
      )}

      {/* General Error Banner */}
      {error && (
        <div className="alert alert-error animate-fade-in" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <AlertCircle size={20} />
            <span>{error}</span>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => setError('')}><X size={16} /></button>
        </div>
      )}

      {/* Summary Cards */}
      <SummaryCards summary={summary} loading={loading} />

      {/* Training Banner */}
      <TrainingBanner summary={summary} retraining={retraining} onRetrain={handleRetrain} />

      {/* Main Table Controls & Filters */}
      <div className="card" style={{ padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16, marginBottom: 16 }}>
          {/* Search Box */}
          <div style={{ position: 'relative', minWidth: 260, flex: '1 1 280px' }}>
            <Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Search by ID, name, brand, description…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{ paddingLeft: 36, paddingRight: 32 }}
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
              >
                <X size={16} />
              </button>
            )}
          </div>

          {/* Filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            {/* Category Filter */}
            <div style={{ minWidth: 160 }}>
              <select
                value={categoryFilter}
                onChange={e => { setCategoryFilter(e.target.value); setPage(1); }}
              >
                <option value="">All Categories</option>
                {summary?.by_category && Object.keys(summary.by_category).sort().map(cat => (
                  <option key={cat} value={cat}>{cat} ({summary.by_category[cat]})</option>
                ))}
              </select>
            </div>

            {/* Status Filter */}
            <div style={{ minWidth: 140 }}>
              <select
                value={statusFilter}
                onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
              >
                <option value="active">Active Only</option>
                <option value="archived">Archived Only</option>
                <option value="all">All Products</option>
              </select>
            </div>

            {/* Page Size */}
            <div style={{ minWidth: 100 }}>
              <select
                value={pageSize}
                onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}
              >
                <option value={25}>25 / page</option>
                <option value={50}>50 / page</option>
                <option value={100}>100 / page</option>
              </select>
            </div>

            {/* Refresh */}
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleReload}
              disabled={tableLoading}
              title="Refresh catalogue list"
            >
              <RefreshCw size={14} className={tableLoading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Table */}
        <div style={{ overflowX: 'auto', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 14 }}>
            <thead>
              <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                <th style={{ width: 44, padding: '12px 14px' }}>
                  <input
                    type="checkbox"
                    checked={isAllCurrentSelected}
                    ref={el => { if (el) el.indeterminate = isSomeSelected; }}
                    onChange={handleSelectAll}
                    style={{ width: 16, height: 16, cursor: 'pointer' }}
                  />
                </th>
                <th style={{ padding: '12px 14px' }}>Product ID</th>
                <th style={{ padding: '12px 14px' }}>Name</th>
                <th style={{ padding: '12px 14px' }}>Category</th>
                <th style={{ padding: '12px 14px' }}>Brand</th>
                <th style={{ padding: '12px 14px' }}>Price</th>
                <th style={{ padding: '12px 14px' }}>Stock</th>
                <th style={{ padding: '12px 14px' }}>Status</th>
                <th style={{ padding: '12px 14px', textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {tableLoading ? (
                <tr>
                  <td colSpan={9} style={{ padding: 48, textAlign: 'center' }}>
                    <div style={{ display: 'inline-block', width: 32, height: 32, borderRadius: '50%', border: '3px solid rgba(59,130,246,0.2)', borderTopColor: 'var(--accent-1)', animation: 'spin 1s linear infinite' }} />
                    <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 12 }}>Loading products…</div>
                  </td>
                </tr>
              ) : products.length === 0 ? (
                <tr>
                  <td colSpan={9} style={{ padding: 48, textAlign: 'center' }}>
                    {debouncedQuery || categoryFilter || statusFilter !== 'active' ? (
                      <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 15, fontWeight: 500 }}>No products matching your search or filters.</div>
                        <button
                          className="btn btn-secondary btn-sm mt-4"
                          onClick={() => { setSearchQuery(''); setCategoryFilter(''); setStatusFilter('active'); }}
                        >
                          Clear Filters
                        </button>
                      </div>
                    ) : (
                      <div>
                        <div style={{ width: 48, height: 48, borderRadius: '50%', background: 'rgba(59,130,246,0.1)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12 }}>
                          <Package size={24} color="var(--accent-1)" />
                        </div>
                        <div style={{ fontSize: 16, fontWeight: 600 }}>No products yet.</div>
                        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>
                          Upload a file to populate your catalogue, or add your first product manually.
                        </p>
                        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 16 }}>
                          <button className="btn btn-primary btn-sm" onClick={() => setUploadModalOpen(true)}>
                            <Upload size={15} /> Upload File
                          </button>
                          <button className="btn btn-secondary btn-sm" onClick={() => { setEditingProduct(null); setDrawerOpen(true); }}>
                            <Plus size={15} /> Add Product
                          </button>
                        </div>
                      </div>
                    )}
                  </td>
                </tr>
              ) : (
                products.map(p => {
                  const isArchived = p.status?.toLowerCase() === 'archived';
                  const inStock = Number(p.in_stock) !== 0;
                  const isSelected = selectedIds.has(p.product_id);

                  return (
                    <tr
                      key={p.product_id}
                      onClick={() => { setEditingProduct(p); setDrawerOpen(true); }}
                      style={{
                        borderBottom: '1px solid var(--border)',
                        background: isSelected ? 'rgba(59,130,246,0.08)' : 'transparent',
                        opacity: isArchived ? 0.65 : 1,
                        cursor: 'pointer',
                        transition: 'background 0.15s',
                      }}
                      onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-card-hover)'; }}
                      onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent'; }}
                    >
                      <td style={{ padding: '12px 14px' }} onClick={e => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => handleToggleSelect(p.product_id)}
                          style={{ width: 16, height: 16, cursor: 'pointer' }}
                        />
                      </td>
                      <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text-primary)' }}>
                        {p.product_id}
                      </td>
                      <td style={{ padding: '12px 14px', fontWeight: 500 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          {p.image_url ? (
                            <img
                              src={p.image_url}
                              alt=""
                              style={{ width: 28, height: 28, borderRadius: 4, objectFit: 'cover', background: 'var(--bg-input)' }}
                              onError={e => { e.currentTarget.style.display = 'none'; }}
                            />
                          ) : null}
                          <span style={{ color: isArchived ? 'var(--text-secondary)' : 'var(--text-primary)' }}>
                            {p.product_name}
                          </span>
                        </div>
                      </td>
                      <td style={{ padding: '12px 14px', color: 'var(--text-secondary)' }}>
                        {p.category || '—'}
                      </td>
                      <td style={{ padding: '12px 14px', color: 'var(--text-muted)' }}>
                        {p.brand || '—'}
                      </td>
                      <td style={{ padding: '12px 14px', fontWeight: 500 }}>
                        {p.price != null && !isNaN(p.price) ? `$${Number(p.price).toFixed(2)}` : '—'}
                      </td>
                      <td style={{ padding: '12px 14px' }}>
                        {inStock ? (
                          <span className="badge badge-green">In stock</span>
                        ) : (
                          <span className="badge badge-yellow">Out of stock</span>
                        )}
                      </td>
                      <td style={{ padding: '12px 14px' }}>
                        {isArchived ? (
                          <span className="badge" style={{ background: 'rgba(148,163,184,0.15)', color: '#94a3b8' }}>Archived</span>
                        ) : (
                          <span className="badge badge-blue">Active</span>
                        )}
                      </td>
                      <td style={{ padding: '12px 14px', textAlign: 'right' }} onClick={e => e.stopPropagation()}>
                        {isArchived ? (
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={e => handleRestoreSingle(p, e)}
                            disabled={actionLoading}
                            style={{ padding: '4px 10px', fontSize: 12 }}
                            title="Restore product to active status"
                          >
                            <RotateCcw size={13} /> Restore
                          </button>
                        ) : (
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={e => handleArchiveSingle(p, e)}
                            disabled={actionLoading}
                            style={{ padding: '4px 10px', fontSize: 12 }}
                            title="Archive product"
                          >
                            <Archive size={13} /> Archive
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginTop: 16, fontSize: 13, color: 'var(--text-secondary)' }}>
          <div>
            Showing {products.length > 0 ? (page - 1) * pageSize + 1 : 0} – {Math.min(page * pageSize, total)} of {total} products
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              className="btn btn-secondary btn-sm"
              disabled={page <= 1 || tableLoading}
              onClick={() => setPage(p => Math.max(1, p - 1))}
            >
              <ChevronLeft size={16} /> Prev
            </button>
            <span style={{ padding: '0 8px', fontWeight: 600 }}>
              Page {page} of {totalPages}
            </span>
            <button
              className="btn btn-secondary btn-sm"
              disabled={page >= totalPages || tableLoading}
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            >
              Next <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Sticky Bulk Action Bar */}
      {selectedIds.size > 0 && (
        <div style={{
          position: 'fixed',
          bottom: 24,
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 100,
          background: 'rgba(17,24,39,0.95)',
          backdropFilter: 'blur(16px)',
          border: '1px solid var(--accent-1)',
          boxShadow: '0 12px 40px rgba(0,0,0,0.6)',
          borderRadius: 'var(--radius)',
          padding: '12px 24px',
          display: 'flex',
          alignItems: 'center',
          gap: 20,
          maxWidth: '90vw',
        }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>
            {selectedIds.size} product{selectedIds.size > 1 ? 's' : ''} selected
          </div>
          {selectedIds.size > 500 && (
            <div style={{ fontSize: 12, color: 'var(--danger)' }}>Max bulk size is 500.</div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              className="btn btn-secondary btn-sm"
              disabled={actionLoading || selectedIds.size > 500}
              onClick={() => setBulkConfirmModal({ action: 'archive', count: selectedIds.size })}
            >
              <Archive size={14} /> Archive Selected
            </button>
            <button
              className="btn btn-secondary btn-sm"
              disabled={actionLoading || selectedIds.size > 500}
              onClick={() => setBulkConfirmModal({ action: 'restore', count: selectedIds.size })}
            >
              <RotateCcw size={14} /> Restore Selected
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setSelectedIds(new Set())}
            >
              Deselect All
            </button>
          </div>
        </div>
      )}

      {/* Add / Edit Drawer */}
      {drawerOpen && (
        <ProductDrawer
          product={editingProduct}
          onClose={() => setDrawerOpen(false)}
          onSaved={() => {
            setDrawerOpen(false);
            setToastMessage({ type: 'success', text: editingProduct ? 'Product updated successfully.' : 'Product created successfully.' });
            handleReload();
          }}
          onPermanentDeleteRequest={p => {
            setDrawerOpen(false);
            setPermanentDeleteModal(p);
          }}
          onConflict={() => setConflictError(true)}
        />
      )}

      {/* Upload Wizard Modal */}
      {uploadModalOpen && (
        <UploadWizardModal
          onClose={() => setUploadModalOpen(false)}
          onSuccess={(appliedSummary) => {
            setUploadModalOpen(false);
            setToastMessage({
              type: 'success',
              text: `Upload committed: ${appliedSummary.added} added, ${appliedSummary.updated} updated, ${appliedSummary.archived} archived.`,
            });
            handleReload();
          }}
          onConflict={() => setConflictError(true)}
        />
      )}

      {/* Audit History Drawer */}
      {historyOpen && (
        <HistoryDrawer
          onClose={() => setHistoryOpen(false)}
          onRequestUndo={(commit) => {
            setUndoCommitInfo(commit || null);
            setUndoError('');
            setUndoConfirmOpen(true);
          }}
        />
      )}

      {/* Bulk Action Confirm Dialog */}
      {bulkConfirmModal && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
          <div className="card" style={{ maxWidth: 440, width: '100%', padding: 24 }}>
            <h4 style={{ marginBottom: 12 }}>Confirm Bulk {bulkConfirmModal.action === 'archive' ? 'Archive' : 'Restore'}</h4>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 20 }}>
              Are you sure you want to {bulkConfirmModal.action} <strong>{bulkConfirmModal.count}</strong> selected product(s)?
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
              <button className="btn btn-secondary btn-sm" onClick={() => setBulkConfirmModal(null)} disabled={actionLoading}>
                Cancel
              </button>
              <button
                className={bulkConfirmModal.action === 'archive' ? 'btn btn-danger btn-sm' : 'btn btn-primary btn-sm'}
                onClick={handleExecuteBulk}
                disabled={actionLoading}
              >
                {actionLoading ? <RefreshCw size={14} className="animate-spin" /> : null}
                Yes, {bulkConfirmModal.action}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Undo Last Commit Confirm Dialog */}
      {undoConfirmOpen && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
          <div className="card" style={{ maxWidth: 480, width: '100%', padding: 24 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <AlertTriangle size={20} color="var(--accent-warn)" />
              <h4 style={{ margin: 0 }}>Undo Last Upload Commit</h4>
            </div>

            <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 12, lineHeight: 1.5 }}>
              Undo restores the catalogue as it was before the <strong>LAST UPLOAD COMMIT</strong>. Any single-product edits made after that upload will also be reverted.
            </p>

            <div style={{ background: 'var(--bg-surface)', padding: '10px 14px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', marginBottom: 16, fontSize: 13 }}>
              <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>Time of last upload commit:</div>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                {undoCommitInfo?.when ? new Date(undoCommitInfo.when).toLocaleString() : 'No upload commit recorded in recent history'}
              </div>
            </div>

            {undoError && (
              <div className="alert alert-error mb-4" style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13 }}>
                <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
                <div>{undoError}</div>
              </div>
            )}

            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 20 }}>
              Note: Up to the last 10 snapshots are retained in storage.
            </p>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  setUndoConfirmOpen(false);
                  setUndoError('');
                }}
                disabled={actionLoading}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={async () => {
                  setActionLoading(true);
                  setUndoError('');
                  try {
                    const res = await undoCatalogCommit();
                    setToastMessage({ type: 'success', text: `Snapshot "${res.snapshot}" restored (${res.total_products} products).` });
                    setUndoConfirmOpen(false);
                    setHistoryOpen(false);
                    handleReload();
                  } catch (err) {
                    if (err?.code === 'conflict') {
                      setConflictError(true);
                      setUndoConfirmOpen(false);
                    } else {
                      setUndoError(err?.message || 'No snapshot available to undo. You can only undo after committing a catalogue upload.');
                    }
                  } finally {
                    setActionLoading(false);
                  }
                }}
                disabled={actionLoading}
              >
                {actionLoading ? <RefreshCw size={14} className="animate-spin" /> : null}
                Restore Snapshot
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Permanent Delete Confirmation Dialog */}
      {permanentDeleteModal && (
        <PermanentDeleteModal
          product={permanentDeleteModal}
          onClose={() => setPermanentDeleteModal(null)}
          onSuccess={() => {
            setPermanentDeleteModal(null);
            setToastMessage({ type: 'success', text: `Product "${permanentDeleteModal.product_id}" permanently deleted.` });
            handleReload();
          }}
          onConflict={() => setConflictError(true)}
        />
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Summary Cards
───────────────────────────────────────────────────────────────────────────── */
function SummaryCards({ summary, loading }) {
  if (loading && !summary) {
    return (
      <div className="grid-4">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="card">
            <div className="skeleton" style={{ height: 60 }} />
          </div>
        ))}
      </div>
    );
  }

  const activeCount = summary?.active || 0;
  const archivedCount = summary?.archived || 0;
  const outOfStockCount = summary?.out_of_stock || 0;
  const categoryCount = summary?.by_category ? Object.keys(summary.by_category).length : 0;

  return (
    <div className="grid-4">
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Active Products</span>
          <div style={{ width: 34, height: 34, borderRadius: 8, background: 'rgba(16,185,129,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <CheckCircle2 size={16} color="var(--success)" />
          </div>
        </div>
        <div style={{ fontFamily: 'Outfit', fontWeight: 700, fontSize: '1.8rem', color: '#fff' }}>
          {activeCount.toLocaleString()}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Included in recommendation candidates</div>
      </div>

      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Archived Products</span>
          <div style={{ width: 34, height: 34, borderRadius: 8, background: 'rgba(148,163,184,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Archive size={16} color="#94a3b8" />
          </div>
        </div>
        <div style={{ fontFamily: 'Outfit', fontWeight: 700, fontSize: '1.8rem', color: '#94a3b8' }}>
          {archivedCount.toLocaleString()}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Excluded from active recommendations</div>
      </div>

      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Out of Stock</span>
          <div style={{ width: 34, height: 34, borderRadius: 8, background: 'rgba(245,158,11,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <AlertTriangle size={16} color="var(--warning)" />
          </div>
        </div>
        <div style={{ fontFamily: 'Outfit', fontWeight: 700, fontSize: '1.8rem', color: outOfStockCount > 0 ? '#fbbf24' : '#fff' }}>
          {outOfStockCount.toLocaleString()}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>in_stock = 0 (hidden if hide_out_of_stock is on)</div>
      </div>

      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Categories</span>
          <div style={{ width: 34, height: 34, borderRadius: 8, background: 'rgba(59,130,246,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Layers size={16} color="var(--accent-1)" />
          </div>
        </div>
        <div style={{ fontFamily: 'Outfit', fontWeight: 700, fontSize: '1.8rem', color: '#fff' }}>
          {categoryCount.toLocaleString()}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Active product groupings</div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Training Banner
───────────────────────────────────────────────────────────────────────────── */
function TrainingBanner({ summary, retraining, onRetrain }) {
  const navigate = useNavigate();
  if (!summary) return null;

  // Case 1: never trained
  if (summary.never_trained) {
    return (
      <div style={{
        background: 'linear-gradient(135deg, rgba(59,130,246,0.15), rgba(129,140,248,0.1))',
        border: '1px solid rgba(59,130,246,0.3)',
        borderRadius: 'var(--radius)',
        padding: '16px 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: 'rgba(59,130,246,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Package size={20} color="var(--accent-1)" />
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 15, color: '#fff' }}>
              Train your model to enable personalised recommendations
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 2 }}>
              Upload interaction history to launch the 4-model tournament and generate your first custom AI model.
            </div>
          </div>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => navigate('/onboarding/upload')}>
          Get Started <ArrowRight size={15} />
        </button>
      </div>
    );
  }

  // Case 2: additions or modifications since last training
  const added = summary.products_added_since_last_training || 0;
  const changed = summary.products_changed_since_last_training || 0;

  if (added > 0 || changed > 0) {
    return (
      <div style={{
        background: 'linear-gradient(135deg, rgba(245,158,11,0.12), rgba(59,130,246,0.08))',
        border: '1px solid rgba(245,158,11,0.3)',
        borderRadius: 'var(--radius)',
        padding: '16px 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: 'rgba(245,158,11,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <AlertTriangle size={20} color="var(--warning)" />
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 15, color: '#fff' }}>
              {added} new and {changed} changed product{added + changed === 1 ? '' : 's'} since last training.
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 2 }}>
              New products appear in the catalogue and similar results immediately, but in personalised recommendations only after retraining.
            </div>
          </div>
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={onRetrain}
          disabled={retraining}
        >
          {retraining ? <><RefreshCw size={14} className="animate-spin" /> Training…</> : <><RefreshCw size={14} /> Retrain Model</>}
        </button>
      </div>
    );
  }

  return null;
}

/* ─────────────────────────────────────────────────────────────────────────────
   Add / Edit Product Drawer
───────────────────────────────────────────────────────────────────────────── */
function ProductDrawer({ product, onClose, onSaved, onPermanentDeleteRequest, onConflict }) {
  const isEditing = Boolean(product);

  const [productId, setProductId] = useState(product?.product_id || '');
  const [name, setName] = useState(product?.product_name || product?.title || product?.name || '');
  const [category, setCategory] = useState(product?.category || '');
  const [brand, setBrand] = useState(product?.brand || '');
  const [price, setPrice] = useState(product?.price != null ? String(product.price) : '');
  const [inStock, setInStock] = useState(product ? Number(product.in_stock) !== 0 : true);
  const [description, setDescription] = useState(product?.description || '');
  const [imageUrl, setImageUrl] = useState(product?.image_url || '');
  const [productUrl, setProductUrl] = useState(product?.product_url || '');

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});

  const validate = () => {
    const errs = {};
    if (!isEditing && !productId.trim()) {
      errs.product_id = 'Product ID is required';
    }
    if (!name.trim()) {
      errs.name = 'Product name is required';
    }
    if (!category.trim()) {
      errs.category = 'Category is required';
    }
    if (price.trim() !== '') {
      const num = Number(price);
      if (isNaN(num) || num < 0) {
        errs.price = 'Price must be a valid number greater than or equal to 0';
      }
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (!validate()) return;
    setSaving(true);
    setErrors({});

    try {
      if (isEditing) {
        const updatePayload = {
          product_name: name.trim(),
          category: category.trim(),
          brand: brand.trim() || null,
          price: price.trim() !== '' ? Number(price) : null,
          in_stock: inStock ? 1 : 0,
          description: description.trim() || null,
          image_url: imageUrl.trim() || null,
          product_url: productUrl.trim() || null,
        };
        await patchCatalogProduct(product.product_id, updatePayload);
      } else {
        const createPayload = {
          product_id: productId.trim(),
          product_name: name.trim(),
          category: category.trim(),
          brand: brand.trim() || null,
          price: price.trim() !== '' ? Number(price) : null,
          in_stock: inStock ? 1 : 0,
          description: description.trim() || null,
          image_url: imageUrl.trim() || null,
          product_url: productUrl.trim() || null,
        };
        await addCatalogProduct(createPayload);
      }
      onSaved();
    } catch (err) {
      if (err?.code === 'conflict') {
        onConflict();
        setErrors({ form: 'Concurrent modification conflict: catalogue was updated elsewhere. Please reload.' });
      } else if (err?.status === 409) {
        setErrors({ product_id: err.message || 'Product ID already exists in catalogue.' });
      } else {
        setErrors({ form: err?.message || 'Failed to save product.' });
      }
    } finally {
      setSaving(false);
    }
  };

  const isArchived = isEditing && product?.status?.toLowerCase() === 'archived';

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', justifyContent: 'flex-end' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }} onClick={onClose} />
      <div
        className="card"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 520,
          height: '100%',
          borderRadius: 0,
          overflowY: 'auto',
          padding: '28px 24px',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-8px 0 32px rgba(0,0,0,0.5)',
          background: 'var(--bg-card)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700 }}>
              {isEditing ? `Edit Product: ${product.product_id}` : 'Add Product'}
            </h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 2 }}>
              {isEditing ? 'Update catalogue attributes and pricing.' : 'Add a new product directly to the catalogue.'}
            </p>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }}><X size={20} /></button>
        </div>

        {errors.form && (
          <div className="alert alert-error mb-4" style={{ fontSize: 13 }}>
            <AlertCircle size={16} /> {errors.form}
          </div>
        )}

        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 16, flex: 1 }}>
          {/* Product ID */}
          <div className="form-group">
            <label className="form-label">Product ID *</label>
            <input
              type="text"
              placeholder="e.g. SKU-1004"
              value={productId}
              onChange={e => setProductId(e.target.value)}
              disabled={isEditing}
              style={{ fontFamily: 'monospace' }}
            />
            {errors.product_id && <div className="form-error">{errors.product_id}</div>}
          </div>

          {/* Product Name */}
          <div className="form-group">
            <label className="form-label">Product Name *</label>
            <input
              type="text"
              placeholder="Display title"
              value={name}
              onChange={e => setName(e.target.value)}
            />
            {errors.name && <div className="form-error">{errors.name}</div>}
          </div>

          {/* Category */}
          <div className="form-group">
            <label className="form-label">Category *</label>
            <input
              type="text"
              placeholder="e.g. Electronics, Footwear"
              value={category}
              onChange={e => setCategory(e.target.value)}
            />
            {errors.category && <div className="form-error">{errors.category}</div>}
          </div>

          {/* Brand & Price (2 columns) */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <label className="form-label">Brand</label>
              <input
                type="text"
                placeholder="e.g. Acme"
                value={brand}
                onChange={e => setBrand(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Price ($)</label>
              <input
                type="number"
                step="0.01"
                min="0"
                placeholder="0.00"
                value={price}
                onChange={e => setPrice(e.target.value)}
              />
              {errors.price && <div className="form-error">{errors.price}</div>}
            </div>
          </div>

          {/* Stock Toggle */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--bg-input)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
            <input
              type="checkbox"
              id="inStockCheckbox"
              checked={inStock}
              onChange={e => setInStock(e.target.checked)}
              style={{ width: 18, height: 18, cursor: 'pointer' }}
            />
            <label htmlFor="inStockCheckbox" style={{ fontSize: 14, fontWeight: 500, cursor: 'pointer', flex: 1 }}>
              Product is In Stock
            </label>
            <span className={inStock ? 'badge badge-green' : 'badge badge-yellow'}>
              {inStock ? 'In Stock' : 'Out of Stock'}
            </span>
          </div>

          {/* Description */}
          <div className="form-group">
            <label className="form-label">Description</label>
            <textarea
              rows={3}
              placeholder="Product details, material, specifications…"
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </div>

          {/* Image URL & Product URL */}
          <div className="form-group">
            <label className="form-label">Image URL</label>
            <input
              type="url"
              placeholder="https://example.com/images/p1.jpg"
              value={imageUrl}
              onChange={e => setImageUrl(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label className="form-label">Product URL</label>
            <input
              type="url"
              placeholder="https://yourstore.com/products/p1"
              value={productUrl}
              onChange={e => setProductUrl(e.target.value)}
            />
          </div>

          <div style={{ marginTop: 'auto', paddingTop: 20, display: 'flex', gap: 12, borderTop: '1px solid var(--border)' }}>
            <button type="button" className="btn btn-secondary" onClick={onClose} style={{ flex: 1 }}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving} style={{ flex: 1 }}>
              {saving ? <RefreshCw size={15} className="animate-spin" /> : null}
              {isEditing ? 'Save Changes' : 'Create Product'}
            </button>
          </div>
        </form>

        {/* Permanent Delete Section (Only if archived) */}
        {isArchived && (
          <div style={{ marginTop: 28, paddingTop: 20, borderTop: '1px solid rgba(239,68,68,0.2)' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--danger)', marginBottom: 4 }}>
              Danger Zone
            </div>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
              This product is archived. Permanent deletion removes the product record from the catalogue file entirely.
            </p>
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => onPermanentDeleteRequest(product)}
            >
              <Trash2 size={14} /> Permanently Delete Product
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Permanent Delete Confirm Modal
───────────────────────────────────────────────────────────────────────────── */
function PermanentDeleteModal({ product, onClose, onSuccess, onConflict }) {
  const [typedId, setTypedId] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState('');

  const isMatched = typedId.trim() === product.product_id;

  const handleDelete = async () => {
    if (!isMatched) return;
    setDeleting(true);
    setErr('');
    try {
      await permanentDeleteCatalogProduct(product.product_id);
      onSuccess();
    } catch (e) {
      if (e?.code === 'conflict') onConflict();
      setErr(e?.message || 'Permanent deletion failed');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1100, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div className="card" style={{ maxWidth: 440, width: '100%', padding: 24, border: '1px solid var(--danger)' }}>
        <h4 style={{ color: 'var(--danger)', display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <AlertTriangle size={18} /> Permanently Delete Product
        </h4>
        <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 12 }}>
          This will permanently remove <strong>{product.product_id}</strong> ({product.product_name}) from the catalogue. This action cannot be undone.
        </p>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>
          Please type <strong style={{ color: '#fff' }}>{product.product_id}</strong> to confirm:
        </p>
        <input
          type="text"
          value={typedId}
          onChange={e => setTypedId(e.target.value)}
          placeholder={product.product_id}
          style={{ marginBottom: 16, fontFamily: 'monospace' }}
        />
        {err && <div className="form-error mb-4">{err}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
          <button className="btn btn-secondary btn-sm" onClick={onClose} disabled={deleting}>
            Cancel
          </button>
          <button
            className="btn btn-danger btn-sm"
            onClick={handleDelete}
            disabled={!isMatched || deleting}
          >
            {deleting ? <RefreshCw size={14} className="animate-spin" /> : null}
            Permanently Delete
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Upload Wizard Modal (4 Steps)
───────────────────────────────────────────────────────────────────────────── */
function UploadWizardModal({ onClose, onSuccess, onConflict }) {
  const [step, setStep] = useState(1); // 1: Template, 2: Select, 3: Preview, 4: Success
  const [file, setFile] = useState(null);
  const [mode, setMode] = useState('upsert'); // upsert | replace
  const [previewData, setPreviewData] = useState(null);
  const [commitData, setCommitData] = useState(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Step 1: Download Template
  const handleDownloadTemplate = async () => {
    try {
      const csvText = await downloadCatalogTemplate('csv');
      const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.setAttribute('download', 'catalog_template.csv');
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      setError('Failed to download catalogue template.');
    }
  };

  // Step 2 -> 3: Preview upload
  const handlePreview = async () => {
    if (!file) return;
    setLoading(true);
    setError('');
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('mode', mode);

      const preview = await previewCatalogUpload(formData);
      setPreviewData(preview);
      setStep(3);
    } catch (err) {
      setError(err?.message || 'Failed to preview upload.');
    } finally {
      setLoading(false);
    }
  };

  // Step 3 -> 4: Commit upload
  const handleCommit = async () => {
    if (!previewData?.upload_id) return;
    setLoading(true);
    setError('');
    try {
      const res = await commitCatalogUpload(previewData.upload_id);
      setCommitData(res);
      setStep(4);
    } catch (err) {
      if (err?.code === 'conflict') {
        onConflict();
        setError('Catalogue conflict detected while committing. Another modification occurred.');
      } else if (err?.status === 404 || err?.message?.includes('expired')) {
        setError('This preview has expired (pending uploads expire after 1 hour). Please re-upload your file.');
      } else {
        setError(err?.message || 'Failed to commit upload.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 600, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div className="card" style={{ maxWidth: 640, width: '100%', maxHeight: '90vh', overflowY: 'auto', padding: 28, position: 'relative' }}>
        <button onClick={onClose} style={{ position: 'absolute', right: 20, top: 20, color: 'var(--text-muted)' }}><X size={20} /></button>

        {/* Wizard Steps Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
          {[1, 2, 3, 4].map(s => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 8, flex: s < 4 ? 1 : 'none' }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                background: step === s ? 'var(--accent-1)' : step > s ? 'var(--success)' : 'var(--bg-input)',
                color: '#fff', fontSize: 13, fontWeight: 600,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                border: '1px solid var(--border)',
              }}>
                {step > s ? <Check size={14} /> : s}
              </div>
              {s < 4 && <div style={{ height: 2, background: step > s ? 'var(--success)' : 'var(--border)', flex: 1 }} />}
            </div>
          ))}
        </div>

        {error && (
          <div className="alert alert-error mb-4" style={{ fontSize: 13 }}>
            <AlertCircle size={16} /> {error}
          </div>
        )}

        {/* Step 1: Template */}
        {step === 1 && (
          <div>
            <h3 style={{ fontSize: '1.25rem', marginBottom: 8 }}>Step 1: Download Template</h3>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 20 }}>
              Use our standard format to prepare your product data. CSV, JSON, and XLSX files up to 20 MB and 100,000 rows are supported.
            </p>
            <div style={{ background: 'var(--bg-surface)', padding: 18, borderRadius: 'var(--radius)', border: '1px solid var(--border)', marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <FileText size={28} color="var(--accent-1)" />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>Catalogue CSV Template</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Includes standard headers: product_id, product_name, category, brand, price, in_stock, description, image_url, product_url</div>
                </div>
                <button className="btn btn-secondary btn-sm" onClick={handleDownloadTemplate}>
                  <Download size={14} /> Download
                </button>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
              <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" onClick={() => setStep(2)}>
                Next: Select File <ArrowRight size={15} />
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Choose File & Mode */}
        {step === 2 && (
          <div>
            <h3 style={{ fontSize: '1.25rem', marginBottom: 8 }}>Step 2: Choose File & Mode</h3>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 20 }}>
              Select your catalogue file and specify how existing products should be handled.
            </p>

            {/* Dropzone */}
            <div
              style={{
                border: '2px dashed var(--border-glow)',
                borderRadius: 'var(--radius)',
                padding: 32,
                textAlign: 'center',
                background: file ? 'rgba(59,130,246,0.05)' : 'var(--bg-surface)',
                cursor: 'pointer',
                marginBottom: 20,
              }}
              onClick={() => document.getElementById('catalogFileInput').click()}
            >
              <input
                id="catalogFileInput"
                type="file"
                accept=".csv,.json,.xlsx"
                style={{ display: 'none' }}
                onChange={e => {
                  if (e.target.files && e.target.files[0]) {
                    setFile(e.target.files[0]);
                  }
                }}
              />
              <Upload size={32} color="var(--accent-1)" style={{ margin: '0 auto 12px' }} />
              {file ? (
                <div>
                  <div style={{ fontWeight: 600, color: '#fff' }}>{file.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                    {(file.size / 1024 / 1024).toFixed(2)} MB • Click to choose another file
                  </div>
                </div>
              ) : (
                <div>
                  <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>Click to browse or drag and drop</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>CSV, JSON, or XLSX up to 20 MB</div>
                </div>
              )}
            </div>

            {/* Mode Selector */}
            <div className="form-group mb-6">
              <label className="form-label" style={{ marginBottom: 8 }}>Import Mode</label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div
                  onClick={() => setMode('upsert')}
                  style={{
                    padding: 14,
                    borderRadius: 'var(--radius-sm)',
                    border: mode === 'upsert' ? '2px solid var(--accent-1)' : '1px solid var(--border)',
                    background: mode === 'upsert' ? 'rgba(59,130,246,0.1)' : 'var(--bg-surface)',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 14, color: mode === 'upsert' ? '#fff' : 'var(--text-secondary)' }}>
                    Add and update (safe)
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                    Adds new items and updates matching IDs. Unmentioned products are left untouched.
                  </div>
                </div>

                <div
                  onClick={() => setMode('replace')}
                  style={{
                    padding: 14,
                    borderRadius: 'var(--radius-sm)',
                    border: mode === 'replace' ? '2px solid var(--warning)' : '1px solid var(--border)',
                    background: mode === 'replace' ? 'rgba(245,158,11,0.1)' : 'var(--bg-surface)',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 14, color: mode === 'replace' ? '#fbbf24' : 'var(--text-secondary)' }}>
                    Replace catalogue
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                    Missing products are ARCHIVED (never deleted) and can be restored or undone.
                  </div>
                </div>
              </div>
            </div>

            {mode === 'replace' && (
              <div className="alert alert-warning mb-6" style={{ fontSize: 13 }}>
                <AlertTriangle size={16} />
                Products missing from the uploaded file will be archived. You can always restore them or use Undo.
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <button className="btn btn-secondary" onClick={() => setStep(1)}>Back</button>
              <button
                className="btn btn-primary"
                disabled={!file || loading}
                onClick={handlePreview}
              >
                {loading ? <RefreshCw size={15} className="animate-spin" /> : null}
                Preview Changes <ArrowRight size={15} />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Preview */}
        {step === 3 && previewData && (
          <div>
            <h3 style={{ fontSize: '1.25rem', marginBottom: 8 }}>Step 3: Preview Changes</h3>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 20 }}>
              Review the additions, updates, and archives before applying them.
            </p>

            <div className="grid-3 mb-6">
              <div className="card" style={{ padding: 16, background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>To Add</div>
                <div style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--success)', marginTop: 4 }}>
                  +{previewData.to_add}
                </div>
              </div>
              <div className="card" style={{ padding: 16, background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)' }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>To Update</div>
                <div style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--accent-1)', marginTop: 4 }}>
                  ~{previewData.to_update}
                </div>
              </div>
              <div className="card" style={{ padding: 16, background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)' }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>To Archive</div>
                <div style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--warning)', marginTop: 4 }}>
                  {previewData.to_archive}
                </div>
              </div>
            </div>

            {/* Error Table (if errors exist) */}
            {previewData.errors && previewData.errors.length > 0 ? (
              <div style={{ marginBottom: 24 }}>
                <div className="alert alert-error mb-3" style={{ fontSize: 13 }}>
                  <AlertCircle size={16} />
                  Found {previewData.errors.length} validation error{previewData.errors.length === 1 ? '' : 's'}. You must fix these errors before committing.
                </div>
                <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                  <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                    <thead style={{ background: 'var(--bg-surface)' }}>
                      <tr>
                        <th style={{ padding: '8px 12px', width: 80 }}>Row #</th>
                        <th style={{ padding: '8px 12px' }}>Error Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewData.errors.map((err, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                          <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontWeight: 600 }}>{err.row}</td>
                          <td style={{ padding: '8px 12px', color: 'var(--danger)' }}>{err.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="alert alert-success mb-6" style={{ fontSize: 13 }}>
                <CheckCircle2 size={16} />
                All {previewData.total_rows} rows passed validation and are ready to commit.
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <button className="btn btn-secondary" onClick={() => setStep(2)}>
                Back / Choose File
              </button>
              <button
                className="btn btn-primary"
                disabled={previewData.errors && previewData.errors.length > 0 || loading}
                onClick={handleCommit}
              >
                {loading ? <RefreshCw size={15} className="animate-spin" /> : null}
                Commit Changes
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Success */}
        {step === 4 && commitData && (
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <div style={{ width: 56, height: 56, borderRadius: '50%', background: 'rgba(16,185,129,0.15)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
              <CheckCircle2 size={32} color="var(--success)" />
            </div>
            <h3 style={{ fontSize: '1.3rem', marginBottom: 8 }}>Upload Committed Successfully!</h3>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 24 }}>
              Applied {commitData.applied} total items: +{commitData.added} added, ~{commitData.updated} updated, {commitData.archived} archived.
            </p>
            <button className="btn btn-primary" onClick={() => onSuccess(commitData)}>
              Close & View Catalogue
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   History & Undo Drawer
───────────────────────────────────────────────────────────────────────────── */
function HistoryDrawer({ onClose, onRequestUndo }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const res = await getCatalogHistory();
        setHistory(res.changes || []);
      } catch (err) {
        setError(err?.message || 'Failed to load change history');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const formatWhen = (ts) => {
    if (!ts) return '—';
    try {
      const d = new Date(ts);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) +
        ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return ts;
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', justifyContent: 'flex-end' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }} onClick={onClose} />
      <div
        className="card"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 520,
          height: '100%',
          borderRadius: 0,
          overflowY: 'auto',
          padding: '28px 24px',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-8px 0 32px rgba(0,0,0,0.5)',
          background: 'var(--bg-card)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
              <History size={20} color="var(--accent-1)" /> Catalogue Audit History
            </h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 2 }}>
              Last 50 changes recorded in immutable audit logs.
            </p>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }}><X size={20} /></button>
        </div>

        {/* Undo Action Bar */}
        <div style={{ background: 'var(--bg-surface)', padding: 16, borderRadius: 'var(--radius)', border: '1px solid var(--border)', marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>Snapshot Rollback</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Undo restores the snapshot taken before the last upload commit.</div>
            </div>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => {
                const lastCommit = history.find(h => h.action === 'upload_commit');
                onRequestUndo(lastCommit || null);
              }}
            >
              <RotateCcw size={14} /> Undo Last Bulk Change
            </button>
          </div>
        </div>

        {error && <div className="alert alert-error mb-4">{error}</div>}

        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <div style={{ display: 'inline-block', width: 28, height: 28, borderRadius: '50%', border: '3px solid rgba(59,130,246,0.2)', borderTopColor: 'var(--accent-1)', animation: 'spin 1s linear infinite' }} />
          </div>
        ) : history.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)', fontSize: 14 }}>
            No history recorded yet.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {history.map((h, i) => (
              <div key={i} style={{ padding: 14, borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span className="badge badge-blue" style={{ textTransform: 'capitalize' }}>
                    {h.action || 'change'}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {formatWhen(h.when)}
                  </span>
                </div>
                <div style={{ fontSize: 13, color: 'var(--text-primary)', marginTop: 4 }}>
                  <strong>{h.product_ids_count || (h.product_ids ? h.product_ids.length : 0)}</strong> product(s) affected
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace', marginTop: 4 }}>
                  By: {h.who || 'system'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
