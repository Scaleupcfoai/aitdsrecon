// Mock data: ~80 transactions (1/10th scale demo)
// 67 matched, 13 with issues

const products = [
  'Blue Cotton Kurta - M', 'Red Silk Saree', 'White Polo T-Shirt - L', 'Designer Lehenga Set',
  'Denim Jacket - XL', 'Premium Sherwani Set', 'Cotton Socks Pack of 3', 'Embroidered Anarkali',
  'Formal Shirt - M', 'Bridal Dupatta Set', 'Casual Chinos - 32', 'Zari Work Saree',
  'Nehru Jacket - L', 'Palazzo Pants - S', 'Printed Maxi Dress', 'Linen Blazer - 40',
];
const cities = ['Mumbai', 'Delhi', 'Bangalore', 'Hyderabad', 'Pune', 'Chennai', 'Kolkata', 'Jaipur'];
const methods = ['upi', 'card', 'netbanking', 'wallet', 'upi', 'upi', 'card'];
const names = ['Rahul S', 'Priya P', 'Amit K', 'Sita R', 'Vikram S', 'Neha G', 'Deepak J', 'Kavita N', 'Raj M', 'Anita V'];

function rng(seed) {
  let s = seed;
  return () => { s = (s * 16807 + 11) % 2147483647; return s / 2147483647; };
}
const rand = rng(42);

const issueBreakdown = {
  matched: 67,
  invoice_missing: 3,
  payment_failed: 2,
  double_payment: 1,
  date_mismatch: 2,
  no_payment: 3,
  amount_mismatch: 1,
  refund_pending: 1,
};

function generateTransactions() {
  const txns = [];
  const statuses = [];
  for (const [status, count] of Object.entries(issueBreakdown)) {
    for (let i = 0; i < count; i++) statuses.push(status);
  }
  // Shuffle issues to spread throughout
  for (let i = statuses.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [statuses[i], statuses[j]] = [statuses[j], statuses[i]];
  }

  for (let i = 0; i < 80; i++) {
    const orderId = `ORD${String(i + 1).padStart(4, '0')}`;
    const product = products[Math.floor(rand() * products.length)];
    const basePrice = Math.floor(rand() * 12000) + 800;
    const discount = Math.floor(basePrice * rand() * 0.25);
    const sellingPrice = basePrice - discount;
    const status = statuses[i];
    const city = cities[Math.floor(rand() * cities.length)];
    const customer = names[Math.floor(rand() * names.length)];
    const method = methods[Math.floor(rand() * methods.length)];
    const hour = Math.floor(rand() * 14) + 7;
    const min = Math.floor(rand() * 60);

    let paymentAmount = sellingPrice;
    let paymentId = `pay_${orderId}_${String(Math.floor(rand() * 99)).padStart(2, '0')}`;
    let settlementId = null;
    let variance = 0;
    let note = '';
    let actionOptions = [];

    switch (status) {
      case 'matched':
        settlementId = `setl_00${Math.floor(rand() * 3) + 1}`;
        note = 'Payment matches sale. Settled and verified.';
        break;
      case 'invoice_missing':
        note = 'Payment received but seller invoice not found in system. Cannot process settlement without valid invoice.';
        actionOptions = [
          { id: 'get_details', label: 'Get More Details', desc: 'Fetch invoice details from ERP system' },
          { id: 'check_files', label: 'Check Invoice Files', desc: 'Search in uploaded documents' },
          { id: 'request_input', label: 'Request from Seller', desc: 'Send email requesting invoice upload' },
        ];
        break;
      case 'payment_failed':
        paymentAmount = 0; variance = -sellingPrice;
        note = 'Payment attempt failed at gateway. Customer may retry or order auto-cancels after 24hrs.';
        actionOptions = [
          { id: 'get_details', label: 'Get Failure Details', desc: 'Check Razorpay failure reason' },
          { id: 'check_retry', label: 'Check Retry Status', desc: 'See if customer retried' },
          { id: 'request_input', label: 'Notify Customer', desc: 'Send payment retry link' },
        ];
        break;
      case 'double_payment':
        paymentAmount = sellingPrice * 2; variance = sellingPrice;
        note = 'Two successful payments detected for same order. Duplicate needs refund.';
        actionOptions = [
          { id: 'get_details', label: 'View Both Payments', desc: 'Show both payment transactions' },
          { id: 'initiate_refund', label: 'Initiate Refund', desc: 'Refund the duplicate payment' },
          { id: 'request_input', label: 'Escalate to Razorpay', desc: 'Raise support ticket' },
        ];
        break;
      case 'date_mismatch':
        note = 'Invoice date does not match payment date. Invoice dated 2 days prior to payment.';
        actionOptions = [
          { id: 'get_details', label: 'Compare Dates', desc: 'Show order/invoice/payment timeline' },
          { id: 'check_files', label: 'Check Original Invoice', desc: 'View invoice document' },
          { id: 'request_input', label: 'Request Correction', desc: 'Email seller to fix invoice date' },
        ];
        break;
      case 'no_payment':
        paymentAmount = 0; variance = -sellingPrice; paymentId = null;
        note = 'Sale recorded & goods delivered but no payment found in Razorpay. Revenue leakage risk.';
        actionOptions = [
          { id: 'get_details', label: 'Get Order Details', desc: 'Fetch full order lifecycle' },
          { id: 'check_files', label: 'Check Other Gateways', desc: 'Search PayU, Cashfree, etc.' },
          { id: 'request_input', label: 'Raise with Marketplace', desc: 'Email Myntra ops for payment trace' },
        ];
        break;
      case 'amount_mismatch': {
        const diff = Math.floor(rand() * 400) + 50;
        paymentAmount = sellingPrice - diff; variance = -diff;
        note = `Payment Rs ${paymentAmount.toLocaleString('en-IN')} vs sale Rs ${sellingPrice.toLocaleString('en-IN')}. Short Rs ${diff}. Likely commission deduction.`;
        actionOptions = [
          { id: 'get_details', label: 'Breakdown Analysis', desc: 'Fee, tax, commission breakdown' },
          { id: 'check_files', label: 'Check Rate Card', desc: 'Compare with commission rate card' },
          { id: 'request_input', label: 'Raise Discrepancy', desc: 'File ticket with marketplace' },
        ];
        break;
      }
      case 'refund_pending':
        note = 'Return received at warehouse but refund not processed. Aging: 5 days.';
        actionOptions = [
          { id: 'get_details', label: 'Check Return Status', desc: 'Verify warehouse receipt' },
          { id: 'initiate_refund', label: 'Process Refund', desc: 'Initiate refund via Razorpay' },
          { id: 'request_input', label: 'Notify Customer', desc: 'Send refund status update' },
        ];
        break;
    }

    txns.push({
      orderId, product,
      sku: `SKU-${String.fromCharCode(65 + (i % 26))}${String(Math.floor(rand() * 99)).padStart(2, '0')}`,
      sellingPrice, discount, customer, city,
      paymentId, paymentAmount, method,
      fee: Math.round(paymentAmount * 0.024 * 100) / 100,
      tax: Math.round(paymentAmount * 0.024 * 0.18 * 100) / 100,
      netAmount: Math.round((paymentAmount * (1 - 0.024 - 0.024 * 0.18)) * 100) / 100,
      settlementId, status, variance, note, actionOptions,
      time: `${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}`,
    });
  }
  return txns;
}

export const transactions = generateTransactions();

export const issueCategories = [
  { key: 'invoice_missing', label: 'Invoice Missing', count: 3, color: '#d29922' },
  { key: 'payment_failed', label: 'Payment Failed', count: 2, color: '#f85149' },
  { key: 'double_payment', label: 'Double Payment', count: 1, color: '#bc8cff' },
  { key: 'date_mismatch', label: 'Date Mismatch', count: 2, color: '#58a6ff' },
  { key: 'no_payment', label: 'No Payment', count: 3, color: '#f85149' },
  { key: 'amount_mismatch', label: 'Amount Mismatch', count: 1, color: '#d29922' },
  { key: 'refund_pending', label: 'Refund Pending', count: 1, color: '#bc8cff' },
];

export const chatSuggestions = [
  "Start reconciliation for March 11",
  "Show unmatched transactions",
  "Invoice missing cases?",
  "Process pending refunds",
  "Email sellers for invoices",
  "Generate recon report",
  "Show double payments",
];
