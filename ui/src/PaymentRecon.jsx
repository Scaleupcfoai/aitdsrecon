import { useState, useRef, useEffect, useMemo } from 'react';
import { transactions, issueCategories, chatSuggestions } from './data/paymentMockData';
import './payment-recon.css';

const fmt = (n) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n);
const fmt2 = (n) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(n);

const statusLabels = {
  matched: 'Matched', invoice_missing: 'Invoice Missing', payment_failed: 'Payment Failed',
  double_payment: 'Double Payment', date_mismatch: 'Date Mismatch', no_payment: 'No Payment',
  amount_mismatch: 'Amt Mismatch', refund_pending: 'Refund Pending',
};
const statusPillClass = {
  matched: 'matched', invoice_missing: 'warn', payment_failed: 'issue',
  double_payment: 'purple', date_mismatch: 'info', no_payment: 'issue',
  amount_mismatch: 'warn', refund_pending: 'purple',
};

const columnOptions = [
  'Select column...', 'order_id', 'transaction_id', 'payment_id', 'invoice_number',
  'date', 'amount', 'customer_name', 'customer_email', 'product_name', 'sku',
  'payment_method', 'payment_status', 'settlement_id', 'utr_number', 'city',
];

function getBotResponse(msg) {
  const lower = msg.toLowerCase();
  if (lower.includes('start') || lower.includes('run') || lower.includes('march') || lower.includes('reconcil')) {
    return { text: `Running reconciliation for March 11, 2026...\n\nMatching sales records with Razorpay payments...\nApplying matching rules on: order_id, amount\n\nResults:\n  67 of 80 transactions matched\n  13 transactions have issues\n\nIssue Breakdown:\n  3 Invoice Missing | 2 Payment Failed\n  1 Double Payment | 2 Date Mismatch\n  3 No Payment | 1 Amount Mismatch\n  1 Refund Pending\n\nMatch Rate: 83.75%\nWhat would you like to investigate?`, actions: [
      { label: 'Show All Issues', action: 'Show unmatched transactions' },
      { label: 'Invoice Missing', action: 'Invoice missing cases?' },
      { label: 'No Payment', action: 'Show no payment cases' },
    ]};
  }
  if (lower.includes('unmatched') || lower.includes('issue')) {
    return { text: `13 unmatched transactions found:\n\nPriority:\n1. No Payment (3) - Revenue at risk\n2. Invoice Missing (3) - Settlement blocked\n3. Payment Failed (2) - Customer impact\n\nClick any issue category chip to filter the table.`, actions: [
      { label: 'Get Details', action: 'Get details for all issues' },
      { label: 'Email Sellers', action: 'Send emails to sellers' },
      { label: 'Export Report', action: 'Generate recon report' },
    ]};
  }
  if (lower.includes('invoice')) {
    return { text: `3 orders have missing invoices.\n\nSettlement blocked until sellers upload valid invoices.\n\nRecommended action: Send automated reminder emails to sellers.`, actions: [
      { label: 'Get Details', action: 'Get details for invoice missing' },
      { label: 'Check Files', action: 'Check uploaded files' },
      { label: 'Email Sellers', action: 'Send email to sellers for invoices' },
    ]};
  }
  if (lower.includes('email') || lower.includes('send')) {
    return { text: `Preparing outreach emails for sellers...\n\nTemplate: "Action Required - Upload Invoice"\nRecipients: 3 seller contacts from Myntra hub\nAuto-follow-up: 48 hours\n\nShall I send these emails?`, actions: [
      { label: 'Yes, Send All', action: 'Confirm sending emails' },
      { label: 'Preview First', action: 'Show email preview' },
    ]};
  }
  if (lower.includes('confirm')) {
    return { text: `Emails sent successfully!\n\n3 outreach emails dispatched to sellers.\nAuto-follow-up in 48 hours.\n\nI'll notify you when sellers respond.` };
  }
  if (lower.includes('preview')) {
    return { text: `Email Preview:\n\nSubject: Action Required - Upload Invoice\n\nDear Seller,\n\nPlease upload the invoice for the following order:\n- Order ID: [ORDER_ID]\n- Amount: Rs [AMOUNT]\n- Delivery: [DATE]\n\nUpload via Myntra Seller Hub > Orders > Upload Invoice\n\nDeadline: 48 hours\n\nRegards, Lekha AI`, actions: [
      { label: 'Send Now', action: 'Confirm sending emails' },
      { label: 'Edit Template', action: 'Edit email template' },
    ]};
  }
  if (lower.includes('report') || lower.includes('generate') || lower.includes('export')) {
    return { text: `Generating reconciliation report...\n\nReport: Weekly Recon - W11 2026\nPeriod: March 8-14, 2026\nFormat: KPMG audit-ready\n\nSections: Executive Summary, Order-wise Details, Settlement Recon, Issue Analysis, Aging Buckets\n\nStatus: Ready for download` };
  }
  if (lower.includes('close') || lower.includes('complete') || lower.includes('finish')) {
    return { text: `Reconciliation Summary:\n\n67/80 transactions fully reconciled (83.75%)\n13 transactions pending resolution\n  - 3 emails sent to sellers\n  - 1 refund queued\n  - 9 items awaiting response\n\nNext automatic recon scheduled: March 12, 2026\n\nClose this reconciliation session?`, actions: [
      { label: 'Close & Save', action: 'Save and close reconciliation' },
      { label: 'Keep Open', action: 'Keep session open' },
    ]};
  }
  if (lower.includes('save')) {
    return { text: `Reconciliation session saved.\n\nSummary report exported to: reports/recon_20260311.xlsx\nPending items tracked in issue tracker.\n\nSession closed. Start a new reconciliation anytime.` };
  }
  if (lower.includes('double')) {
    return { text: `1 double payment detected.\n\nCustomer charged twice. Second payment needs refund to prevent chargeback.`, actions: [
      { label: 'Initiate Refund', action: 'Process refund' },
      { label: 'View Details', action: 'Get details' },
    ]};
  }
  if (lower.includes('no payment')) {
    return { text: `3 orders with no payment found.\n\nGoods delivered but no Razorpay payment. Potential causes:\n- Payment via different gateway\n- Marketplace processing delay\n- System sync issue`, actions: [
      { label: 'Check Other Gateways', action: 'Check PayU, Cashfree' },
      { label: 'Raise with Myntra', action: 'Email Myntra ops' },
    ]};
  }
  if (lower.includes('detail') || lower.includes('get') || lower.includes('check') || lower.includes('investigate')) {
    return { text: `Fetching data...\n\nERP system: checked\nWarehouse data: cross-referenced\nRazorpay logs: pulled\n\nAll data loaded. Click any transaction in the table to see full analysis in the right panel.` };
  }
  if (lower.includes('sync')) {
    return { text: `Syncing latest data...\n\nRazorpay: 2 new settlements\nMyntra: 5 new orders\nIncreFF: 3 returns received\n\nDashboard updated.`, actions: [
      { label: 'Run Recon', action: 'Start reconciliation' },
    ]};
  }
  if (lower.includes('refund') || lower.includes('process')) {
    return { text: `Processing refund...\n\nRefund initiated via Razorpay API.\nAmount will be credited within 5-7 business days.\nCustomer notified via email.` };
  }
  return { text: `I can help with:\n\n- Run reconciliation\n- Investigate issues by category\n- Send emails for missing data\n- Process refunds\n- Generate reports\n- Close reconciliation session\n\nWhat would you like to do?` };
}

// Phases: 'upload' -> 'mapping' -> 'results'
function PaymentRecon({ onBack }) {
  const [phase, setPhase] = useState('upload');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingText, setLoadingText] = useState('');

  // Transition with loading delay to feel real
  const transitionTo = (nextPhase, text = 'Processing...', delay = 2500) => {
    setIsLoading(true);
    setLoadingText(text);
    setTimeout(() => {
      setPhase(nextPhase);
      setIsLoading(false);
      setLoadingText('');
    }, delay);
  };
  const [salesFile, setSalesFile] = useState(null);
  const [paymentFile, setPaymentFile] = useState(null);
  const [mappings, setMappings] = useState({ matchKey: 'order_id', amountCol: 'amount', dateCol: 'date' });
  const [selectedTxn, setSelectedTxn] = useState(null);
  const [rightOpen, setRightOpen] = useState(true);
  const [filter, setFilter] = useState('all');
  const [messages, setMessages] = useState([
    { type: 'bot', text: 'Welcome to Lekha AI!\n\nUpload your sales report and payment report to begin reconciliation.\n\nSupported formats: CSV, XLSX, JSON', actions: [
      { label: 'Use Sample Data', action: 'Load sample Myntra + Razorpay data' },
    ]},
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [reconStarted, setReconStarted] = useState(false);
  const [emailModal, setEmailModal] = useState(null); // { to, subject, body, orderId }
  const [expandedGroups, setExpandedGroups] = useState(new Set());
  const [resolvedGroups, setResolvedGroups] = useState(new Set());
  const chatRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages, isTyping]);

  const openEmailDraft = (orderId, issueType) => {
    const templates = {
      invoice_missing: {
        subject: `Action Required: Upload Invoice for Order ${orderId}`,
        body: `Dear Seller,\n\nWe are processing settlements for recent orders and noticed that the invoice for the following order is missing from our system:\n\nOrder ID: ${orderId}\nMarketplace: Myntra\nDate: March 11, 2026\n\nPlease upload the invoice via Myntra Seller Hub > Orders > Upload Invoice within the next 48 hours to avoid settlement delays.\n\nIf you have already uploaded the invoice, please reply to this email with the invoice number for our reference.\n\nRegards,\nLekha AI\nScaleUp CFO`,
      },
      no_payment: {
        subject: `Payment Trace Request - Order ${orderId}`,
        body: `Dear Myntra Ops Team,\n\nWe have identified the following order where goods were delivered but no corresponding payment has been received via Razorpay:\n\nOrder ID: ${orderId}\nDelivery Date: March 11, 2026\nStatus: Delivered (confirmed via Increff WMS)\n\nCould you please investigate and confirm:\n1. Was this payment processed via a different gateway?\n2. Is there a pending settlement for this order?\n3. Any known issues with this transaction?\n\nPlease respond within 24 hours as this impacts our daily reconciliation.\n\nRegards,\nLekha AI\nScaleUp CFO`,
      },
      date_mismatch: {
        subject: `Invoice Date Correction Required - Order ${orderId}`,
        body: `Dear Seller,\n\nDuring our reconciliation process, we found a date mismatch for the following order:\n\nOrder ID: ${orderId}\n\nThe invoice date does not match the payment date in our records. Please review and reissue the invoice with the correct date.\n\nRegards,\nLekha AI\nScaleUp CFO`,
      },
      default: {
        subject: `Reconciliation Query - Order ${orderId}`,
        body: `Dear Team,\n\nWe have a reconciliation query regarding the following order:\n\nOrder ID: ${orderId}\nDate: March 11, 2026\n\nPlease review and provide the necessary details at the earliest.\n\nRegards,\nLekha AI\nScaleUp CFO`,
      },
    };
    const tmpl = templates[issueType] || templates.default;
    setEmailModal({ to: '', subject: tmpl.subject, body: tmpl.body, orderId });
  };

  const sendEmail = () => {
    if (!emailModal.to) return;
    const catKey = emailModal.categoryKey;
    setEmailModal(null);
    setMessages(prev => [...prev, {
      type: 'bot',
      text: `Email sent successfully!\n\nTo: ${emailModal.to}\nSubject: ${emailModal.subject}\n\nAuto-follow-up scheduled in 48 hours. I'll notify you when the recipient responds.${catKey ? `\n\n✅ Category "${issueCategories.find(c => c.key === catKey)?.label || catKey}" resolved.` : ''}`
    }]);
    if (catKey) {
      setResolvedGroups(prev => new Set([...prev, catKey]));
    }
  };

  // Auto-resize textarea
  const handleTextareaInput = (e) => {
    setInput(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  };

  const sendMessage = (text) => {
    if (!text.trim()) return;
    const lower = text.toLowerCase();
    setMessages(prev => [...prev, { type: 'user', text }]);
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    setIsTyping(true);

    // Handle sample data loading
    if (lower.includes('sample') || lower.includes('load')) {
      setTimeout(() => {
        setIsTyping(false);
        setSalesFile('myntra_sales_march11.csv');
        setPaymentFile('razorpay_payments_march11.csv');
        transitionTo('mapping', 'Loading sample data...', 2500);
        setMessages(prev => [...prev, { type: 'bot', text: 'Sample data loaded!\n\n- Sales: myntra_sales_march11.csv (80 orders)\n- Payments: razorpay_payments_march11.csv (77 payments)\n\nNow select the matching columns to reconcile these files.' }]);
      }, 800);
      return;
    }

    if (lower.includes('start') || lower.includes('run') || lower.includes('reconcil') || lower.includes('march')) {
      setReconStarted(true);
      setPhase('results');
    }

    setTimeout(() => {
      setIsTyping(false);
      const resp = getBotResponse(text);
      setMessages(prev => [...prev, { type: 'bot', ...resp }]);
    }, 800 + Math.random() * 600);
  };

  const handleFileUpload = (type) => {
    // Simulate file selection
    if (type === 'sales') setSalesFile('myntra_sales_march11.csv');
    else setPaymentFile('razorpay_payments_march11.csv');
    setMessages(prev => [...prev, {
      type: 'bot',
      text: `${type === 'sales' ? 'Sales' : 'Payment'} report uploaded: ${type === 'sales' ? 'myntra_sales_march11.csv' : 'razorpay_payments_march11.csv'}\n\n${type === 'sales' ? '80 rows detected. Columns: order_id, product_name, sku, amount, customer_name, city, date, status' : '77 rows detected. Columns: payment_id, order_id, amount, fee, tax, net_amount, method, status, settlement_id'}`
    }]);
  };

  const proceedToMapping = () => {
    transitionTo('mapping', 'Analyzing file structure...', 2000);
    setMessages(prev => [...prev, {
      type: 'bot',
      text: 'Both files uploaded. Now select the matching parameters.\n\nI detected "order_id" and "amount" as likely match keys. You can adjust these in the column mapping panel.'
    }]);
  };

  const startRecon = () => {
    transitionTo('results', 'Matching 80 sales records against 77 payments...', 3500);
    setReconStarted(true);
    setTimeout(() => sendMessage('Start reconciliation for March 11'), 3600);
  };

  const toggleGroup = (key) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  // Category-level actions
  const categoryActions = {
    invoice_missing: [
      { id: 'email', label: 'Ask Data by Email', desc: 'Request missing invoices from all sellers', icon: '✉' },
      { id: 'call', label: 'Call Seller Contact', desc: 'Get phone details for follow-up', icon: '📞' },
      { id: 'file', label: 'Check Source Files', desc: 'Scan uploaded docs for invoices', icon: '📁' },
    ],
    payment_failed: [
      { id: 'email', label: 'Send Retry Links', desc: 'Email customers with payment retry links', icon: '✉' },
      { id: 'call', label: 'Call Gateway Support', desc: 'Contact Razorpay for failure reasons', icon: '📞' },
      { id: 'file', label: 'Check Gateway Logs', desc: 'Pull detailed failure logs from Razorpay', icon: '📁' },
    ],
    double_payment: [
      { id: 'email', label: 'Notify Finance Team', desc: 'Alert team for refund processing', icon: '✉' },
      { id: 'file', label: 'Pull Payment Proofs', desc: 'Fetch both transaction receipts', icon: '📁' },
      { id: 'refund', label: 'Initiate Bulk Refund', desc: 'Process refund for duplicate payments', icon: '↩' },
    ],
    date_mismatch: [
      { id: 'email', label: 'Request Date Correction', desc: 'Email sellers to reissue invoices', icon: '✉' },
      { id: 'file', label: 'Compare Timelines', desc: 'Read order/payment timeline from ERP', icon: '📁' },
      { id: 'auto', label: 'Auto-Correct Dates', desc: 'Apply date normalization rules', icon: '⚡' },
    ],
    no_payment: [
      { id: 'email', label: 'Raise with Myntra Ops', desc: 'Email marketplace for payment trace', icon: '✉' },
      { id: 'call', label: 'Call Marketplace Hub', desc: 'Escalate via phone for urgent cases', icon: '📞' },
      { id: 'file', label: 'Check Other Gateways', desc: 'Search PayU, Cashfree, Paytm', icon: '📁' },
    ],
    amount_mismatch: [
      { id: 'email', label: 'Raise Discrepancy', desc: 'File ticket with marketplace', icon: '✉' },
      { id: 'file', label: 'Check Rate Card', desc: 'Compare against commission rate card', icon: '📁' },
      { id: 'auto', label: 'Apply Fee Adjustment', desc: 'Auto-reconcile known commission rates', icon: '⚡' },
    ],
    refund_pending: [
      { id: 'email', label: 'Notify Customer', desc: 'Send refund status update email', icon: '✉' },
      { id: 'file', label: 'Check Warehouse Receipt', desc: 'Verify return received at warehouse', icon: '📁' },
      { id: 'refund', label: 'Process All Refunds', desc: 'Initiate refund via Razorpay API', icon: '↩' },
    ],
  };

  const handleCategoryAction = (issueKey, actionId) => {
    const cat = issueCategories.find(c => c.key === issueKey);
    const txnsInGroup = transactions.filter(t => t.status === issueKey);
    const orderIds = txnsInGroup.map(t => t.orderId).join(', ');

    if (actionId === 'email') {
      // Open email modal for category-level email
      const templates = {
        invoice_missing: { subject: `Action Required: Upload Invoices for ${txnsInGroup.length} Orders`, body: `Dear Seller,\n\nWe are processing settlements and noticed missing invoices for the following orders:\n\n${txnsInGroup.map(t => `• ${t.orderId} — Rs ${fmt(t.sellingPrice)} (${t.product})`).join('\n')}\n\nPlease upload invoices via Myntra Seller Hub > Orders > Upload Invoice within 48 hours.\n\nRegards,\nLekha AI\nScaleUp CFO` },
        payment_failed: { subject: `Payment Retry Required - ${txnsInGroup.length} Orders`, body: `Dear Customer,\n\nYour payment could not be processed for the following orders:\n\n${txnsInGroup.map(t => `• ${t.orderId} — Rs ${fmt(t.sellingPrice)} (${t.product})`).join('\n')}\n\nPlease retry payment using the link below or contact support.\n\nRegards,\nLekha AI` },
        no_payment: { subject: `Payment Trace Request - ${txnsInGroup.length} Unmatched Orders`, body: `Dear Myntra Ops Team,\n\nGoods delivered but no payment received for:\n\n${txnsInGroup.map(t => `• ${t.orderId} — Rs ${fmt(t.sellingPrice)} (${t.customer}, ${t.city})`).join('\n')}\n\nPlease investigate and confirm payment status.\n\nRegards,\nLekha AI\nScaleUp CFO` },
        date_mismatch: { subject: `Invoice Date Correction - ${txnsInGroup.length} Orders`, body: `Dear Seller,\n\nDate mismatches found for:\n\n${txnsInGroup.map(t => `• ${t.orderId} — Rs ${fmt(t.sellingPrice)}`).join('\n')}\n\nPlease reissue invoices with correct dates.\n\nRegards,\nLekha AI` },
        double_payment: { subject: `Duplicate Payment Alert - ${txnsInGroup.length} Orders`, body: `Dear Finance Team,\n\nDuplicate payments detected:\n\n${txnsInGroup.map(t => `• ${t.orderId} — Rs ${fmt(t.sellingPrice)} (duplicate charge)`).join('\n')}\n\nPlease process refunds for the duplicate amounts.\n\nRegards,\nLekha AI` },
        amount_mismatch: { subject: `Amount Discrepancy - ${txnsInGroup.length} Orders`, body: `Dear Marketplace Team,\n\nAmount mismatches found:\n\n${txnsInGroup.map(t => `• ${t.orderId} — Sale Rs ${fmt(t.sellingPrice)}, Payment Rs ${fmt(t.paymentAmount)}, Variance Rs ${fmt(t.variance)}`).join('\n')}\n\nPlease verify against commission rate card.\n\nRegards,\nLekha AI` },
        refund_pending: { subject: `Pending Refunds - ${txnsInGroup.length} Orders`, body: `Dear Customer,\n\nYour return has been received. Refund is being processed for:\n\n${txnsInGroup.map(t => `• ${t.orderId} — Rs ${fmt(t.sellingPrice)}`).join('\n')}\n\nExpected credit: 5-7 business days.\n\nRegards,\nLekha AI` },
      };
      const tmpl = templates[issueKey] || { subject: `Reconciliation Query - ${txnsInGroup.length} Orders`, body: `Orders: ${orderIds}` };
      setEmailModal({ to: '', subject: tmpl.subject, body: tmpl.body, orderId: orderIds, categoryKey: issueKey });
    } else {
      // Non-email actions: simulate processing and resolve
      const actionLabel = categoryActions[issueKey]?.find(a => a.id === actionId)?.label || actionId;
      setMessages(prev => [...prev, { type: 'user', text: `${actionLabel} for all ${cat?.label || issueKey} cases` }]);
      setIsTyping(true);
      setTimeout(() => {
        setIsTyping(false);
        if (actionId === 'refund') {
          setMessages(prev => [...prev, { type: 'bot', text: `Refund initiated for ${txnsInGroup.length} orders.\n\n${txnsInGroup.map(t => `• ${t.orderId} — Rs ${fmt(t.sellingPrice)}`).join('\n')}\n\nAmount will be credited within 5-7 business days.\nCustomers notified via email.\n\n✅ Category "${cat?.label}" resolved.` }]);
        } else if (actionId === 'auto') {
          setMessages(prev => [...prev, { type: 'bot', text: `Auto-processing ${txnsInGroup.length} transactions...\n\n${txnsInGroup.map(t => `• ${t.orderId} — adjusted & matched`).join('\n')}\n\n✅ Category "${cat?.label}" resolved. ${txnsInGroup.length} transactions now reconciled.` }]);
        } else {
          setMessages(prev => [...prev, { type: 'bot', text: `${actionLabel} completed for ${txnsInGroup.length} transactions.\n\nOrders: ${orderIds}\n\nData loaded and cross-referenced. Check individual transactions for details.\n\n✅ Category "${cat?.label}" resolved.` }]);
        }
        setResolvedGroups(prev => new Set([...prev, issueKey]));
      }, 1000);
    }
  };

  // Stats
  const matched = transactions.filter(t => t.status === 'matched').length;
  const issues = transactions.filter(t => t.status !== 'matched').length;
  const totalSales = transactions.reduce((s, t) => s + t.sellingPrice, 0);
  const settledAmount = transactions.filter(t => t.settlementId).reduce((s, t) => s + t.sellingPrice, 0);
  const matchRate = ((matched / transactions.length) * 100).toFixed(1);
  const atRisk = Math.abs(transactions.filter(t => t.variance < 0).reduce((s, t) => s + t.variance, 0));

  const filtered = useMemo(() => {
    if (filter === 'all') return transactions;
    if (filter === 'issues') return transactions.filter(t => t.status !== 'matched');
    return transactions.filter(t => t.status === filter);
  }, [filter]);

  return (
    <div className="pr-app">
      {/* LEFT PANEL — Chat */}
      <div className="pr-left-panel">
        <button className="pr-back-link" onClick={onBack}>&larr; Back to Reconciliations</button>
        <div className="pr-brand">
          <h2>Sales-Payment Recon</h2>
          <span>Myntra + Razorpay | March 2026</span>
        </div>

        {/* Chat */}
        <div className="chat-section">
          <div className="chat-header">
            <span className="pulse-dot"></span>
            Lekha AI Assistant
          </div>
          <div className="chat-messages" ref={chatRef}>
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg ${m.type}`}>
                <div className="msg-label">{m.type === 'bot' ? 'Lekha AI' : 'You'}</div>
                {m.text}
                {m.actions && (
                  <div className="chat-actions">
                    {m.actions.map((a, j) => (
                      <button key={j} className="chat-action-btn" onClick={() => sendMessage(a.action)}>{a.label}</button>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {isTyping && (
              <div className="chat-msg bot">
                <div className="msg-label">Recon AI</div>
                <div className="typing-dots"><span></span><span></span><span></span></div>
              </div>
            )}
          </div>
          <div className="suggestions">
            {(phase === 'results' ? chatSuggestions : ['Use sample data', 'How does this work?']).slice(0, 4).map((s, i) => (
              <div key={i} className="suggestion-chip" onClick={() => sendMessage(s)}>{s}</div>
            ))}
          </div>
          <div className="chat-input-area">
            <div className="chat-input-wrap">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleTextareaInput}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input); } }}
                placeholder="Ask about reconciliation..."
                rows={1}
              />
              <button className="chat-send-btn" onClick={() => sendMessage(input)}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* CENTER PANEL */}
      <div className="pr-center-panel">
        {/* Loading overlay */}
        {isLoading && (
          <div className="pr-loading-overlay">
            <div className="pr-loading-spinner" />
            <div className="pr-loading-text">{loadingText}</div>
          </div>
        )}
        <div className="top-bar">
          <div className="top-bar-left">
            <h2>Payment Reconciliation</h2>
            <span className="date-badge">March 11, 2026</span>
            {reconStarted && <span className="date-badge" style={{ borderColor: 'var(--accent-green)', color: 'var(--accent-green)' }}>Recon Complete</span>}
          </div>
          <div className="top-bar-right">
            {phase === 'results' && (
              <>
                <button className="top-btn" onClick={() => sendMessage('Sync latest data')}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
                  Sync
                </button>
                <button className="top-btn" onClick={() => sendMessage('Generate recon report')}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  Export
                </button>
              </>
            )}
          </div>
        </div>

        {/* PHASE: UPLOAD */}
        {phase === 'upload' && (
          <div className="upload-section">
            <div className="upload-area">
              <div className="step-indicator">
                <div className={`step ${salesFile && paymentFile ? 'done' : 'active'}`}>
                  <div className="step-num">1</div>
                  Upload Files
                </div>
                <div className="step-line"></div>
                <div className="step">
                  <div className="step-num">2</div>
                  Map Columns
                </div>
                <div className="step-line"></div>
                <div className="step">
                  <div className="step-num">3</div>
                  View Results
                </div>
              </div>

              <div className={`upload-box ${salesFile ? 'filled' : ''}`} onClick={() => handleFileUpload('sales')}>
                <div className="upload-icon">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                </div>
                <h3>{salesFile ? 'Sales Report Uploaded' : 'Upload Sales Report'}</h3>
                <p>{salesFile ? '' : 'Drag & drop or click to browse (CSV, XLSX)'}</p>
                {salesFile && <div className="file-name">{salesFile} - 80 rows</div>}
              </div>

              <div className={`upload-box ${paymentFile ? 'filled' : ''}`} onClick={() => handleFileUpload('payment')}>
                <div className="upload-icon">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                </div>
                <h3>{paymentFile ? 'Payment Report Uploaded' : 'Upload Payment Report'}</h3>
                <p>{paymentFile ? '' : 'Razorpay settlement or payment export (CSV, XLSX)'}</p>
                {paymentFile && <div className="file-name">{paymentFile} - 77 rows</div>}
              </div>

              {salesFile && paymentFile && (
                <button className="proceed-btn" onClick={proceedToMapping}>
                  Continue to Column Mapping
                </button>
              )}
            </div>
          </div>
        )}

        {/* PHASE: COLUMN MAPPING */}
        {phase === 'mapping' && (
          <div className="upload-section">
            <div className="upload-area">
              <div className="step-indicator">
                <div className="step done">
                  <div className="step-num">1</div>
                  Upload Files
                </div>
                <div className="step-line"></div>
                <div className="step active">
                  <div className="step-num">2</div>
                  Map Columns
                </div>
                <div className="step-line"></div>
                <div className="step">
                  <div className="step-num">3</div>
                  View Results
                </div>
              </div>

              <div className="column-mapping">
                <h3>Select Matching Parameters</h3>
                <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20 }}>
                  Choose which columns to use for matching sales with payments
                </p>

                <div className="mapping-row">
                  <label>Primary Match Key</label>
                  <select value={mappings.matchKey} onChange={e => setMappings({ ...mappings, matchKey: e.target.value })}>
                    {columnOptions.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>

                <div className="mapping-row">
                  <label>Amount Column</label>
                  <select value={mappings.amountCol} onChange={e => setMappings({ ...mappings, amountCol: e.target.value })}>
                    {columnOptions.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>

                <div className="mapping-row">
                  <label>Date Column</label>
                  <select value={mappings.dateCol} onChange={e => setMappings({ ...mappings, dateCol: e.target.value })}>
                    {columnOptions.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>

                <div className="mapping-row">
                  <label>Amount Tolerance</label>
                  <select defaultValue="exact">
                    <option value="exact">Exact match</option>
                    <option value="1">Within Rs 1</option>
                    <option value="10">Within Rs 10</option>
                    <option value="100">Within Rs 100</option>
                  </select>
                </div>

                <button className="proceed-btn" onClick={startRecon} disabled={mappings.matchKey === 'Select column...'}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ display: 'inline', verticalAlign: 'middle', marginRight: 6 }}><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  Run Reconciliation
                </button>
              </div>
            </div>
          </div>
        )}

        {/* PHASE: RESULTS */}
        {phase === 'results' && (
          <>
            <div className="status-cards">
              <div className={`status-card ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>
                <div className="card-label">Total Transactions</div>
                <div className="card-value blue">{transactions.length}</div>
                <div className="card-sub">Rs {fmt(totalSales)}</div>
              </div>
              <div className={`status-card ${filter === 'matched' ? 'active' : ''}`} onClick={() => setFilter('matched')}>
                <div className="card-label">Matched</div>
                <div className="card-value green">{matched}</div>
                <div className="card-sub">{matchRate}% match rate</div>
              </div>
              <div className={`status-card ${filter === 'issues' ? 'active' : ''}`} onClick={() => setFilter('issues')}>
                <div className="card-label">Issues Found</div>
                <div className="card-value red">{issues}</div>
                <div className="card-sub">Needs attention</div>
              </div>
              <div className="status-card">
                <div className="card-label">Settled</div>
                <div className="card-value green">Rs {fmt(settledAmount)}</div>
                <div className="card-sub">Via Razorpay</div>
              </div>
              <div className="status-card">
                <div className="card-label">At Risk</div>
                <div className="card-value orange">Rs {fmt(atRisk)}</div>
                <div className="card-sub">Revenue exposure</div>
              </div>
            </div>

            <div className="issue-bar">
              {issueCategories.map(cat => (
                <div key={cat.key} className={`issue-chip ${filter === cat.key ? 'active' : ''}`}
                  onClick={() => setFilter(filter === cat.key ? 'all' : cat.key)}>
                  <div className="chip-dot" style={{ background: cat.color }}></div>
                  {cat.label} <span className="chip-count">{cat.count}</span>
                </div>
              ))}
            </div>

            <div className="progress-row">
              <span className="progress-label">Resolved</span>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${matchRate}%` }}></div>
              </div>
              <span className="progress-label">{matchRate}%</span>
            </div>

            <div className="table-section">
              <div className="table-header">
                <h3>Transactions ({filtered.length} of {transactions.length})</h3>
              </div>
              <div className="table-wrap">
                {/* Issue Groups Accordion */}
                {(filter === 'all' || filter === 'issues' ? issueCategories : issueCategories.filter(c => c.key === filter)).map(cat => {
                  const groupTxns = transactions.filter(t => t.status === cat.key);
                  if (groupTxns.length === 0) return null;
                  const isExpanded = expandedGroups.has(cat.key);
                  const isResolved = resolvedGroups.has(cat.key);
                  const totalAtRisk = Math.abs(groupTxns.reduce((s, t) => s + t.variance, 0));
                  return (
                    <div key={cat.key} className={`issue-group ${isResolved ? 'resolved' : ''}`}>
                      <div className="issue-group-header" onClick={() => toggleGroup(cat.key)}>
                        <div className="issue-group-left">
                          <svg className={`chevron ${isExpanded ? 'open' : ''}`} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
                          <div className="chip-dot" style={{ background: cat.color }}></div>
                          <span className="issue-group-title">{cat.label}</span>
                          <span className="issue-group-count">{groupTxns.length}</span>
                          {isResolved && <span className="resolved-badge">✓ Resolved</span>}
                        </div>
                        <div className="issue-group-right">
                          {totalAtRisk > 0 && <span className="risk-amount">Rs {fmt(totalAtRisk)} at risk</span>}
                        </div>
                      </div>

                      {isExpanded && (
                        <>
                          {/* Category-level actions */}
                          {!isResolved && categoryActions[cat.key] && (
                            <div className="issue-group-actions">
                              <span className="actions-label">Next Steps:</span>
                              {categoryActions[cat.key].map((act, j) => (
                                <button key={j} className="cat-action-btn" onClick={(e) => { e.stopPropagation(); handleCategoryAction(cat.key, act.id); }}>
                                  <span className="cat-action-icon">{act.icon}</span>
                                  <div>
                                    <div className="cat-action-label">{act.label}</div>
                                    <div className="cat-action-desc">{act.desc}</div>
                                  </div>
                                </button>
                              ))}
                            </div>
                          )}
                          {isResolved && (
                            <div className="issue-group-resolved-msg">
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>
                              All {groupTxns.length} transactions in this category have been resolved
                            </div>
                          )}
                          <table>
                            <thead>
                              <tr>
                                <th>Order ID</th>
                                <th>Product</th>
                                <th>Customer</th>
                                <th>Sale Amt</th>
                                <th>Payment</th>
                                <th>Variance</th>
                              </tr>
                            </thead>
                            <tbody>
                              {groupTxns.map(txn => (
                                <tr key={txn.orderId} className={selectedTxn?.orderId === txn.orderId ? 'selected' : ''}
                                  onClick={() => { setSelectedTxn(txn); setRightOpen(true); }}>
                                  <td className="mono">{txn.orderId}</td>
                                  <td style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{txn.product}</td>
                                  <td>{txn.customer}</td>
                                  <td className="amt">Rs {fmt(txn.sellingPrice)}</td>
                                  <td className="amt">{txn.paymentAmount ? `Rs ${fmt(txn.paymentAmount)}` : '-'}</td>
                                  <td className={`amt ${txn.variance < 0 ? 'neg' : txn.variance > 0 ? 'pos' : ''}`}>
                                    {txn.variance !== 0 ? `Rs ${fmt(txn.variance)}` : '-'}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </>
                      )}
                    </div>
                  );
                })}

                {/* Matched transactions (shown when filter is 'all' or 'matched') */}
                {(filter === 'all' || filter === 'matched') && (() => {
                  const matchedTxns = transactions.filter(t => t.status === 'matched');
                  const isExpanded = expandedGroups.has('matched');
                  return (
                    <div className="issue-group matched-group">
                      <div className="issue-group-header" onClick={() => toggleGroup('matched')}>
                        <div className="issue-group-left">
                          <svg className={`chevron ${isExpanded ? 'open' : ''}`} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
                          <div className="chip-dot" style={{ background: 'var(--accent-green)' }}></div>
                          <span className="issue-group-title">Matched</span>
                          <span className="issue-group-count">{matchedTxns.length}</span>
                          <span className="resolved-badge">✓ Reconciled</span>
                        </div>
                      </div>
                      {isExpanded && (
                        <table>
                          <thead>
                            <tr>
                              <th>Order ID</th>
                              <th>Product</th>
                              <th>Customer</th>
                              <th>Sale Amt</th>
                              <th>Payment</th>
                              <th>Settlement</th>
                            </tr>
                          </thead>
                          <tbody>
                            {matchedTxns.map(txn => (
                              <tr key={txn.orderId} className={selectedTxn?.orderId === txn.orderId ? 'selected' : ''}
                                onClick={() => { setSelectedTxn(txn); setRightOpen(true); }}>
                                <td className="mono">{txn.orderId}</td>
                                <td style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{txn.product}</td>
                                <td>{txn.customer}</td>
                                <td className="amt">Rs {fmt(txn.sellingPrice)}</td>
                                <td className="amt">Rs {fmt(txn.paymentAmount)}</td>
                                <td className="mono" style={{ fontSize: 11 }}>{txn.settlementId}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* Close Recon Bar */}
            <div className="close-recon-bar">
              <span>{matched} of {transactions.length} reconciled | {issues} pending</span>
              <div className="close-recon-actions">
                <button className="top-btn" onClick={() => sendMessage('Close and complete reconciliation')}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>
                  Close Recon
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* RIGHT PANEL */}
      <div className={`right-panel ${!rightOpen || phase !== 'results' ? 'collapsed' : ''}`}>
        {selectedTxn ? (
          <>
            <div className="detail-header">
              <h3>Transaction Detail</h3>
              <button className="close-btn" onClick={() => setRightOpen(false)}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="detail-body">
              <div className="detail-section">
                <h4>Order Information</h4>
                <div className="detail-row"><span className="label">Order ID</span><span className="value mono">{selectedTxn.orderId}</span></div>
                <div className="detail-row"><span className="label">Product</span><span className="value">{selectedTxn.product}</span></div>
                <div className="detail-row"><span className="label">SKU</span><span className="value mono">{selectedTxn.sku}</span></div>
                <div className="detail-row"><span className="label">Customer</span><span className="value">{selectedTxn.customer}</span></div>
                <div className="detail-row"><span className="label">City</span><span className="value">{selectedTxn.city}</span></div>
                <div className="detail-row"><span className="label">Sale Amount</span><span className="value">Rs {fmt(selectedTxn.sellingPrice)}</span></div>
                <div className="detail-row"><span className="label">Discount</span><span className="value" style={{ color: 'var(--accent-red)' }}>-Rs {fmt(selectedTxn.discount)}</span></div>
              </div>

              <div className="detail-section">
                <h4>Payment Information</h4>
                {selectedTxn.paymentId ? (
                  <>
                    <div className="detail-row"><span className="label">Payment ID</span><span className="value mono">{selectedTxn.paymentId}</span></div>
                    <div className="detail-row"><span className="label">Amount</span><span className="value">Rs {fmt(selectedTxn.paymentAmount)}</span></div>
                    <div className="detail-row"><span className="label">Gateway Fee</span><span className="value" style={{ color: 'var(--accent-orange)' }}>Rs {fmt2(selectedTxn.fee)}</span></div>
                    <div className="detail-row"><span className="label">Net Amount</span><span className="value" style={{ color: 'var(--accent-green)' }}>Rs {fmt2(selectedTxn.netAmount)}</span></div>
                    <div className="detail-row"><span className="label">Method</span><span className="value">{selectedTxn.method.toUpperCase()}</span></div>
                    <div className="detail-row"><span className="label">Settlement</span><span className="value mono">{selectedTxn.settlementId || 'Pending'}</span></div>
                  </>
                ) : (
                  <div style={{ color: 'var(--accent-red)', fontSize: 13, padding: '8px 0' }}>No payment found in Razorpay</div>
                )}
              </div>

              <div className="detail-section">
                <h4>Reconciliation</h4>
                <div className="detail-row">
                  <span className="label">Status</span>
                  <span className={`status-pill ${statusPillClass[selectedTxn.status]}`}>
                    <span className="pill-dot" style={{ background: 'currentColor' }}></span>
                    {statusLabels[selectedTxn.status]}
                  </span>
                </div>
                {selectedTxn.variance !== 0 && (
                  <div className="detail-row">
                    <span className="label">Variance</span>
                    <span className="value" style={{ color: selectedTxn.variance < 0 ? 'var(--accent-red)' : 'var(--accent-green)' }}>Rs {fmt(selectedTxn.variance)}</span>
                  </div>
                )}
                <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{selectedTxn.note}</div>
              </div>

              <div className="terminal">
                <div className="terminal-head">recon_engine.py</div>
                <div className="terminal-body">
                  <div className="tl"><span className="tc">$</span> python recon_engine.py --order {selectedTxn.orderId}</div>
                  <div className="tl"><span className="tg">[OK]</span> Fetching Razorpay data...</div>
                  <div className="tl"><span className="tg">[OK]</span> Fetching sale record...</div>
                  {selectedTxn.paymentId ? (
                    <div className="tl"><span className="tb">[FOUND]</span> {selectedTxn.paymentId}</div>
                  ) : (
                    <div className="tl"><span className="tr">[ERR]</span> No payment in Razorpay</div>
                  )}
                  {selectedTxn.status === 'matched' ? (
                    <div className="tl"><span className="tg">[MATCH]</span> Rs {fmt(selectedTxn.sellingPrice)} == Rs {fmt(selectedTxn.paymentAmount)}</div>
                  ) : (
                    <div className="tl"><span className="ty">[ISSUE]</span> {statusLabels[selectedTxn.status]}</div>
                  )}
                  <div className="tl"><span className="tg">[DONE]</span> Complete</div>
                </div>
              </div>
            </div>

            {selectedTxn.actionOptions?.length > 0 && (
              <div className="detail-actions">
                <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>
                  What would you like to do?
                </div>
                {selectedTxn.actionOptions.map((opt, i) => (
                  <button key={i} className={`action-btn ${opt.id === 'initiate_refund' ? 'danger' : ''}`}
                    onClick={() => {
                      if (opt.id === 'request_input') {
                        openEmailDraft(selectedTxn.orderId, selectedTxn.status);
                      } else {
                        sendMessage(`${opt.label} for ${selectedTxn.orderId}`);
                      }
                    }}>
                    {opt.label}
                    <span className="btn-desc">{opt.desc}</span>
                  </button>
                ))}
              </div>
            )}
            {selectedTxn.status === 'matched' && (
              <div className="detail-actions">
                <button className="action-btn success">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>
                  Verified & Closed
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="empty-state">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ color: 'var(--text-muted)' }}>
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
            </svg>
            <p>Select a transaction to view details</p>
            <span style={{ fontSize: 12 }}>Click any row in the table</span>
          </div>
        )}
      </div>

      {/* Email Modal */}
      {emailModal && (
        <div className="modal-overlay" onClick={() => setEmailModal(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Send Email</h3>
              <button className="close-btn" onClick={() => setEmailModal(null)}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="modal-body">
              <div className="modal-field">
                <label>To (Email Address)</label>
                <input
                  type="email"
                  placeholder="seller@vendor.com"
                  value={emailModal.to}
                  onChange={e => setEmailModal({ ...emailModal, to: e.target.value })}
                  autoFocus
                />
              </div>
              <div className="modal-field">
                <label>Subject</label>
                <input
                  value={emailModal.subject}
                  onChange={e => setEmailModal({ ...emailModal, subject: e.target.value })}
                />
              </div>
              <div className="modal-field">
                <label>Message</label>
                <textarea
                  value={emailModal.body}
                  onChange={e => setEmailModal({ ...emailModal, body: e.target.value })}
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="modal-btn cancel" onClick={() => setEmailModal(null)}>Cancel</button>
              <button className="modal-btn send" onClick={sendEmail} disabled={!emailModal.to}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }}><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                Send Email
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default PaymentRecon;
