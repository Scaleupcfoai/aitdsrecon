// ============================================================
// LEKHA AI - BOOK CLOSE DEMO - MOCK DATA
// Simulates a mid-size Indian company: "Prism Apparels Pvt. Ltd."
// FY 2025-26, March 2026 month-end close
// ============================================================

// --- TEAM MEMBERS & ROLES ---
export const teamMembers = [
  { id: 'u1', name: 'Ashish Mehta', role: 'Controller', avatar: 'AM', color: '#58a6ff' },
  { id: 'u2', name: 'Priya Sharma', role: 'Senior Accountant', avatar: 'PS', color: '#bc8cff' },
  { id: 'u3', name: 'Rahul Verma', role: 'Staff Accountant', avatar: 'RV', color: '#39d2c0' },
  { id: 'u4', name: 'Sneha Patel', role: 'AP/AR Clerk', avatar: 'SP', color: '#f78166' },
  { id: 'u5', name: 'Vikram Singh', role: 'Payroll', avatar: 'VS', color: '#e3b341' },
  { id: 'u6', name: 'Neha Gupta', role: 'CFO', avatar: 'NG', color: '#ff7b72' },
];

// --- CLOSE PERIOD ---
export const closePeriod = {
  month: 'March 2026',
  fy: 'FY 2025-26',
  type: 'Year-End',
  startDate: '2026-04-01',
  targetDate: '2026-04-10',
  daysElapsed: 5,
  totalDays: 10,
  status: 'in_progress',
};

// --- CLOSE CHECKLIST (47 tasks grouped by phase) ---
export const closeChecklist = [
  // Phase 1: Pre-Close
  {
    id: 't01', phase: 'pre_close', task: 'Distribute close calendar to all stakeholders',
    owner: 'u1', dueDate: '2026-04-01', status: 'completed', completedAt: '2026-04-01T09:30:00',
    reviewer: 'u6', reviewStatus: 'approved', priority: 'high',
  },
  {
    id: 't02', phase: 'pre_close', task: 'Send reminders for expense report submission',
    owner: 'u2', dueDate: '2026-04-01', status: 'completed', completedAt: '2026-04-01T10:15:00',
    reviewer: null, reviewStatus: null, priority: 'medium',
  },
  {
    id: 't03', phase: 'pre_close', task: 'Confirm all payroll runs processed and posted',
    owner: 'u5', dueDate: '2026-04-02', status: 'completed', completedAt: '2026-04-02T14:00:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'high',
  },
  {
    id: 't04', phase: 'pre_close', task: 'Import bank feeds & credit card transactions',
    owner: 'u3', dueDate: '2026-04-02', status: 'completed', completedAt: '2026-04-02T11:30:00',
    reviewer: null, reviewStatus: null, priority: 'high',
  },
  {
    id: 't05', phase: 'pre_close', task: 'Confirm AP invoices received by cutoff are entered',
    owner: 'u4', dueDate: '2026-04-02', status: 'completed', completedAt: '2026-04-02T16:00:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'high',
  },
  {
    id: 't06', phase: 'pre_close', task: 'Confirm all AR invoices for the period are generated',
    owner: 'u4', dueDate: '2026-04-02', status: 'completed', completedAt: '2026-04-02T17:00:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'high',
  },
  {
    id: 't07', phase: 'pre_close', task: 'Review open POs for received but uninvoiced goods',
    owner: 'u4', dueDate: '2026-04-02', status: 'completed', completedAt: '2026-04-03T09:00:00',
    reviewer: null, reviewStatus: null, priority: 'medium',
  },

  // Phase 2: Sub-Ledger Close
  {
    id: 't08', phase: 'subledger_close', task: 'Close AP sub-ledger; reconcile to GL',
    owner: 'u4', dueDate: '2026-04-03', status: 'completed', completedAt: '2026-04-03T15:00:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'critical',
  },
  {
    id: 't09', phase: 'subledger_close', task: 'Close AR sub-ledger; reconcile to GL',
    owner: 'u4', dueDate: '2026-04-03', status: 'completed', completedAt: '2026-04-03T16:30:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'critical',
  },
  {
    id: 't10', phase: 'subledger_close', task: 'Close inventory sub-ledger; reconcile to GL',
    owner: 'u3', dueDate: '2026-04-04', status: 'completed', completedAt: '2026-04-04T11:00:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'critical',
  },
  {
    id: 't11', phase: 'subledger_close', task: 'Close fixed asset sub-ledger; reconcile to GL',
    owner: 'u3', dueDate: '2026-04-04', status: 'completed', completedAt: '2026-04-04T14:00:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'critical',
  },
  {
    id: 't12', phase: 'subledger_close', task: 'Close payroll sub-ledger; reconcile to GL',
    owner: 'u5', dueDate: '2026-04-04', status: 'completed', completedAt: '2026-04-04T16:00:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'critical',
  },

  // Phase 3: Reconciliations
  {
    id: 't13', phase: 'reconciliation', task: 'Bank reconciliation — HDFC Current A/c',
    owner: 'u3', dueDate: '2026-04-04', status: 'completed', completedAt: '2026-04-04T12:00:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'critical', reconId: 'r1',
  },
  {
    id: 't14', phase: 'reconciliation', task: 'Bank reconciliation — ICICI Savings A/c',
    owner: 'u3', dueDate: '2026-04-04', status: 'completed', completedAt: '2026-04-04T14:30:00',
    reviewer: 'u2', reviewStatus: 'approved', priority: 'critical', reconId: 'r2',
  },
  {
    id: 't15', phase: 'reconciliation', task: 'Credit card reconciliation — Amex Corporate',
    owner: 'u3', dueDate: '2026-04-05', status: 'in_progress', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'high', reconId: 'r3',
  },
  {
    id: 't16', phase: 'reconciliation', task: 'Intercompany reconciliation — Prism Exports',
    owner: 'u2', dueDate: '2026-04-05', status: 'in_progress', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'critical', reconId: 'r4',
  },
  {
    id: 't17', phase: 'reconciliation', task: 'Prepaid expense reconciliation',
    owner: 'u3', dueDate: '2026-04-05', status: 'in_progress', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'high', reconId: 'r5',
  },
  {
    id: 't18', phase: 'reconciliation', task: 'Accrued liabilities reconciliation',
    owner: 'u2', dueDate: '2026-04-06', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'high', reconId: 'r6',
  },
  {
    id: 't19', phase: 'reconciliation', task: 'TDS payable reconciliation',
    owner: 'u3', dueDate: '2026-04-06', status: 'not_started', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'high', reconId: 'r7',
  },
  {
    id: 't20', phase: 'reconciliation', task: 'GST reconciliation (GSTR-2B vs Books)',
    owner: 'u2', dueDate: '2026-04-06', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'critical', reconId: 'r8',
  },
  {
    id: 't21', phase: 'reconciliation', task: 'Loan balance reconciliation — Term Loan',
    owner: 'u3', dueDate: '2026-04-06', status: 'not_started', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'medium', reconId: 'r9',
  },

  // Phase 4: Adjusting Journal Entries
  {
    id: 't22', phase: 'adjusting_entries', task: 'Post depreciation entries (all asset classes)',
    owner: 'u3', dueDate: '2026-04-06', status: 'in_progress', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'critical', jeId: 'je1',
  },
  {
    id: 't23', phase: 'adjusting_entries', task: 'Post prepaid insurance amortization',
    owner: 'u3', dueDate: '2026-04-06', status: 'not_started', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'high', jeId: 'je2',
  },
  {
    id: 't24', phase: 'adjusting_entries', task: 'Record accrued salary & wages (partial March)',
    owner: 'u5', dueDate: '2026-04-06', status: 'not_started', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'critical', jeId: 'je3',
  },
  {
    id: 't25', phase: 'adjusting_entries', task: 'Record accrued professional fees',
    owner: 'u2', dueDate: '2026-04-07', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'high', jeId: 'je4',
  },
  {
    id: 't26', phase: 'adjusting_entries', task: 'Record accrued utilities (electricity, internet)',
    owner: 'u3', dueDate: '2026-04-07', status: 'not_started', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'medium', jeId: 'je5',
  },
  {
    id: 't27', phase: 'adjusting_entries', task: 'Adjust bad debt allowance (AR aging review)',
    owner: 'u2', dueDate: '2026-04-07', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'high', jeId: 'je6',
  },
  {
    id: 't28', phase: 'adjusting_entries', task: 'Post reclassification entries (miscoded expenses)',
    owner: 'u3', dueDate: '2026-04-07', status: 'not_started', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'medium', jeId: 'je7',
  },
  {
    id: 't29', phase: 'adjusting_entries', task: 'Reverse prior-month accruals',
    owner: 'u3', dueDate: '2026-04-07', status: 'not_started', completedAt: null,
    reviewer: 'u2', reviewStatus: null, priority: 'high', jeId: 'je8',
  },
  {
    id: 't30', phase: 'adjusting_entries', task: 'Record inventory write-down for obsolete stock',
    owner: 'u2', dueDate: '2026-04-07', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'medium', jeId: 'je9',
  },
  {
    id: 't31', phase: 'adjusting_entries', task: 'Book income tax provision (year-end)',
    owner: 'u1', dueDate: '2026-04-08', status: 'not_started', completedAt: null,
    reviewer: 'u6', reviewStatus: null, priority: 'critical', jeId: 'je10',
  },

  // Phase 5: Trial Balance & Review
  {
    id: 't32', phase: 'review', task: 'Generate adjusted trial balance; verify debits = credits',
    owner: 'u2', dueDate: '2026-04-08', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'critical',
  },
  {
    id: 't33', phase: 'review', task: 'Flux analysis: actual vs. prior month',
    owner: 'u2', dueDate: '2026-04-08', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'high',
  },
  {
    id: 't34', phase: 'review', task: 'Flux analysis: actual vs. budget',
    owner: 'u2', dueDate: '2026-04-08', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'high',
  },
  {
    id: 't35', phase: 'review', task: 'Investigate & document material variances',
    owner: 'u2', dueDate: '2026-04-09', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'high',
  },
  {
    id: 't36', phase: 'review', task: 'Review all journal entries for proper documentation',
    owner: 'u1', dueDate: '2026-04-09', status: 'not_started', completedAt: null,
    reviewer: 'u6', reviewStatus: null, priority: 'critical',
  },

  // Phase 6: Financial Statements
  {
    id: 't37', phase: 'financials', task: 'Prepare Income Statement (P&L)',
    owner: 'u2', dueDate: '2026-04-09', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'critical',
  },
  {
    id: 't38', phase: 'financials', task: 'Prepare Balance Sheet',
    owner: 'u2', dueDate: '2026-04-09', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'critical',
  },
  {
    id: 't39', phase: 'financials', task: 'Prepare Cash Flow Statement',
    owner: 'u2', dueDate: '2026-04-10', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'high',
  },
  {
    id: 't40', phase: 'financials', task: 'Prepare management reporting package with commentary',
    owner: 'u1', dueDate: '2026-04-10', status: 'not_started', completedAt: null,
    reviewer: 'u6', reviewStatus: null, priority: 'high',
  },
  {
    id: 't41', phase: 'financials', task: 'Controller reviews & approves financial statements',
    owner: 'u1', dueDate: '2026-04-10', status: 'not_started', completedAt: null,
    reviewer: 'u6', reviewStatus: null, priority: 'critical',
  },
  {
    id: 't42', phase: 'financials', task: 'CFO reviews financial package',
    owner: 'u6', dueDate: '2026-04-10', status: 'not_started', completedAt: null,
    reviewer: null, reviewStatus: null, priority: 'critical',
  },

  // Phase 7: Close & Archive
  {
    id: 't43', phase: 'close_archive', task: 'Lock accounting period in ERP',
    owner: 'u1', dueDate: '2026-04-10', status: 'not_started', completedAt: null,
    reviewer: 'u6', reviewStatus: null, priority: 'critical',
  },
  {
    id: 't44', phase: 'close_archive', task: 'Close revenue/expense accounts to Retained Earnings',
    owner: 'u2', dueDate: '2026-04-10', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'critical',
  },
  {
    id: 't45', phase: 'close_archive', task: 'Generate post-closing trial balance',
    owner: 'u2', dueDate: '2026-04-10', status: 'not_started', completedAt: null,
    reviewer: 'u1', reviewStatus: null, priority: 'high',
  },
  {
    id: 't46', phase: 'close_archive', task: 'Archive all workpapers and documentation',
    owner: 'u3', dueDate: '2026-04-10', status: 'not_started', completedAt: null,
    reviewer: null, reviewStatus: null, priority: 'medium',
  },
  {
    id: 't47', phase: 'close_archive', task: 'Post-close debrief: identify process improvements',
    owner: 'u1', dueDate: '2026-04-11', status: 'not_started', completedAt: null,
    reviewer: null, reviewStatus: null, priority: 'low',
  },
];

export const phaseConfig = {
  pre_close: { label: 'Pre-Close', icon: '1', color: '#39d2c0', order: 0 },
  subledger_close: { label: 'Sub-Ledger Close', icon: '2', color: '#58a6ff', order: 1 },
  reconciliation: { label: 'Reconciliations', icon: '3', color: '#bc8cff', order: 2 },
  adjusting_entries: { label: 'Adjusting Entries', icon: '4', color: '#e3b341', order: 3 },
  review: { label: 'Review & Analysis', icon: '5', color: '#f78166', order: 4 },
  financials: { label: 'Financial Statements', icon: '6', color: '#ff7b72', order: 5 },
  close_archive: { label: 'Close & Archive', icon: '7', color: '#3fb950', order: 6 },
};

// --- RECONCILIATION DATA ---
export const reconciliations = [
  {
    id: 'r1', account: 'HDFC Current A/c (001-234567)', type: 'bank',
    glBalance: 2847562.50, supportingBalance: 2892341.00,
    reconcilingItems: [
      { desc: 'Cheque #4521 — Fabric House (outstanding)', amount: -35000, type: 'outstanding_check' },
      { desc: 'Cheque #4518 — Dye Works Ltd (outstanding)', amount: -12450, type: 'outstanding_check' },
      { desc: 'NEFT from Lifestyle Int. (deposit in transit)', amount: 85000, type: 'deposit_in_transit' },
      { desc: 'Bank charges March (not yet recorded)', amount: -1578.50, type: 'bank_charge' },
      { desc: 'Interest credit (not yet recorded)', amount: 3250, type: 'interest' },
      { desc: 'NACH bounce — Raj Textiles (not yet recorded)', amount: -84000, type: 'nsf' },
    ],
    status: 'completed', variance: 0, owner: 'u3', reviewer: 'u2',
  },
  {
    id: 'r2', account: 'ICICI Savings A/c (045-789012)', type: 'bank',
    glBalance: 548230.00, supportingBalance: 548230.00,
    reconcilingItems: [],
    status: 'completed', variance: 0, owner: 'u3', reviewer: 'u2',
  },
  {
    id: 'r3', account: 'Amex Corporate Card', type: 'credit_card',
    glBalance: 187450.00, supportingBalance: 194320.00,
    reconcilingItems: [
      { desc: 'Travel expense — Ashish (not yet recorded)', amount: 4520, type: 'unrecorded' },
      { desc: 'Software subscription renewal (not yet recorded)', amount: 2350, type: 'unrecorded' },
    ],
    status: 'in_progress', variance: 6870, owner: 'u3', reviewer: 'u2',
  },
  {
    id: 'r4', account: 'Intercompany — Prism Exports Ltd.', type: 'intercompany',
    glBalance: 1245000.00, supportingBalance: 1320000.00,
    reconcilingItems: [
      { desc: 'Invoice #PE-2026-089 (timing difference)', amount: 45000, type: 'timing' },
      { desc: 'Debit note #DN-045 (dispute under review)', amount: 30000, type: 'disputed' },
    ],
    status: 'in_progress', variance: 75000, owner: 'u2', reviewer: 'u1',
  },
  {
    id: 'r5', account: 'Prepaid Expenses', type: 'prepaid',
    glBalance: 324500.00, supportingBalance: 310200.00,
    reconcilingItems: [
      { desc: 'Insurance premium amortization not posted', amount: -14300, type: 'unposted_je' },
    ],
    status: 'in_progress', variance: 14300, owner: 'u3', reviewer: 'u2',
  },
  {
    id: 'r6', account: 'Accrued Liabilities', type: 'accrual',
    glBalance: 0, supportingBalance: 0, reconcilingItems: [],
    status: 'not_started', variance: null, owner: 'u2', reviewer: 'u1',
  },
  {
    id: 'r7', account: 'TDS Reconciliation (all sections)', type: 'tax',
    glBalance: 0, supportingBalance: 0, reconcilingItems: [],
    status: 'not_started', variance: null, owner: 'u3', reviewer: 'u2',
  },
  {
    id: 'r8', account: 'GST Input Credit (GSTR-2B vs Books)', type: 'tax',
    glBalance: 0, supportingBalance: 0, reconcilingItems: [],
    status: 'not_started', variance: null, owner: 'u2', reviewer: 'u1',
  },
  {
    id: 'r9', account: 'Term Loan — SBI (TL/2024/00456)', type: 'debt',
    glBalance: 0, supportingBalance: 0, reconcilingItems: [],
    status: 'not_started', variance: null, owner: 'u3', reviewer: 'u2',
  },
];

// --- JOURNAL ENTRIES ---
export const journalEntries = [
  {
    id: 'je1', type: 'recurring', description: 'Monthly depreciation — all asset classes',
    preparedBy: 'u3', reviewedBy: 'u2', status: 'draft',
    date: '2026-03-31', amount: 245800,
    lines: [
      { account: 'Depreciation — Plant & Machinery', debit: 125000, credit: 0 },
      { account: 'Depreciation — Furniture & Fixtures', debit: 18500, credit: 0 },
      { account: 'Depreciation — Vehicles', debit: 35400, credit: 0 },
      { account: 'Depreciation — Computers & IT', debit: 42900, credit: 0 },
      { account: 'Depreciation — Office Equipment', debit: 24000, credit: 0 },
      { account: 'Accumulated Depreciation — P&M', debit: 0, credit: 125000 },
      { account: 'Accumulated Depreciation — F&F', debit: 0, credit: 18500 },
      { account: 'Accumulated Depreciation — Vehicles', debit: 0, credit: 35400 },
      { account: 'Accumulated Depreciation — Computers', debit: 0, credit: 42900 },
      { account: 'Accumulated Depreciation — Office Equip', debit: 0, credit: 24000 },
    ],
  },
  {
    id: 'je2', type: 'recurring', description: 'Prepaid insurance amortization',
    preparedBy: 'u3', reviewedBy: 'u2', status: 'not_started',
    date: '2026-03-31', amount: 14300,
    lines: [
      { account: 'Insurance Expense', debit: 14300, credit: 0 },
      { account: 'Prepaid Insurance', debit: 0, credit: 14300 },
    ],
  },
  {
    id: 'je3', type: 'accrual', description: 'Accrued salary & wages (March 25-31)',
    preparedBy: 'u5', reviewedBy: 'u2', status: 'not_started',
    date: '2026-03-31', amount: 185000,
    lines: [
      { account: 'Salary Expense', debit: 145000, credit: 0 },
      { account: 'PF Employer Contribution', debit: 17400, credit: 0 },
      { account: 'ESI Employer Contribution', debit: 5800, credit: 0 },
      { account: 'Professional Tax Expense', debit: 16800, credit: 0 },
      { account: 'Accrued Salaries Payable', debit: 0, credit: 185000 },
    ],
  },
  {
    id: 'je4', type: 'accrual', description: 'Accrued professional fees — CA & legal',
    preparedBy: 'u2', reviewedBy: 'u1', status: 'not_started',
    date: '2026-03-31', amount: 75000,
    lines: [
      { account: 'Professional Fees', debit: 75000, credit: 0 },
      { account: 'Accrued Expenses', debit: 0, credit: 75000 },
    ],
  },
  {
    id: 'je5', type: 'accrual', description: 'Accrued utilities (electricity, internet, phone)',
    preparedBy: 'u3', reviewedBy: 'u2', status: 'not_started',
    date: '2026-03-31', amount: 42500,
    lines: [
      { account: 'Electricity Expense', debit: 28500, credit: 0 },
      { account: 'Internet & Phone Expense', debit: 14000, credit: 0 },
      { account: 'Accrued Utilities', debit: 0, credit: 42500 },
    ],
  },
  {
    id: 'je6', type: 'non_recurring', description: 'Bad debt allowance adjustment (AR aging)',
    preparedBy: 'u2', reviewedBy: 'u1', status: 'not_started',
    date: '2026-03-31', amount: 125000,
    lines: [
      { account: 'Bad Debt Expense', debit: 125000, credit: 0 },
      { account: 'Allowance for Doubtful Accounts', debit: 0, credit: 125000 },
    ],
  },
  {
    id: 'je7', type: 'reclassification', description: 'Reclassify capex miscoded as repair expense',
    preparedBy: 'u3', reviewedBy: 'u2', status: 'not_started',
    date: '2026-03-31', amount: 89000,
    lines: [
      { account: 'Plant & Machinery (FA)', debit: 89000, credit: 0 },
      { account: 'Repairs & Maintenance', debit: 0, credit: 89000 },
    ],
  },
  {
    id: 'je8', type: 'reversal', description: 'Reverse Feb accrued professional fees',
    preparedBy: 'u3', reviewedBy: 'u2', status: 'not_started',
    date: '2026-03-01', amount: 50000,
    lines: [
      { account: 'Accrued Expenses', debit: 50000, credit: 0 },
      { account: 'Professional Fees', debit: 0, credit: 50000 },
    ],
  },
  {
    id: 'je9', type: 'non_recurring', description: 'Inventory write-down — obsolete fabric stock',
    preparedBy: 'u2', reviewedBy: 'u1', status: 'not_started',
    date: '2026-03-31', amount: 67000,
    lines: [
      { account: 'Inventory Write-Down Expense', debit: 67000, credit: 0 },
      { account: 'Inventory — Raw Materials', debit: 0, credit: 67000 },
    ],
  },
  {
    id: 'je10', type: 'non_recurring', description: 'Income tax provision (year-end)',
    preparedBy: 'u1', reviewedBy: 'u6', status: 'not_started',
    date: '2026-03-31', amount: 890000,
    lines: [
      { account: 'Income Tax Expense', debit: 890000, credit: 0 },
      { account: 'Income Tax Payable', debit: 0, credit: 890000 },
    ],
  },
];

// --- TRIAL BALANCE ---
export const trialBalance = [
  // ASSETS
  { code: '1001', name: 'Cash in Hand', category: 'Assets', subcategory: 'Current Assets', debit: 45230, credit: 0, fsLine: 'Cash & Cash Equivalents' },
  { code: '1002', name: 'HDFC Current A/c', category: 'Assets', subcategory: 'Current Assets', debit: 2847562.50, credit: 0, fsLine: 'Cash & Cash Equivalents' },
  { code: '1003', name: 'ICICI Savings A/c', category: 'Assets', subcategory: 'Current Assets', debit: 548230, credit: 0, fsLine: 'Cash & Cash Equivalents' },
  { code: '1010', name: 'Accounts Receivable', category: 'Assets', subcategory: 'Current Assets', debit: 4250000, credit: 0, fsLine: 'Trade Receivables' },
  { code: '1011', name: 'Allowance for Doubtful Accounts', category: 'Assets', subcategory: 'Current Assets', debit: 0, credit: 175000, fsLine: 'Trade Receivables' },
  { code: '1020', name: 'Inventory — Raw Materials', category: 'Assets', subcategory: 'Current Assets', debit: 3200000, credit: 0, fsLine: 'Inventories' },
  { code: '1021', name: 'Inventory — Finished Goods', category: 'Assets', subcategory: 'Current Assets', debit: 2850000, credit: 0, fsLine: 'Inventories' },
  { code: '1030', name: 'Prepaid Insurance', category: 'Assets', subcategory: 'Current Assets', debit: 171600, credit: 0, fsLine: 'Other Current Assets' },
  { code: '1031', name: 'Prepaid Rent', category: 'Assets', subcategory: 'Current Assets', debit: 150000, credit: 0, fsLine: 'Other Current Assets' },
  { code: '1032', name: 'Advance to Suppliers', category: 'Assets', subcategory: 'Current Assets', debit: 280000, credit: 0, fsLine: 'Other Current Assets' },
  { code: '1033', name: 'TDS Receivable', category: 'Assets', subcategory: 'Current Assets', debit: 142000, credit: 0, fsLine: 'Other Current Assets' },
  { code: '1034', name: 'GST Input Credit', category: 'Assets', subcategory: 'Current Assets', debit: 385000, credit: 0, fsLine: 'Other Current Assets' },
  { code: '1040', name: 'Intercompany Receivable — Prism Exports', category: 'Assets', subcategory: 'Current Assets', debit: 1245000, credit: 0, fsLine: 'Other Current Assets' },
  { code: '1100', name: 'Plant & Machinery (Gross)', category: 'Assets', subcategory: 'Fixed Assets', debit: 4500000, credit: 0, fsLine: 'Property, Plant & Equipment' },
  { code: '1101', name: 'Accumulated Depreciation — P&M', category: 'Assets', subcategory: 'Fixed Assets', debit: 0, credit: 1875000, fsLine: 'Property, Plant & Equipment' },
  { code: '1110', name: 'Furniture & Fixtures (Gross)', category: 'Assets', subcategory: 'Fixed Assets', debit: 650000, credit: 0, fsLine: 'Property, Plant & Equipment' },
  { code: '1111', name: 'Accumulated Depreciation — F&F', category: 'Assets', subcategory: 'Fixed Assets', debit: 0, credit: 312000, fsLine: 'Property, Plant & Equipment' },
  { code: '1120', name: 'Vehicles (Gross)', category: 'Assets', subcategory: 'Fixed Assets', debit: 1200000, credit: 0, fsLine: 'Property, Plant & Equipment' },
  { code: '1121', name: 'Accumulated Depreciation — Vehicles', category: 'Assets', subcategory: 'Fixed Assets', debit: 0, credit: 480000, fsLine: 'Property, Plant & Equipment' },
  { code: '1130', name: 'Computers & IT (Gross)', category: 'Assets', subcategory: 'Fixed Assets', debit: 520000, credit: 0, fsLine: 'Property, Plant & Equipment' },
  { code: '1131', name: 'Accumulated Depreciation — Computers', category: 'Assets', subcategory: 'Fixed Assets', debit: 0, credit: 286000, fsLine: 'Property, Plant & Equipment' },
  { code: '1140', name: 'Office Equipment (Gross)', category: 'Assets', subcategory: 'Fixed Assets', debit: 380000, credit: 0, fsLine: 'Property, Plant & Equipment' },
  { code: '1141', name: 'Accumulated Depreciation — Office Equip', category: 'Assets', subcategory: 'Fixed Assets', debit: 0, credit: 168000, fsLine: 'Property, Plant & Equipment' },

  // LIABILITIES
  { code: '2001', name: 'Accounts Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 3450000, fsLine: 'Trade Payables' },
  { code: '2010', name: 'Accrued Salaries Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 0, fsLine: 'Other Current Liabilities' },
  { code: '2011', name: 'Accrued Expenses', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 50000, fsLine: 'Other Current Liabilities' },
  { code: '2012', name: 'Accrued Utilities', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 0, fsLine: 'Other Current Liabilities' },
  { code: '2020', name: 'TDS Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 134742, fsLine: 'Other Current Liabilities' },
  { code: '2021', name: 'GST Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 245000, fsLine: 'Other Current Liabilities' },
  { code: '2022', name: 'PF Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 52000, fsLine: 'Other Current Liabilities' },
  { code: '2023', name: 'ESI Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 12400, fsLine: 'Other Current Liabilities' },
  { code: '2024', name: 'Professional Tax Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 16800, fsLine: 'Other Current Liabilities' },
  { code: '2030', name: 'Income Tax Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 450000, fsLine: 'Other Current Liabilities' },
  { code: '2040', name: 'Amex Corporate Card Payable', category: 'Liabilities', subcategory: 'Current Liabilities', debit: 0, credit: 187450, fsLine: 'Other Current Liabilities' },
  { code: '2100', name: 'Term Loan — SBI', category: 'Liabilities', subcategory: 'Non-Current Liabilities', debit: 0, credit: 2400000, fsLine: 'Long-Term Borrowings' },
  { code: '2101', name: 'Vehicle Loan — HDFC', category: 'Liabilities', subcategory: 'Non-Current Liabilities', debit: 0, credit: 450000, fsLine: 'Long-Term Borrowings' },

  // EQUITY
  { code: '3001', name: 'Share Capital', category: 'Equity', subcategory: 'Equity', debit: 0, credit: 5000000, fsLine: 'Share Capital' },
  { code: '3002', name: 'Retained Earnings (Opening)', category: 'Equity', subcategory: 'Equity', debit: 0, credit: 3850000, fsLine: 'Retained Earnings' },

  // REVENUE
  { code: '4001', name: 'Sales — Domestic', category: 'Revenue', subcategory: 'Revenue', debit: 0, credit: 12500000, fsLine: 'Revenue from Operations' },
  { code: '4002', name: 'Sales — Export', category: 'Revenue', subcategory: 'Revenue', debit: 0, credit: 1500000, fsLine: 'Revenue from Operations' },
  { code: '4003', name: 'Sales Returns', category: 'Revenue', subcategory: 'Revenue', debit: 320000, credit: 0, fsLine: 'Revenue from Operations' },
  { code: '4010', name: 'Interest Income', category: 'Revenue', subcategory: 'Other Income', debit: 0, credit: 42000, fsLine: 'Other Income' },
  { code: '4011', name: 'Commission Income', category: 'Revenue', subcategory: 'Other Income', debit: 0, credit: 85000, fsLine: 'Other Income' },

  // COGS
  { code: '5001', name: 'Purchases — Raw Materials', category: 'Expenses', subcategory: 'COGS', debit: 7200000, credit: 0, fsLine: 'Cost of Materials Consumed' },
  { code: '5002', name: 'Purchase Returns', category: 'Expenses', subcategory: 'COGS', debit: 0, credit: 180000, fsLine: 'Cost of Materials Consumed' },
  { code: '5003', name: 'Freight Inward', category: 'Expenses', subcategory: 'COGS', debit: 245000, credit: 0, fsLine: 'Cost of Materials Consumed' },
  { code: '5004', name: 'Manufacturing Wages', category: 'Expenses', subcategory: 'COGS', debit: 1850000, credit: 0, fsLine: 'Employee Benefit Expense' },
  { code: '5005', name: 'Factory Overheads', category: 'Expenses', subcategory: 'COGS', debit: 420000, credit: 0, fsLine: 'Other Expenses' },

  // OPERATING EXPENSES
  { code: '6001', name: 'Salary Expense — Admin', category: 'Expenses', subcategory: 'Employee Costs', debit: 2400000, credit: 0, fsLine: 'Employee Benefit Expense' },
  { code: '6002', name: 'PF Employer Contribution', category: 'Expenses', subcategory: 'Employee Costs', debit: 288000, credit: 0, fsLine: 'Employee Benefit Expense' },
  { code: '6003', name: 'ESI Employer Contribution', category: 'Expenses', subcategory: 'Employee Costs', debit: 96000, credit: 0, fsLine: 'Employee Benefit Expense' },
  { code: '6004', name: 'Professional Tax Expense', category: 'Expenses', subcategory: 'Employee Costs', debit: 168000, credit: 0, fsLine: 'Employee Benefit Expense' },
  { code: '6005', name: 'Staff Welfare', category: 'Expenses', subcategory: 'Employee Costs', debit: 65000, credit: 0, fsLine: 'Employee Benefit Expense' },
  { code: '6010', name: 'Rent Expense', category: 'Expenses', subcategory: 'Operating Expenses', debit: 600000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6011', name: 'Insurance Expense', category: 'Expenses', subcategory: 'Operating Expenses', debit: 157300, credit: 0, fsLine: 'Other Expenses' },
  { code: '6012', name: 'Repairs & Maintenance', category: 'Expenses', subcategory: 'Operating Expenses', debit: 289000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6013', name: 'Electricity Expense', category: 'Expenses', subcategory: 'Operating Expenses', debit: 342000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6014', name: 'Internet & Phone Expense', category: 'Expenses', subcategory: 'Operating Expenses', debit: 156000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6015', name: 'Travel & Conveyance', category: 'Expenses', subcategory: 'Operating Expenses', debit: 185000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6016', name: 'Printing & Stationery', category: 'Expenses', subcategory: 'Operating Expenses', debit: 42000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6017', name: 'Professional Fees', category: 'Expenses', subcategory: 'Operating Expenses', debit: 350000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6018', name: 'Freight Outward', category: 'Expenses', subcategory: 'Operating Expenses', debit: 380000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6019', name: 'Bad Debt Expense', category: 'Expenses', subcategory: 'Operating Expenses', debit: 85000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6020', name: 'Commission Expense', category: 'Expenses', subcategory: 'Operating Expenses', debit: 280000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6021', name: 'Advertising & Marketing', category: 'Expenses', subcategory: 'Operating Expenses', debit: 125000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6022', name: 'Bank Charges', category: 'Expenses', subcategory: 'Operating Expenses', debit: 18500, credit: 0, fsLine: 'Other Expenses' },
  { code: '6023', name: 'Miscellaneous Expenses', category: 'Expenses', subcategory: 'Operating Expenses', debit: 35000, credit: 0, fsLine: 'Other Expenses' },
  { code: '6024', name: 'Inventory Write-Down Expense', category: 'Expenses', subcategory: 'Operating Expenses', debit: 0, credit: 0, fsLine: 'Other Expenses' },

  // DEPRECIATION
  { code: '7001', name: 'Depreciation — Plant & Machinery', category: 'Expenses', subcategory: 'Depreciation', debit: 1375000, credit: 0, fsLine: 'Depreciation & Amortisation' },
  { code: '7002', name: 'Depreciation — Furniture & Fixtures', category: 'Expenses', subcategory: 'Depreciation', debit: 203500, credit: 0, fsLine: 'Depreciation & Amortisation' },
  { code: '7003', name: 'Depreciation — Vehicles', category: 'Expenses', subcategory: 'Depreciation', debit: 389400, credit: 0, fsLine: 'Depreciation & Amortisation' },
  { code: '7004', name: 'Depreciation — Computers & IT', category: 'Expenses', subcategory: 'Depreciation', debit: 471900, credit: 0, fsLine: 'Depreciation & Amortisation' },
  { code: '7005', name: 'Depreciation — Office Equipment', category: 'Expenses', subcategory: 'Depreciation', debit: 264000, credit: 0, fsLine: 'Depreciation & Amortisation' },

  // FINANCE COSTS
  { code: '8001', name: 'Interest on Term Loan', category: 'Expenses', subcategory: 'Finance Costs', debit: 216000, credit: 0, fsLine: 'Finance Costs' },
  { code: '8002', name: 'Interest on Vehicle Loan', category: 'Expenses', subcategory: 'Finance Costs', debit: 54000, credit: 0, fsLine: 'Finance Costs' },

  // TAX
  { code: '9001', name: 'Income Tax Expense', category: 'Expenses', subcategory: 'Tax', debit: 0, credit: 0, fsLine: 'Tax Expense' },
];

// --- FLUX ANALYSIS DATA ---
export const fluxData = [
  { line: 'Revenue from Operations', current: 13680000, prior: 12850000, budget: 14000000 },
  { line: 'Cost of Materials Consumed', current: 7265000, prior: 6920000, budget: 7000000 },
  { line: 'Employee Benefit Expense', current: 4867000, prior: 4750000, budget: 4900000 },
  { line: 'Depreciation & Amortisation', current: 2703800, prior: 2703800, budget: 2700000 },
  { line: 'Other Expenses', current: 2647800, prior: 2350000, budget: 2500000 },
  { line: 'Finance Costs', current: 270000, prior: 270000, budget: 270000 },
];

// --- ACTIVITY LOG ---
export const activityLog = [
  { time: '2026-04-05 16:45', user: 'u2', action: 'Started intercompany reconciliation', type: 'recon' },
  { time: '2026-04-05 15:30', user: 'u3', action: 'Credit card recon — 2 unrecorded items found', type: 'recon' },
  { time: '2026-04-05 14:00', user: 'u3', action: 'Started prepaid expense reconciliation', type: 'recon' },
  { time: '2026-04-05 11:00', user: 'u3', action: 'Created draft JE: Monthly depreciation', type: 'journal' },
  { time: '2026-04-04 16:00', user: 'u5', action: 'Payroll sub-ledger closed & reconciled', type: 'task' },
  { time: '2026-04-04 14:30', user: 'u3', action: 'Bank recon completed — ICICI (no differences)', type: 'recon' },
  { time: '2026-04-04 14:00', user: 'u3', action: 'Fixed asset sub-ledger closed & reconciled', type: 'task' },
  { time: '2026-04-04 12:00', user: 'u3', action: 'Bank recon completed — HDFC (6 items reconciled)', type: 'recon' },
  { time: '2026-04-04 11:00', user: 'u3', action: 'Inventory sub-ledger closed & reconciled', type: 'task' },
  { time: '2026-04-03 16:30', user: 'u4', action: 'AR sub-ledger closed & reconciled', type: 'task' },
  { time: '2026-04-03 15:00', user: 'u4', action: 'AP sub-ledger closed & reconciled', type: 'task' },
];
