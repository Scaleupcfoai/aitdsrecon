import { useState, useMemo } from 'react';
import {
  teamMembers, closePeriod, closeChecklist, phaseConfig,
  reconciliations, journalEntries, trialBalance, fluxData, activityLog
} from './data/mockData';
import TdsRecon from './TdsRecon';
import './index.css';
import lekhaLogo from '/lekha-logo.svg';

// ─── Helpers ──────────────────────────────────────────────
const fmt = (n) => {
  if (n === null || n === undefined) return '—';
  const abs = Math.abs(n);
  if (abs >= 10000000) return (n < 0 ? '-' : '') + '₹' + (abs / 10000000).toFixed(2) + ' Cr';
  if (abs >= 100000) return (n < 0 ? '-' : '') + '₹' + (abs / 100000).toFixed(2) + ' L';
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
};

const fmtFull = (n) => {
  if (n === null || n === undefined) return '—';
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const getMember = (id) => teamMembers.find(m => m.id === id) || { name: '—', avatar: '?', color: '#666' };

const statusIcon = (s) => {
  switch(s) {
    case 'completed': return '✓';
    case 'in_progress': return '◔';
    case 'not_started': return '○';
    case 'approved': return '✓✓';
    case 'draft': return '✎';
    default: return '○';
  }
};

const statusLabel = (s) => {
  switch(s) {
    case 'completed': return 'Done';
    case 'in_progress': return 'In Progress';
    case 'not_started': return 'Not Started';
    case 'approved': return 'Approved';
    case 'draft': return 'Draft';
    case 'review': return 'In Review';
    default: return s;
  }
};

const priorityColor = (p) => {
  switch(p) {
    case 'critical': return '#ff7b72';
    case 'high': return '#f78166';
    case 'medium': return '#e3b341';
    case 'low': return '#8b949e';
    default: return '#8b949e';
  }
};

// ─── Main App ─────────────────────────────────────────────
export default function App() {
  const [activeView, setActiveView] = useState('dashboard');
  const [tdsReconActive, setTdsReconActive] = useState(false);
  const [selectedTask, setSelectedTask] = useState(null);
  const [selectedRecon, setSelectedRecon] = useState(null);
  const [selectedJE, setSelectedJE] = useState(null);
  const [expandedPhases, setExpandedPhases] = useState(new Set(['reconciliation', 'adjusting_entries']));
  const [taskStatuses, setTaskStatuses] = useState(() => {
    const map = {};
    closeChecklist.forEach(t => { map[t.id] = t.status; });
    return map;
  });
  const [jeStatuses, setJeStatuses] = useState(() => {
    const map = {};
    journalEntries.forEach(j => { map[j.id] = j.status; });
    return map;
  });
  const [tbView, setTbView] = useState('unadjusted'); // unadjusted | adjusted
  const [fsTab, setFsTab] = useState('pnl'); // pnl | bs
  const [showAIPanel, setShowAIPanel] = useState(false);

  // ─── Computed Stats ──────────────────────────────────────
  const stats = useMemo(() => {
    const total = closeChecklist.length;
    const completed = Object.values(taskStatuses).filter(s => s === 'completed').length;
    const inProgress = Object.values(taskStatuses).filter(s => s === 'in_progress').length;
    const notStarted = Object.values(taskStatuses).filter(s => s === 'not_started').length;
    const byPhase = {};
    Object.keys(phaseConfig).forEach(phase => {
      const tasks = closeChecklist.filter(t => t.phase === phase);
      const done = tasks.filter(t => taskStatuses[t.id] === 'completed').length;
      byPhase[phase] = { total: tasks.length, done, pct: tasks.length ? Math.round((done / tasks.length) * 100) : 0 };
    });
    const reconDone = reconciliations.filter(r => r.status === 'completed').length;
    const reconTotal = reconciliations.length;
    const jePosted = Object.values(jeStatuses).filter(s => s === 'posted' || s === 'approved').length;
    const jeTotal = journalEntries.length;
    return { total, completed, inProgress, notStarted, pct: Math.round((completed / total) * 100), byPhase, reconDone, reconTotal, jePosted, jeTotal };
  }, [taskStatuses, jeStatuses]);

  // Toggle phase expand
  const togglePhase = (phase) => {
    setExpandedPhases(prev => {
      const next = new Set(prev);
      next.has(phase) ? next.delete(phase) : next.add(phase);
      return next;
    });
  };

  // Task status toggle
  const cycleTaskStatus = (taskId) => {
    setTaskStatuses(prev => {
      const current = prev[taskId];
      const next = current === 'not_started' ? 'in_progress' : current === 'in_progress' ? 'completed' : 'not_started';
      return { ...prev, [taskId]: next };
    });
  };

  // JE status cycle
  const cycleJEStatus = (jeId) => {
    setJeStatuses(prev => {
      const current = prev[jeId];
      const next = current === 'not_started' ? 'draft' : current === 'draft' ? 'review' : current === 'review' ? 'posted' : 'not_started';
      return { ...prev, [jeId]: next };
    });
  };

  // Close the right panel
  const closeDetail = () => {
    setSelectedTask(null);
    setSelectedRecon(null);
    setSelectedJE(null);
  };

  const hasDetail = !tdsReconActive && (selectedTask || selectedRecon || selectedJE);

  // ─── Navigation Items ────────────────────────────────────
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: '⊞' },
    { id: 'checklist', label: 'Checklist', icon: '☑' },
    { id: 'reconciliations', label: 'Reconciliations', icon: '⇄' },
    { id: 'journal_entries', label: 'Journal Entries', icon: '✎' },
    { id: 'trial_balance', label: 'Trial Balance', icon: '⊟' },
    { id: 'financials', label: 'Financial Statements', icon: '📊' },
  ];

  // ─── Trial Balance Computed ──────────────────────────────
  const adjustedTB = useMemo(() => {
    if (tbView === 'unadjusted') return trialBalance;
    // Apply posted JE adjustments to trial balance
    const adjustments = {};
    journalEntries.forEach(je => {
      if (jeStatuses[je.id] === 'posted' || jeStatuses[je.id] === 'approved') {
        je.lines.forEach(line => {
          if (!adjustments[line.account]) adjustments[line.account] = { debit: 0, credit: 0 };
          adjustments[line.account].debit += line.debit;
          adjustments[line.account].credit += line.credit;
        });
      }
    });
    return trialBalance.map(row => {
      // Try to match by name (simplified)
      const adj = Object.entries(adjustments).find(([name]) =>
        row.name.toLowerCase().includes(name.toLowerCase().split('—')[0].trim().toLowerCase()) ||
        name.toLowerCase().includes(row.name.toLowerCase().split('—')[0].trim().toLowerCase())
      );
      if (adj) {
        return {
          ...row,
          adjDebit: adj[1].debit,
          adjCredit: adj[1].credit,
          debit: row.debit + adj[1].debit,
          credit: row.credit + adj[1].credit,
        };
      }
      return { ...row, adjDebit: 0, adjCredit: 0 };
    });
  }, [tbView, jeStatuses]);

  const tbTotals = useMemo(() => {
    return adjustedTB.reduce((acc, row) => {
      acc.debit += row.debit;
      acc.credit += row.credit;
      return acc;
    }, { debit: 0, credit: 0 });
  }, [adjustedTB]);

  // ─── Financial Statements Computed ───────────────────────
  const financials = useMemo(() => {
    const tb = adjustedTB;
    // P&L
    const revenue = tb.filter(r => r.category === 'Revenue' && r.subcategory === 'Revenue')
      .reduce((s, r) => s + r.credit - r.debit, 0);
    const otherIncome = tb.filter(r => r.subcategory === 'Other Income')
      .reduce((s, r) => s + r.credit - r.debit, 0);
    const cogs = tb.filter(r => r.subcategory === 'COGS')
      .reduce((s, r) => s + r.debit - r.credit, 0);
    const employeeCost = tb.filter(r => r.subcategory === 'Employee Costs' || r.fsLine === 'Employee Benefit Expense')
      .reduce((s, r) => s + r.debit - r.credit, 0);
    const depreciation = tb.filter(r => r.subcategory === 'Depreciation')
      .reduce((s, r) => s + r.debit - r.credit, 0);
    const otherExpenses = tb.filter(r => r.subcategory === 'Operating Expenses')
      .reduce((s, r) => s + r.debit - r.credit, 0);
    const financeCosts = tb.filter(r => r.subcategory === 'Finance Costs')
      .reduce((s, r) => s + r.debit - r.credit, 0);
    const tax = tb.filter(r => r.subcategory === 'Tax')
      .reduce((s, r) => s + r.debit - r.credit, 0);
    const pbt = revenue + otherIncome - cogs - employeeCost - depreciation - otherExpenses - financeCosts;
    const pat = pbt - tax;

    // Balance Sheet
    const currentAssets = tb.filter(r => r.subcategory === 'Current Assets')
      .reduce((s, r) => s + r.debit - r.credit, 0);
    const fixedAssets = tb.filter(r => r.subcategory === 'Fixed Assets')
      .reduce((s, r) => s + r.debit - r.credit, 0);
    const currentLiabilities = tb.filter(r => r.subcategory === 'Current Liabilities')
      .reduce((s, r) => s + r.credit - r.debit, 0);
    const ncLiabilities = tb.filter(r => r.subcategory === 'Non-Current Liabilities')
      .reduce((s, r) => s + r.credit - r.debit, 0);
    const equity = tb.filter(r => r.subcategory === 'Equity')
      .reduce((s, r) => s + r.credit - r.debit, 0);

    return {
      revenue, otherIncome, cogs, employeeCost, depreciation, otherExpenses,
      financeCosts, tax, pbt, pat,
      currentAssets, fixedAssets, currentLiabilities, ncLiabilities, equity,
      totalAssets: currentAssets + fixedAssets,
      totalLiabilities: currentLiabilities + ncLiabilities + equity + pat,
    };
  }, [adjustedTB]);

  // ─────────────────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────────────────
  return (
    <div className="app-container">
      {/* ═══ LEFT PANEL: Navigation ═══ */}
      <aside className="left-panel">
        <div className="brand">
          <img src={lekhaLogo} className="brand-logo-img" alt="Lekha AI" />
          <div className="brand-text">
            <span className="brand-name">Lekha AI</span>
            <span className="brand-sub">Book Close Management</span>
          </div>
        </div>

        {/* Close Period Info */}
        <div className="close-period-card">
          <div className="cp-header">
            <span className="cp-badge">{closePeriod.type}</span>
            <span className="cp-month">{closePeriod.month}</span>
          </div>
          <div className="cp-fy">{closePeriod.fy}</div>
          <div className="cp-progress-bar">
            <div className="cp-progress-fill" style={{ width: `${stats.pct}%` }} />
          </div>
          <div className="cp-progress-text">{stats.pct}% complete — Day {closePeriod.daysElapsed}/{closePeriod.totalDays}</div>
        </div>

        {/* Navigation */}
        <nav className="nav-list">
          {navItems.map(item => (
            <button
              key={item.id}
              className={`nav-item ${activeView === item.id ? 'active' : ''}`}
              onClick={() => { setActiveView(item.id); closeDetail(); }}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
              {item.id === 'checklist' && (
                <span className="nav-badge">{stats.completed}/{stats.total}</span>
              )}
              {item.id === 'reconciliations' && (
                <span className="nav-badge">{stats.reconDone}/{stats.reconTotal}</span>
              )}
              {item.id === 'journal_entries' && (
                <span className="nav-badge">{stats.jePosted}/{stats.jeTotal}</span>
              )}
            </button>
          ))}
        </nav>

        {/* Team */}
        <div className="team-section">
          <div className="team-header">TEAM</div>
          {teamMembers.map(m => (
            <div key={m.id} className="team-member">
              <div className="avatar" style={{ background: m.color }}>{m.avatar}</div>
              <div className="member-info">
                <div className="member-name">{m.name}</div>
                <div className="member-role">{m.role}</div>
              </div>
            </div>
          ))}
        </div>

        {/* AI Assistant */}
        <button className="ai-assist-btn" onClick={() => setShowAIPanel(!showAIPanel)}>
          <span className="ai-dot" />
          Lekha AI Assistant
        </button>
      </aside>

      {/* ═══ CENTER PANEL: Main Content ═══ */}
      <main className={`center-panel ${hasDetail ? 'with-detail' : ''}`}>
        {/* ─── DASHBOARD VIEW ─── */}
        {activeView === 'dashboard' && (
          <div className="view-content">
            <div className="view-header">
              <h1>Close Dashboard</h1>
              <div className="view-header-right">
                <span className="header-period">{closePeriod.month} • {closePeriod.fy}</span>
              </div>
            </div>

            {/* Stats Row */}
            <div className="stats-row">
              <div className="stat-card">
                <div className="stat-value">{stats.pct}%</div>
                <div className="stat-label">Overall Progress</div>
                <div className="stat-bar"><div className="stat-bar-fill" style={{ width: `${stats.pct}%`, background: 'var(--accent)' }} /></div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{stats.completed}<span className="stat-total">/{stats.total}</span></div>
                <div className="stat-label">Tasks Completed</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{stats.reconDone}<span className="stat-total">/{stats.reconTotal}</span></div>
                <div className="stat-label">Reconciliations Done</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{stats.jePosted}<span className="stat-total">/{stats.jeTotal}</span></div>
                <div className="stat-label">JEs Posted</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{closePeriod.totalDays - closePeriod.daysElapsed}</div>
                <div className="stat-label">Days Remaining</div>
              </div>
            </div>

            {/* Phase Progress */}
            <div className="section-title">Phase Progress</div>
            <div className="phase-grid">
              {Object.entries(phaseConfig).map(([key, config]) => {
                const p = stats.byPhase[key];
                return (
                  <div key={key} className="phase-card" onClick={() => { setActiveView('checklist'); setExpandedPhases(new Set([key])); }}>
                    <div className="phase-card-header">
                      <span className="phase-num" style={{ background: config.color }}>{config.icon}</span>
                      <span className="phase-name">{config.label}</span>
                    </div>
                    <div className="phase-card-bar">
                      <div className="phase-card-fill" style={{ width: `${p.pct}%`, background: config.color }} />
                    </div>
                    <div className="phase-card-text">{p.done}/{p.total} tasks • {p.pct}%</div>
                  </div>
                );
              })}
            </div>

            {/* Two Column: Activity + Blockers */}
            <div className="dash-two-col">
              <div className="dash-col">
                <div className="section-title">Recent Activity</div>
                <div className="activity-list">
                  {activityLog.slice(0, 8).map((a, i) => {
                    const member = getMember(a.user);
                    return (
                      <div key={i} className="activity-item">
                        <div className="avatar-sm" style={{ background: member.color }}>{member.avatar}</div>
                        <div className="activity-text">
                          <div className="activity-action">{a.action}</div>
                          <div className="activity-time">{a.time} — {member.name}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="dash-col">
                <div className="section-title">Attention Needed</div>
                <div className="blocker-list">
                  {reconciliations.filter(r => r.status === 'in_progress' && r.variance > 0).map(r => (
                    <div key={r.id} className="blocker-item" onClick={() => { setActiveView('reconciliations'); setSelectedRecon(r); }}>
                      <span className="blocker-icon">⚠</span>
                      <div className="blocker-text">
                        <div className="blocker-title">{r.account}</div>
                        <div className="blocker-desc">Variance: {fmtFull(r.variance)} — {r.reconcilingItems.length} items</div>
                      </div>
                    </div>
                  ))}
                  {closeChecklist.filter(t => t.priority === 'critical' && taskStatuses[t.id] === 'not_started').slice(0, 3).map(t => (
                    <div key={t.id} className="blocker-item" onClick={() => { setActiveView('checklist'); setSelectedTask(t); }}>
                      <span className="blocker-icon">🔴</span>
                      <div className="blocker-text">
                        <div className="blocker-title">{t.task}</div>
                        <div className="blocker-desc">Critical • Due {t.dueDate} • {getMember(t.owner).name}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─── CHECKLIST VIEW ─── */}
        {activeView === 'checklist' && (
          <div className="view-content">
            <div className="view-header">
              <h1>Close Checklist</h1>
              <div className="view-header-right">
                <span className="completed-count">{stats.completed}/{stats.total} completed</span>
              </div>
            </div>

            {Object.entries(phaseConfig).sort((a, b) => a[1].order - b[1].order).map(([phaseKey, config]) => {
              const phaseTasks = closeChecklist.filter(t => t.phase === phaseKey);
              const expanded = expandedPhases.has(phaseKey);
              const p = stats.byPhase[phaseKey];
              return (
                <div key={phaseKey} className="phase-group">
                  <div className="phase-header" onClick={() => togglePhase(phaseKey)}>
                    <span className={`chevron ${expanded ? 'open' : ''}`}>▶</span>
                    <span className="phase-num" style={{ background: config.color }}>{config.icon}</span>
                    <span className="phase-title">{config.label}</span>
                    <span className="phase-count">{p.done}/{p.total}</span>
                    <div className="phase-mini-bar">
                      <div className="phase-mini-fill" style={{ width: `${p.pct}%`, background: config.color }} />
                    </div>
                    {p.pct === 100 && <span className="phase-done-badge">Complete</span>}
                  </div>
                  {expanded && (
                    <div className="phase-body">
                      {phaseTasks.map(task => {
                        const owner = getMember(task.owner);
                        const reviewer = task.reviewer ? getMember(task.reviewer) : null;
                        const st = taskStatuses[task.id];
                        return (
                          <div
                            key={task.id}
                            className={`task-row ${st} ${selectedTask?.id === task.id ? 'selected' : ''}`}
                            onClick={() => setSelectedTask(task)}
                          >
                            <button
                              className={`task-check ${st}`}
                              onClick={(e) => { e.stopPropagation(); cycleTaskStatus(task.id); }}
                              title="Toggle status"
                            >
                              {statusIcon(st)}
                            </button>
                            <div className="task-info">
                              <div className="task-name">{task.task}</div>
                              <div className="task-meta">
                                <span className="priority-dot" style={{ background: priorityColor(task.priority) }} />
                                <span className="task-due">Due {task.dueDate.slice(5)}</span>
                                {reviewer && <span className="task-reviewer">Review: {reviewer.name.split(' ')[0]}</span>}
                              </div>
                            </div>
                            <div className="task-owner">
                              <div className="avatar-sm" style={{ background: owner.color }} title={owner.name}>{owner.avatar}</div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* ─── TDS RECON VIEW ─── */}
        {activeView === 'reconciliations' && tdsReconActive && (
          <div className="view-content" style={{ maxWidth: 'none', height: 'calc(100vh - 20px)' }}>
            <TdsRecon onBack={() => setTdsReconActive(false)} />
          </div>
        )}

        {/* ─── RECONCILIATIONS VIEW ─── */}
        {activeView === 'reconciliations' && !tdsReconActive && (
          <div className="view-content">
            <div className="view-header">
              <h1>Reconciliations</h1>
              <div className="view-header-right">
                <span className="completed-count">{stats.reconDone}/{stats.reconTotal} completed</span>
              </div>
            </div>

            <div className="recon-grid">
              {reconciliations.map(r => {
                const owner = getMember(r.owner);
                return (
                  <div
                    key={r.id}
                    className={`recon-card ${r.status} ${selectedRecon?.id === r.id ? 'selected' : ''}`}
                    onClick={() => r.id === 'r7' ? setTdsReconActive(true) : setSelectedRecon(r)}
                  >
                    <div className="recon-card-header">
                      <span className={`recon-type-badge ${r.type}`}>{r.type.replace('_', ' ')}</span>
                      <span className={`recon-status-badge ${r.status}`}>{statusLabel(r.status)}</span>
                    </div>
                    <div className="recon-account">{r.account}</div>
                    {r.status !== 'not_started' && (
                      <div className="recon-balances">
                        <div className="recon-bal-row">
                          <span>GL Balance</span>
                          <span>{fmtFull(r.glBalance)}</span>
                        </div>
                        <div className="recon-bal-row">
                          <span>Supporting</span>
                          <span>{fmtFull(r.supportingBalance)}</span>
                        </div>
                        {r.variance !== null && r.variance !== 0 && (
                          <div className="recon-bal-row variance">
                            <span>Variance</span>
                            <span className="variance-amount">{fmtFull(r.variance)}</span>
                          </div>
                        )}
                      </div>
                    )}
                    <div className="recon-card-footer">
                      <div className="avatar-sm" style={{ background: owner.color }} title={owner.name}>{owner.avatar}</div>
                      <span className="recon-items-count">
                        {r.reconcilingItems.length > 0 ? `${r.reconcilingItems.length} items` : 'No items'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ─── JOURNAL ENTRIES VIEW ─── */}
        {activeView === 'journal_entries' && (
          <div className="view-content">
            <div className="view-header">
              <h1>Adjusting Journal Entries</h1>
              <div className="view-header-right">
                <span className="completed-count">{stats.jePosted}/{stats.jeTotal} posted</span>
              </div>
            </div>

            <div className="je-table">
              <div className="je-table-header">
                <span className="je-col-status">Status</span>
                <span className="je-col-id">ID</span>
                <span className="je-col-desc">Description</span>
                <span className="je-col-type">Type</span>
                <span className="je-col-amount">Amount</span>
                <span className="je-col-date">Date</span>
                <span className="je-col-owner">Preparer</span>
              </div>
              {journalEntries.map(je => {
                const preparer = getMember(je.preparedBy);
                const st = jeStatuses[je.id];
                return (
                  <div
                    key={je.id}
                    className={`je-row ${st} ${selectedJE?.id === je.id ? 'selected' : ''}`}
                    onClick={() => setSelectedJE(je)}
                  >
                    <span className="je-col-status">
                      <button
                        className={`je-status-btn ${st}`}
                        onClick={(e) => { e.stopPropagation(); cycleJEStatus(je.id); }}
                        title="Cycle status"
                      >
                        {statusIcon(st)}
                      </button>
                      <span className="je-status-label">{statusLabel(st)}</span>
                    </span>
                    <span className="je-col-id">{je.id.toUpperCase()}</span>
                    <span className="je-col-desc">{je.description}</span>
                    <span className="je-col-type">
                      <span className={`je-type-badge ${je.type}`}>{je.type}</span>
                    </span>
                    <span className="je-col-amount">{fmtFull(je.amount)}</span>
                    <span className="je-col-date">{je.date}</span>
                    <span className="je-col-owner">
                      <div className="avatar-sm" style={{ background: preparer.color }}>{preparer.avatar}</div>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ─── TRIAL BALANCE VIEW ─── */}
        {activeView === 'trial_balance' && (
          <div className="view-content">
            <div className="view-header">
              <h1>Trial Balance</h1>
              <div className="view-header-right">
                <div className="tb-toggle">
                  <button className={tbView === 'unadjusted' ? 'active' : ''} onClick={() => setTbView('unadjusted')}>Unadjusted</button>
                  <button className={tbView === 'adjusted' ? 'active' : ''} onClick={() => setTbView('adjusted')}>Adjusted</button>
                </div>
              </div>
            </div>

            <div className="tb-balance-check">
              <span>Total Debits: <strong>{fmtFull(tbTotals.debit)}</strong></span>
              <span className={tbTotals.debit === tbTotals.credit ? 'tb-balanced' : 'tb-imbalanced'}>
                {tbTotals.debit === tbTotals.credit ? '✓ Balanced' : '✗ Imbalanced'}
              </span>
              <span>Total Credits: <strong>{fmtFull(tbTotals.credit)}</strong></span>
            </div>

            <div className="tb-table">
              <div className="tb-table-header">
                <span className="tb-col-code">Code</span>
                <span className="tb-col-name">Account Name</span>
                <span className="tb-col-debit">Debit</span>
                <span className="tb-col-credit">Credit</span>
              </div>
              {['Assets', 'Liabilities', 'Equity', 'Revenue', 'Expenses'].map(category => {
                const rows = adjustedTB.filter(r => r.category === category);
                if (rows.length === 0) return null;
                return (
                  <div key={category} className="tb-section">
                    <div className="tb-section-header">{category}</div>
                    {rows.map(row => (
                      <div key={row.code} className="tb-row">
                        <span className="tb-col-code">{row.code}</span>
                        <span className="tb-col-name">{row.name}</span>
                        <span className="tb-col-debit">{row.debit ? fmtFull(row.debit) : ''}</span>
                        <span className="tb-col-credit">{row.credit ? fmtFull(row.credit) : ''}</span>
                      </div>
                    ))}
                  </div>
                );
              })}
              <div className="tb-totals-row">
                <span className="tb-col-code" />
                <span className="tb-col-name"><strong>TOTAL</strong></span>
                <span className="tb-col-debit"><strong>{fmtFull(tbTotals.debit)}</strong></span>
                <span className="tb-col-credit"><strong>{fmtFull(tbTotals.credit)}</strong></span>
              </div>
            </div>
          </div>
        )}

        {/* ─── FINANCIAL STATEMENTS VIEW ─── */}
        {activeView === 'financials' && (
          <div className="view-content">
            <div className="view-header">
              <h1>Financial Statements</h1>
              <div className="view-header-right">
                <div className="tb-toggle">
                  <button className={fsTab === 'pnl' ? 'active' : ''} onClick={() => setFsTab('pnl')}>P&L</button>
                  <button className={fsTab === 'bs' ? 'active' : ''} onClick={() => setFsTab('bs')}>Balance Sheet</button>
                </div>
              </div>
            </div>

            {fsTab === 'pnl' && (
              <div className="fs-statement">
                <div className="fs-title">Statement of Profit & Loss</div>
                <div className="fs-subtitle">For the year ended 31st March 2026</div>
                <div className="fs-table">
                  <div className="fs-row header">
                    <span className="fs-col-item">Particulars</span>
                    <span className="fs-col-amount">Amount (₹)</span>
                  </div>
                  <div className="fs-row">
                    <span className="fs-col-item bold">I. Revenue from Operations</span>
                    <span className="fs-col-amount bold">{fmt(financials.revenue)}</span>
                  </div>
                  <div className="fs-row">
                    <span className="fs-col-item bold">II. Other Income</span>
                    <span className="fs-col-amount">{fmt(financials.otherIncome)}</span>
                  </div>
                  <div className="fs-row total">
                    <span className="fs-col-item">III. Total Revenue (I + II)</span>
                    <span className="fs-col-amount">{fmt(financials.revenue + financials.otherIncome)}</span>
                  </div>
                  <div className="fs-row section-header">
                    <span className="fs-col-item">IV. Expenses</span>
                    <span className="fs-col-amount" />
                  </div>
                  <div className="fs-row indent">
                    <span className="fs-col-item">Cost of Materials Consumed</span>
                    <span className="fs-col-amount">{fmt(financials.cogs)}</span>
                  </div>
                  <div className="fs-row indent">
                    <span className="fs-col-item">Employee Benefit Expense</span>
                    <span className="fs-col-amount">{fmt(financials.employeeCost)}</span>
                  </div>
                  <div className="fs-row indent">
                    <span className="fs-col-item">Depreciation & Amortisation</span>
                    <span className="fs-col-amount">{fmt(financials.depreciation)}</span>
                  </div>
                  <div className="fs-row indent">
                    <span className="fs-col-item">Other Expenses</span>
                    <span className="fs-col-amount">{fmt(financials.otherExpenses)}</span>
                  </div>
                  <div className="fs-row indent">
                    <span className="fs-col-item">Finance Costs</span>
                    <span className="fs-col-amount">{fmt(financials.financeCosts)}</span>
                  </div>
                  <div className="fs-row total">
                    <span className="fs-col-item">Total Expenses</span>
                    <span className="fs-col-amount">{fmt(financials.cogs + financials.employeeCost + financials.depreciation + financials.otherExpenses + financials.financeCosts)}</span>
                  </div>
                  <div className="fs-row highlight">
                    <span className="fs-col-item bold">V. Profit Before Tax (III - IV)</span>
                    <span className="fs-col-amount bold">{fmt(financials.pbt)}</span>
                  </div>
                  <div className="fs-row indent">
                    <span className="fs-col-item">Tax Expense</span>
                    <span className="fs-col-amount">{fmt(financials.tax)}</span>
                  </div>
                  <div className="fs-row highlight big">
                    <span className="fs-col-item bold">VI. Profit After Tax</span>
                    <span className="fs-col-amount bold">{fmt(financials.pat)}</span>
                  </div>
                </div>
              </div>
            )}

            {fsTab === 'bs' && (
              <div className="fs-statement">
                <div className="fs-title">Balance Sheet</div>
                <div className="fs-subtitle">As at 31st March 2026</div>
                <div className="fs-two-col">
                  {/* Assets */}
                  <div className="fs-col">
                    <div className="fs-table">
                      <div className="fs-row header">
                        <span className="fs-col-item">ASSETS</span>
                        <span className="fs-col-amount">Amount (₹)</span>
                      </div>
                      <div className="fs-row section-header"><span className="fs-col-item">Non-Current Assets</span></div>
                      <div className="fs-row indent">
                        <span className="fs-col-item">Property, Plant & Equipment</span>
                        <span className="fs-col-amount">{fmt(financials.fixedAssets)}</span>
                      </div>
                      <div className="fs-row section-header"><span className="fs-col-item">Current Assets</span></div>
                      <div className="fs-row indent">
                        <span className="fs-col-item">Current Assets</span>
                        <span className="fs-col-amount">{fmt(financials.currentAssets)}</span>
                      </div>
                      <div className="fs-row total big">
                        <span className="fs-col-item bold">Total Assets</span>
                        <span className="fs-col-amount bold">{fmt(financials.totalAssets)}</span>
                      </div>
                    </div>
                  </div>
                  {/* Liabilities */}
                  <div className="fs-col">
                    <div className="fs-table">
                      <div className="fs-row header">
                        <span className="fs-col-item">EQUITY & LIABILITIES</span>
                        <span className="fs-col-amount">Amount (₹)</span>
                      </div>
                      <div className="fs-row section-header"><span className="fs-col-item">Equity</span></div>
                      <div className="fs-row indent">
                        <span className="fs-col-item">Share Capital + Reserves</span>
                        <span className="fs-col-amount">{fmt(financials.equity)}</span>
                      </div>
                      <div className="fs-row indent">
                        <span className="fs-col-item">Current Year Profit</span>
                        <span className="fs-col-amount">{fmt(financials.pat)}</span>
                      </div>
                      <div className="fs-row section-header"><span className="fs-col-item">Non-Current Liabilities</span></div>
                      <div className="fs-row indent">
                        <span className="fs-col-item">Long-Term Borrowings</span>
                        <span className="fs-col-amount">{fmt(financials.ncLiabilities)}</span>
                      </div>
                      <div className="fs-row section-header"><span className="fs-col-item">Current Liabilities</span></div>
                      <div className="fs-row indent">
                        <span className="fs-col-item">Current Liabilities</span>
                        <span className="fs-col-amount">{fmt(financials.currentLiabilities)}</span>
                      </div>
                      <div className="fs-row total big">
                        <span className="fs-col-item bold">Total Equity & Liabilities</span>
                        <span className="fs-col-amount bold">{fmt(financials.totalLiabilities)}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Flux Analysis */}
            <div className="section-title" style={{ marginTop: 24 }}>Flux Analysis (March vs Feb)</div>
            <div className="flux-table">
              <div className="flux-header">
                <span className="flux-col-item">Line Item</span>
                <span className="flux-col-num">Current</span>
                <span className="flux-col-num">Prior Month</span>
                <span className="flux-col-num">Variance</span>
                <span className="flux-col-num">Var %</span>
                <span className="flux-col-num">Budget</span>
                <span className="flux-col-num">Bud Var %</span>
              </div>
              {fluxData.map((row, i) => {
                const variance = row.current - row.prior;
                const varPct = row.prior ? ((variance / row.prior) * 100).toFixed(1) : 0;
                const budVar = row.budget ? (((row.current - row.budget) / row.budget) * 100).toFixed(1) : 0;
                const isExpense = !row.line.includes('Revenue');
                const isBad = isExpense ? variance > 0 && Math.abs(varPct) > 5 : variance < 0 && Math.abs(varPct) > 5;
                return (
                  <div key={i} className={`flux-row ${isBad ? 'flagged' : ''}`}>
                    <span className="flux-col-item">{row.line}</span>
                    <span className="flux-col-num">{fmt(row.current)}</span>
                    <span className="flux-col-num">{fmt(row.prior)}</span>
                    <span className={`flux-col-num ${variance > 0 ? 'positive' : 'negative'}`}>{fmt(variance)}</span>
                    <span className={`flux-col-num ${isBad ? 'flagged-text' : ''}`}>{varPct}%</span>
                    <span className="flux-col-num">{fmt(row.budget)}</span>
                    <span className="flux-col-num">{budVar}%</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </main>

      {/* ═══ RIGHT PANEL: Detail Slider ═══ */}
      {hasDetail && (
        <aside className="right-panel">
          <button className="close-detail-btn" onClick={closeDetail}>✕</button>

          {/* Task Detail */}
          {selectedTask && (
            <div className="detail-content">
              <div className="detail-section-title">Task Detail</div>
              <h2 className="detail-title">{selectedTask.task}</h2>
              <div className="detail-meta-grid">
                <div className="detail-meta-item">
                  <span className="meta-label">Phase</span>
                  <span className="meta-value">{phaseConfig[selectedTask.phase]?.label}</span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Status</span>
                  <span className={`status-badge ${taskStatuses[selectedTask.id]}`}>
                    {statusIcon(taskStatuses[selectedTask.id])} {statusLabel(taskStatuses[selectedTask.id])}
                  </span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Priority</span>
                  <span className="meta-value">
                    <span className="priority-dot" style={{ background: priorityColor(selectedTask.priority) }} />
                    {selectedTask.priority}
                  </span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Due Date</span>
                  <span className="meta-value">{selectedTask.dueDate}</span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Owner</span>
                  <div className="meta-member">
                    <div className="avatar-sm" style={{ background: getMember(selectedTask.owner).color }}>
                      {getMember(selectedTask.owner).avatar}
                    </div>
                    <span>{getMember(selectedTask.owner).name}</span>
                  </div>
                </div>
                {selectedTask.reviewer && (
                  <div className="detail-meta-item">
                    <span className="meta-label">Reviewer</span>
                    <div className="meta-member">
                      <div className="avatar-sm" style={{ background: getMember(selectedTask.reviewer).color }}>
                        {getMember(selectedTask.reviewer).avatar}
                      </div>
                      <span>{getMember(selectedTask.reviewer).name}</span>
                    </div>
                  </div>
                )}
                {selectedTask.completedAt && (
                  <div className="detail-meta-item">
                    <span className="meta-label">Completed At</span>
                    <span className="meta-value">{selectedTask.completedAt}</span>
                  </div>
                )}
              </div>
              <div className="detail-actions">
                <button className="action-btn primary" onClick={() => cycleTaskStatus(selectedTask.id)}>
                  {taskStatuses[selectedTask.id] === 'completed' ? 'Reopen' : taskStatuses[selectedTask.id] === 'in_progress' ? 'Mark Complete' : 'Start Task'}
                </button>
              </div>
            </div>
          )}

          {/* Reconciliation Detail */}
          {selectedRecon && (
            <div className="detail-content">
              <div className="detail-section-title">Reconciliation Detail</div>
              <h2 className="detail-title">{selectedRecon.account}</h2>
              <div className={`recon-type-badge ${selectedRecon.type}`} style={{ marginBottom: 16 }}>{selectedRecon.type.replace('_', ' ')}</div>

              {selectedRecon.status !== 'not_started' && (
                <>
                  <div className="recon-detail-balances">
                    <div className="rdb-row">
                      <span>GL Balance</span>
                      <span className="rdb-amount">{fmtFull(selectedRecon.glBalance)}</span>
                    </div>
                    <div className="rdb-row">
                      <span>Supporting Balance</span>
                      <span className="rdb-amount">{fmtFull(selectedRecon.supportingBalance)}</span>
                    </div>
                    <div className="rdb-row diff">
                      <span>Difference</span>
                      <span className="rdb-amount">{fmtFull(selectedRecon.glBalance - selectedRecon.supportingBalance)}</span>
                    </div>
                  </div>

                  {selectedRecon.reconcilingItems.length > 0 && (
                    <>
                      <div className="section-title" style={{ marginTop: 20 }}>Reconciling Items</div>
                      <div className="recon-items-list">
                        {selectedRecon.reconcilingItems.map((item, i) => (
                          <div key={i} className="recon-item-row">
                            <span className="ri-desc">{item.desc}</span>
                            <span className={`ri-amount ${item.amount < 0 ? 'negative' : 'positive'}`}>
                              {fmtFull(item.amount)}
                            </span>
                          </div>
                        ))}
                        <div className="recon-item-row total">
                          <span className="ri-desc"><strong>Net Reconciling Items</strong></span>
                          <span className="ri-amount">
                            <strong>{fmtFull(selectedRecon.reconcilingItems.reduce((s, i) => s + i.amount, 0))}</strong>
                          </span>
                        </div>
                        <div className="recon-item-row total">
                          <span className="ri-desc"><strong>Adjusted Balance (GL + Items)</strong></span>
                          <span className="ri-amount">
                            <strong>{fmtFull(selectedRecon.glBalance + selectedRecon.reconcilingItems.reduce((s, i) => s + i.amount, 0))}</strong>
                          </span>
                        </div>
                      </div>
                    </>
                  )}
                </>
              )}

              <div className="detail-meta-grid" style={{ marginTop: 20 }}>
                <div className="detail-meta-item">
                  <span className="meta-label">Status</span>
                  <span className={`recon-status-badge ${selectedRecon.status}`}>{statusLabel(selectedRecon.status)}</span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Owner</span>
                  <div className="meta-member">
                    <div className="avatar-sm" style={{ background: getMember(selectedRecon.owner).color }}>
                      {getMember(selectedRecon.owner).avatar}
                    </div>
                    <span>{getMember(selectedRecon.owner).name}</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Journal Entry Detail */}
          {selectedJE && (
            <div className="detail-content">
              <div className="detail-section-title">Journal Entry Detail</div>
              <h2 className="detail-title">{selectedJE.description}</h2>
              <div className="detail-meta-grid">
                <div className="detail-meta-item">
                  <span className="meta-label">ID</span>
                  <span className="meta-value">{selectedJE.id.toUpperCase()}</span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Type</span>
                  <span className={`je-type-badge ${selectedJE.type}`}>{selectedJE.type}</span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Status</span>
                  <span className={`status-badge ${jeStatuses[selectedJE.id]}`}>
                    {statusIcon(jeStatuses[selectedJE.id])} {statusLabel(jeStatuses[selectedJE.id])}
                  </span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Date</span>
                  <span className="meta-value">{selectedJE.date}</span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Amount</span>
                  <span className="meta-value">{fmtFull(selectedJE.amount)}</span>
                </div>
                <div className="detail-meta-item">
                  <span className="meta-label">Preparer</span>
                  <div className="meta-member">
                    <div className="avatar-sm" style={{ background: getMember(selectedJE.preparedBy).color }}>
                      {getMember(selectedJE.preparedBy).avatar}
                    </div>
                    <span>{getMember(selectedJE.preparedBy).name}</span>
                  </div>
                </div>
              </div>

              <div className="section-title" style={{ marginTop: 20 }}>Entry Lines</div>
              <div className="je-lines-table">
                <div className="je-lines-header">
                  <span className="jl-account">Account</span>
                  <span className="jl-debit">Debit</span>
                  <span className="jl-credit">Credit</span>
                </div>
                {selectedJE.lines.map((line, i) => (
                  <div key={i} className="je-lines-row">
                    <span className="jl-account">{line.account}</span>
                    <span className="jl-debit">{line.debit ? fmtFull(line.debit) : ''}</span>
                    <span className="jl-credit">{line.credit ? fmtFull(line.credit) : ''}</span>
                  </div>
                ))}
                <div className="je-lines-row total">
                  <span className="jl-account"><strong>Total</strong></span>
                  <span className="jl-debit"><strong>{fmtFull(selectedJE.lines.reduce((s, l) => s + l.debit, 0))}</strong></span>
                  <span className="jl-credit"><strong>{fmtFull(selectedJE.lines.reduce((s, l) => s + l.credit, 0))}</strong></span>
                </div>
              </div>

              <div className="detail-actions">
                <button className="action-btn primary" onClick={() => cycleJEStatus(selectedJE.id)}>
                  {jeStatuses[selectedJE.id] === 'not_started' ? 'Create Draft' :
                   jeStatuses[selectedJE.id] === 'draft' ? 'Submit for Review' :
                   jeStatuses[selectedJE.id] === 'review' ? 'Approve & Post' : 'Reopen'}
                </button>
              </div>
            </div>
          )}
        </aside>
      )}

      {/* ═══ AI Assistant Panel ═══ */}
      {showAIPanel && (
        <div className="ai-panel-overlay" onClick={() => setShowAIPanel(false)}>
          <div className="ai-panel" onClick={e => e.stopPropagation()}>
            <div className="ai-panel-header">
              <img src={lekhaLogo} className="ai-logo" alt="" />
              <span>Lekha AI Assistant</span>
              <button className="ai-panel-close" onClick={() => setShowAIPanel(false)}>✕</button>
            </div>
            <div className="ai-panel-body">
              <div className="ai-message bot">
                <p>Hi! I'm your AI book close assistant. Here's what I can help with:</p>
                <ul>
                  <li><strong>3 reconciliations</strong> are in progress — I found 2 unrecorded credit card items and an intercompany timing difference</li>
                  <li><strong>10 journal entries</strong> are pending — I can auto-draft depreciation, prepaid amortization, and standard accruals</li>
                  <li><strong>Other Expenses</strong> are 12.7% above prior month — want me to investigate?</li>
                </ul>
              </div>
              <div className="ai-suggestions">
                <button className="ai-suggest-btn">Auto-post recurring JEs</button>
                <button className="ai-suggest-btn">Draft accrual entries</button>
                <button className="ai-suggest-btn">Explain Other Expenses variance</button>
                <button className="ai-suggest-btn">Run all reconciliation checks</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
