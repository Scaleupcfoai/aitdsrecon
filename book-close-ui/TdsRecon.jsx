import { useState, useRef, useEffect, useMemo } from 'react';
import './tds-recon.css';

const API = 'http://localhost:8000';
const fmt = (n) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n);

function TdsRecon({ onBack }) {
  const [status, setStatus] = useState('idle'); // idle | running | done | error
  const [visibleEvents, setVisibleEvents] = useState([]);
  const [results, setResults] = useState(null);
  const [activeTab, setActiveTab] = useState('summary');
  const [expandedSections, setExpandedSections] = useState(new Set());
  const [reviewDecisions, setReviewDecisions] = useState({});
  const [runCount, setRunCount] = useState(0);
  const [uploadedFiles, setUploadedFiles] = useState({ form26: null, tally: null });
  const [useUpload, setUseUpload] = useState(false);
  const logRef = useRef(null);

  // Auto-scroll agent activity log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [visibleEvents]);

  // Upload files then run, or run on existing data
  const runPipeline = async () => {
    setStatus('running');
    setVisibleEvents([]);
    setReviewDecisions({});
    setResults(null);

    // If user uploaded files, upload them first
    let streamUrl = `${API}/api/run/stream`;
    if (useUpload && uploadedFiles.form26 && uploadedFiles.tally) {
      try {
        const formData = new FormData();
        formData.append('form26', uploadedFiles.form26);
        formData.append('tally', uploadedFiles.tally);
        const uploadRes = await fetch(`${API}/api/upload`, { method: 'POST', body: formData });
        if (!uploadRes.ok) throw new Error('Upload failed');
        streamUrl = `${API}/api/run/stream/upload`;
      } catch (err) {
        setVisibleEvents([{ agent: 'Upload', type: 'error', message: `Upload failed: ${err.message}` }]);
        setStatus('error');
        return;
      }
    }

    try {
      const evtSource = new EventSource(streamUrl);

      evtSource.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data);
          if (event.type === 'keepalive') return;

          if (event.type === 'pipeline_complete') {
            // Final event with results
            setResults(event.results || null);
            setRunCount(prev => prev + 1);
            setStatus('done');
            evtSource.close();
            return;
          }

          // Real-time: add each event as it arrives
          setVisibleEvents(prev => [...prev, event]);
        } catch (e) {
          // Ignore parse errors
        }
      };

      evtSource.onerror = () => {
        evtSource.close();
        // If we haven't received pipeline_complete, fetch results
        fetch(`${API}/api/results`).then(r => r.json()).then(data => {
          setResults(data);
          setRunCount(prev => prev + 1);
          setStatus('done');
        }).catch(() => setStatus('error'));
      };
    } catch (err) {
      setVisibleEvents([{ agent: 'Error', type: 'error', message: `Failed to connect to API: ${err.message}. Make sure api_server.py is running on port 8000.` }]);
      setStatus('error');
    }
  };

  // Submit review decisions
  const submitReview = async () => {
    const decisions = Object.entries(reviewDecisions)
      .filter(([, d]) => d.decision)
      .map(([vendor, d]) => ({
        vendor,
        decision: d.decision,
        params: d.params || {},
        reason: d.reason || `Human review: ${d.decision}`,
      }));
    if (decisions.length === 0) return;

    setStatus('running');
    try {
      const res = await fetch(`${API}/api/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decisions }),
      });
      const data = await res.json();
      // Learning Agent returns its own events (corrections + Checker + Reporter only)
      setVisibleEvents(prev => [...prev, ...(data.events || [])]);
      setResults(data.results || null);
      setRunCount(prev => prev + 1);
      setReviewDecisions({});
      setStatus('done');
    } catch (err) {
      setStatus('error');
    }
  };

  // Derived data
  const summary = results?.reconciliation_summary || null;
  const matchResults = results?.match_results || null;
  const checkerResults = results?.checker_results || null;
  const matches = matchResults?.matches || [];
  const findings = checkerResults?.findings || [];
  const unmatched194cRaw = matchResults?.unmatched_tally_194c || [];
  // Filter out below-threshold entries — they are resolved, not needing review
  const unmatched194c = unmatched194cRaw.filter(e => !e._below_threshold);

  // Group unmatched by vendor
  const unmatchedVendors = useMemo(() => {
    const map = {};
    for (const e of unmatched194c) {
      const v = e.party_name || 'Unknown';
      if (!map[v]) map[v] = { entries: [], total: 0 };
      map[v].entries.push(e);
      map[v].total += e.amount || 0;
    }
    return Object.entries(map)
      .sort((a, b) => b[1].total - a[1].total);
  }, [unmatched194c]);

  // Group matches by section
  const matchesBySection = useMemo(() => {
    const groups = {};
    for (const m of matches) {
      const section = m.form26_entry?.section || 'Unknown';
      if (!groups[section]) groups[section] = [];
      groups[section].push(m);
    }
    return groups;
  }, [matches]);

  const sectionNames = {
    '194A': 'Interest on Securities',
    '194C': 'Contractor / Freight',
    '194H': 'Commission / Brokerage',
    '194J(b)': 'Professional Fees',
    '194Q': 'Purchase of Goods',
  };

  const getMatchTypeClass = (passName) => {
    if (!passName) return '';
    if (passName.includes('exact')) return 'exact';
    if (passName.includes('fuzzy')) return 'fuzzy';
    if (passName.includes('aggregated')) return 'aggregated';
    if (passName.includes('gst')) return 'gst';
    return '';
  };

  const getMatchTypeLabel = (passName) => {
    if (!passName) return '';
    if (passName.includes('exact')) return 'Exact';
    if (passName.includes('fuzzy')) return 'Fuzzy';
    if (passName.includes('aggregated')) return 'Agg';
    if (passName.includes('gst')) return 'GST';
    if (passName.includes('exempt')) return 'Exempt';
    return passName;
  };

  const getConfClass = (conf) => {
    if (conf >= 0.9) return 'high';
    if (conf >= 0.7) return 'medium';
    return 'low';
  };

  const getAgentIconClass = (agent) => {
    const a = agent.toLowerCase();
    if (a.includes('parser')) return 'parser';
    if (a.includes('matcher')) return 'matcher';
    if (a.includes('checker')) return 'checker';
    if (a.includes('reporter')) return 'reporter';
    if (a.includes('learning')) return 'learning';
    if (a.includes('pipeline')) return 'pipeline';
    return 'matcher';
  };

  const getAgentIconLetter = (agent) => {
    const a = agent.toLowerCase();
    if (a.includes('parser')) return 'P';
    if (a.includes('matcher')) return 'M';
    if (a.includes('checker')) return 'C';
    if (a.includes('reporter')) return 'R';
    if (a.includes('learning')) return 'L';
    if (a.includes('pipeline')) return '\u2713';
    return '?';
  };

  // Group events by agent for display
  const eventBlocks = useMemo(() => {
    const blocks = [];
    let current = null;
    for (const e of visibleEvents) {
      if (!e || !e.type) continue;
      if (e.type === 'agent_start') {
        if (current) blocks.push(current);
        current = { agent: e.agent, events: [e], startTime: e.elapsed_ms };
      } else if (e.type === 'agent_done') {
        if (current) {
          current.events.push(e);
          current.endTime = e.elapsed_ms;
          blocks.push(current);
          current = null;
        }
      } else {
        if (current && current.agent === e.agent) {
          current.events.push(e);
        } else {
          // Event outside an agent block (like Pipeline complete)
          if (current) blocks.push(current);
          current = null;
          blocks.push({ agent: e.agent, events: [e], standalone: true, startTime: e.elapsed_ms });
        }
      }
    }
    if (current) blocks.push(current);
    return blocks;
  }, [visibleEvents]);

  const toggleSection = (key) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const setDecision = (vendor, decision, params = {}) => {
    setReviewDecisions(prev => ({
      ...prev,
      [vendor]: prev[vendor]?.decision === decision ? {} : { decision, params: { vendor_name: vendor, ...params } },
    }));
  };

  const pendingReviewCount = Object.values(reviewDecisions).filter(d => d.decision).length;

  // ═══ RENDER ═══
  return (
    <div className="tds-recon">
      <button className="tds-back-link" onClick={onBack}>
        &larr; Back to Reconciliations
      </button>

      <div className="tds-header">
        <div className="tds-header-left">
          <h1>TDS Payable (all sections)</h1>
          <div className="tds-subtitle">FY 2024-25 | AY 2025-26 | Sections: 194A, 194C, 194H, 194J(b), 194Q</div>
        </div>
        <button
          className="tds-run-btn"
          onClick={runPipeline}
          disabled={status === 'running' || (useUpload && (!uploadedFiles.form26 || !uploadedFiles.tally))}
        >
          {status === 'running' ? <><span className="spinner"></span> Running...</> :
           useUpload ? 'Upload & Run' : 'Run Reconciliation'}
        </button>
      </div>

      <div className="tds-split">
        {/* ── LEFT: Dashboard ── */}
        <div className="tds-dashboard">
          {status === 'idle' ? (
            <div className="tds-empty-state">
              <div className="tds-empty-icon">📋</div>
              <div className="tds-empty-title">Ready to Reconcile</div>
              <div className="tds-empty-desc" style={{ marginBottom: 16 }}>
                Upload your files or run with existing data.
              </div>

              {/* Upload toggle */}
              <div style={{ display: 'flex', gap: 8, marginBottom: 12, justifyContent: 'center' }}>
                <button
                  className={`tds-tab ${!useUpload ? 'active' : ''}`}
                  onClick={() => setUseUpload(false)}
                  style={{ fontSize: 12, padding: '4px 12px' }}
                >
                  Use Existing Data
                </button>
                <button
                  className={`tds-tab ${useUpload ? 'active' : ''}`}
                  onClick={() => setUseUpload(true)}
                  style={{ fontSize: 12, padding: '4px 12px' }}
                >
                  Upload New Files
                </button>
              </div>

              {useUpload && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center', marginBottom: 12 }}>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--text-secondary)' }}>
                    Form 26 (.xlsx)
                    <input
                      type="file"
                      accept=".xlsx,.xls"
                      onChange={e => setUploadedFiles(prev => ({ ...prev, form26: e.target.files[0] || null }))}
                      style={{ fontSize: 12 }}
                    />
                    {uploadedFiles.form26 && <span style={{ color: 'var(--accent-green)' }}>{uploadedFiles.form26.name}</span>}
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--text-secondary)' }}>
                    Tally Extract (.xlsx)
                    <input
                      type="file"
                      accept=".xlsx,.xls"
                      onChange={e => setUploadedFiles(prev => ({ ...prev, tally: e.target.files[0] || null }))}
                      style={{ fontSize: 12 }}
                    />
                    {uploadedFiles.tally && <span style={{ color: 'var(--accent-green)' }}>{uploadedFiles.tally.name}</span>}
                  </label>
                </div>
              )}
            </div>
          ) : (
            <>
              {/* KPI Cards */}
              {summary && (
                <div className="tds-kpi-row">
                  <div className="tds-kpi-card">
                    <div className="tds-kpi-value">
                      {summary.matching?.total_resolved || 0}
                    </div>
                    <div className="tds-kpi-label">
                      Entries Resolved ({summary.matching?.matched_with_tds || 0} with TDS + {summary.matching?.below_threshold_resolved || 0} exempt)
                    </div>
                    <div className="tds-kpi-bar">
                      <div className="tds-kpi-bar-fill" style={{ width: `${summary.matching?.match_rate_pct || 0}%` }} />
                    </div>
                  </div>
                  <div className="tds-kpi-card">
                    <div className="tds-kpi-value">{((summary.matching?.avg_confidence || 0) * 100).toFixed(0)}%</div>
                    <div className="tds-kpi-label">Avg Confidence</div>
                    <div className="tds-kpi-bar">
                      <div className="tds-kpi-bar-fill" style={{ width: `${(summary.matching?.avg_confidence || 0) * 100}%` }} />
                    </div>
                  </div>
                  <div className="tds-kpi-card">
                    <div className="tds-kpi-value">{summary.compliance?.total_findings || 0}</div>
                    <div className="tds-kpi-label">Findings ({summary.compliance?.errors || 0} errors)</div>
                    <div className="tds-kpi-bar">
                      <div className="tds-kpi-bar-fill" style={{
                        width: `${Math.min(100, (summary.compliance?.errors || 0) * 20)}%`,
                        background: 'var(--accent-red)'
                      }} />
                    </div>
                  </div>
                  <div className="tds-kpi-card">
                    <div className="tds-kpi-value" style={{ fontSize: 22 }}>
                      {'\u20B9'}{fmt(summary.compliance?.missing_tds_exposure || 0)}
                    </div>
                    <div className="tds-kpi-label">Missing TDS Exposure</div>
                  </div>
                </div>
              )}

              {/* Tabs */}
              <div className="tds-tabs">
                {['summary', 'matches', 'findings', 'review'].map(tab => (
                  <button
                    key={tab}
                    className={`tds-tab ${activeTab === tab ? 'active' : ''}`}
                    onClick={() => setActiveTab(tab)}
                  >
                    {tab === 'summary' ? 'Summary' :
                     tab === 'matches' ? `Matches (${matches.length})` :
                     tab === 'findings' ? `Findings (${findings.length})` :
                     `Review (${unmatchedVendors.length})`}
                  </button>
                ))}
              </div>

              {/* Tab Content */}
              {activeTab === 'summary' && summary && (
                <div>
                  {/* Section-wise overview */}
                  {Object.entries(summary.section_wise || {}).map(([section, data]) => (
                    <div key={section} className="tds-section-group">
                      <button className="tds-section-header" onClick={() => toggleSection(section)}>
                        <span className={`tds-section-chevron ${expandedSections.has(section) ? 'open' : ''}`}>&#9654;</span>
                        <span className="tds-section-name">
                          {section} {sectionNames[section] ? `\u2014 ${sectionNames[section]}` : ''}
                        </span>
                        <span className="tds-section-count">{data.form26_count} entries</span>
                        <span className={`tds-section-status-badge ${data.matched_count === data.form26_count ? 'matched' : 'pending'}`}>
                          {data.matched_count === data.form26_count ? 'Matched' :
                           data.not_in_scope ? 'Pending' : `${data.matched_count}/${data.form26_count}`}
                        </span>
                      </button>
                      {expandedSections.has(section) && (
                        <div className="tds-section-body" style={{ padding: '8px 12px' }}>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                            <div>Form 26 Amount: <strong>{'\u20B9'}{fmt(data.form26_amount || 0)}</strong></div>
                            <div>TDS Deducted: <strong>{'\u20B9'}{fmt(data.form26_tds || 0)}</strong></div>
                            {data.matched_amount != null && <div>Matched Amount: <strong>{'\u20B9'}{fmt(data.matched_amount)}</strong></div>}
                            {data.not_in_scope && <div style={{ color: 'var(--text-muted)' }}>Not yet in scope for matching</div>}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {activeTab === 'matches' && (
                <div>
                  {Object.entries(matchesBySection).map(([section, sectionMatches]) => (
                    <div key={section} className="tds-section-group">
                      <button className="tds-section-header" onClick={() => toggleSection(`m_${section}`)}>
                        <span className={`tds-section-chevron ${expandedSections.has(`m_${section}`) ? 'open' : ''}`}>&#9654;</span>
                        <span className="tds-section-name">Section {section}</span>
                        <span className="tds-section-count">{sectionMatches.length} matches</span>
                      </button>
                      {expandedSections.has(`m_${section}`) && (
                        <div className="tds-section-body">
                          {sectionMatches.map((m, i) => (
                            <div key={i} className="tds-match-row">
                              <div className="tds-match-vendor">{m.form26_entry?.vendor_name || 'Unknown'}</div>
                              <div className="tds-match-amount">{'\u20B9'}{fmt(m.form26_entry?.amount_paid || 0)}</div>
                              <div className={`tds-match-type ${getMatchTypeClass(m.pass_name)}`}>
                                {getMatchTypeLabel(m.pass_name)}
                              </div>
                              <div className={`tds-match-confidence ${getConfClass(m.confidence || 0)}`}>
                                {((m.confidence || 0) * 100).toFixed(0)}%
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {activeTab === 'findings' && (
                <div>
                  {findings.length === 0 ? (
                    <div className="tds-empty-state">
                      <div className="tds-empty-title">No findings</div>
                      <div className="tds-empty-desc">All entries passed compliance checks.</div>
                    </div>
                  ) : (
                    findings.map((f, i) => (
                      <div key={i} className="tds-finding-row">
                        <div className="tds-finding-icon">
                          {f.severity === 'error' ? '\u2717' : '\u26A0'}
                        </div>
                        <div className="tds-finding-content">
                          <div className="tds-finding-header">
                            <span className="tds-finding-vendor">{f.vendor || 'Unknown'}</span>
                            <span className={`tds-finding-severity ${f.severity}`}>{f.severity}</span>
                            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{f.check || ''}</span>
                          </div>
                          <div className="tds-finding-message">{f.message || ''}</div>
                          {f.remediation && (
                            <div className="tds-finding-remediation">{f.remediation}</div>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}

              {activeTab === 'review' && (
                <div>
                  <div className="tds-review-intro">
                    {unmatchedVendors.length} vendors have Tally entries with no matching Form 26 TDS deduction.
                    Review each vendor and classify them. Your decisions become learned rules for future runs.
                  </div>
                  {unmatchedVendors.map(([vendor, data]) => (
                    <div key={vendor} className="tds-review-vendor-row">
                      <div className="tds-review-vendor-info">
                        <div className="tds-review-vendor-name">{vendor}</div>
                        <div className="tds-review-vendor-meta">
                          {data.entries.length} entries | {'\u20B9'}{fmt(data.total)}
                        </div>
                      </div>
                      <div className="tds-review-actions">
                        {[
                          { key: 'below_threshold', label: 'Below Threshold', params: { section: '194C', annual_amount: data.total, threshold: 100000, fy: '2024-25' } },
                          { key: 'ignore', label: 'Ignore', params: { category: 'not_tds_applicable' } },
                        ].map(opt => (
                          <button
                            key={opt.key}
                            className={`tds-review-action-btn ${reviewDecisions[vendor]?.decision === opt.key ? 'selected' : ''}`}
                            onClick={() => setDecision(vendor, opt.key, opt.params)}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                  {unmatchedVendors.length > 0 && (
                    <button
                      className="tds-submit-review"
                      onClick={submitReview}
                      disabled={pendingReviewCount === 0 || status === 'running'}
                    >
                      {status === 'running' ? 'Submitting...' : `Submit ${pendingReviewCount} Decision${pendingReviewCount !== 1 ? 's' : ''} & Re-run`}
                    </button>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* ── RIGHT: Agent Activity ── */}
        <div className="tds-activity">
          <div className="tds-activity-header">
            <div className={`tds-activity-dot ${status === 'running' ? '' : 'idle'}`} />
            Agent Activity
            {runCount > 0 && <span className="tds-rules-badge">Run #{runCount}</span>}
          </div>
          <div className="tds-activity-log" ref={logRef}>
            {eventBlocks.length === 0 && status !== 'running' && (
              <div className="tds-empty-state" style={{ padding: '40px 20px' }}>
                <div className="tds-empty-desc">
                  Agent activity will appear here as the reconciliation runs.
                </div>
              </div>
            )}
            {eventBlocks.map((block, bi) => (
              <div key={bi} className="tds-agent-block">
                <div className="tds-agent-header">
                  <div className={`tds-agent-icon ${getAgentIconClass(block.agent)}`}>
                    {getAgentIconLetter(block.agent)}
                  </div>
                  <span className="tds-agent-name">{block.agent}</span>
                  {block.endTime != null && block.startTime != null && (
                    <span className="tds-agent-time">
                      {((block.endTime - block.startTime) / 1000).toFixed(1)}s
                    </span>
                  )}
                  {block.events.some(e => e.type === 'agent_done') && (
                    <span className="tds-agent-status-icon" style={{ color: 'var(--accent-green)' }}>{'\u2713'}</span>
                  )}
                </div>
                {block.events
                  .filter(e => e.type !== 'agent_start' && e.type !== 'agent_done')
                  .map((e, ei) => (
                    <div key={ei} className={`tds-log-line ${e.type}`} style={{ animationDelay: `${ei * 0.05}s` }}>
                      <span className="log-prefix">
                        {e.type === 'detail' ? '\u251C\u2500' : e.type === 'success' ? '\u2713' : e.type === 'error' ? '\u2717' : e.type === 'warning' ? '\u26A0' : '\u2022'}
                      </span>
                      {e.message}
                    </div>
                  ))}
              </div>
            ))}
            {status === 'running' && (
              <div className="tds-typing">
                <div className="tds-typing-dot" />
                <div className="tds-typing-dot" />
                <div className="tds-typing-dot" />
              </div>
            )}
            {status === 'done' && runCount > 1 && (
              <div className="tds-run-divider">Run #{runCount} Complete</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default TdsRecon;
