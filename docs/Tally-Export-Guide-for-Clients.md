# Tally Data Export Guide for Lekha AI TDS Reconciliation

## What You Need to Export

Lekha AI needs **3 reports** from Tally to run TDS reconciliation. Each report is exported as an **Excel file** using Tally's built-in export.

| # | Report | What It Contains | Why We Need It |
|---|--------|-----------------|----------------|
| 1 | **Journal Register** | All journal entries — interest, TDS, salary, brokerage | Matches against Form 26 for 194A, 194H, 192 |
| 2 | **Purchase GST Exp Register** | Expense vouchers with GST breakup | Matches against Form 26 for 194C, 194J(b) |
| 3 | **Purchase Register** | Goods purchase vouchers | Matches against Form 26 for 194Q |

---

## Step-by-Step Export Instructions

### Before You Start

- Open **Tally Prime** (or Tally ERP 9)
- Make sure the **correct company** is selected (Gateway of Tally shows company name at top)
- Know your **financial year** (e.g., 1-Apr-2024 to 31-Mar-2025)

---

### Export 1: Journal Register

1. From **Gateway of Tally**, go to:
   - **Display More Reports** → **Account Books** → **Journal Register**
   
2. If Tally asks for a period:
   - Set **From:** 1-Apr-2024
   - Set **To:** 31-Mar-2025
   - Press **Enter**

3. You should see the Journal Register with all journal entries listed.

4. Press **Ctrl + E** (or **Alt + E**) to open the **Export** screen.

5. In the Export screen:
   - **Export As:** Excel (Spreadsheet)
   - **File Name:** `Journal Register` (Tally will add .xlsx)
   - **Save Location:** Choose your Desktop or a folder you can find easily
   
6. Under **Report Options** (if shown):
   - **Show All Columns:** Yes
   - **Columnar Format:** Yes (this is important — gives us all ledger columns)

7. Press **Enter** or click **Export**.

8. **Verify:** Open the exported file. It should have columns like:
   - Date | Particulars | Voucher No. | Value | Gross Total | Interest Paid | TDS Payable | Brokerage and Commission | Salary & Bonus | (many more columns)
   - If you only see Date/Particulars/Amount without ledger columns, go back and enable "Columnar" format.

---

### Export 2: Purchase GST Exp Register

1. From **Gateway of Tally**, go to:
   - **Display More Reports** → **Account Books** → **Purchase Register**
   
2. Tally may show multiple purchase books. Select:
   - **Purchase GST Expense Register** (or similar name — it's the expense/service purchase book, NOT the goods purchase book)

3. Set the period:
   - **From:** 1-Apr-2024
   - **To:** 31-Mar-2025

4. Press **Ctrl + E** (or **Alt + E**) to Export.

5. Export settings:
   - **Export As:** Excel (Spreadsheet)
   - **File Name:** `Purchase GST Exp Register`
   - **Show All Columns:** Yes
   - **Columnar Format:** Yes

6. Press **Enter** to export.

7. **Verify:** The file should have columns like:
   - Date | Particulars | Voucher No. | Gross Total | Input C GST | Input S GST | Freight Charges | Advertisement | Packing Charges | (expense head columns)

---

### Export 3: Purchase Register (Goods)

1. From **Gateway of Tally** → **Display More Reports** → **Account Books** → **Purchase Register**

2. Select the **Purchase Register** (goods purchases — NOT the GST expense one).

3. Set the period:
   - **From:** 1-Apr-2024
   - **To:** 31-Mar-2025

4. Press **Ctrl + E** (or **Alt + E**) to Export.

5. Export settings:
   - **Export As:** Excel (Spreadsheet)
   - **File Name:** `Purchase Register`
   - **Show All Columns:** Yes
   - **Columnar Format:** Yes

6. Press **Enter** to export.

7. **Verify:** The file should have columns like:
   - Date | Particulars | Voucher No. | Purchase Account | Input C GST | Input S GST | Gross Total | Discount

---

## Combining Into One File (Optional)

You can upload the **3 separate Excel files** to Lekha AI. OR, you can combine them:

1. Open all 3 exported files in Excel
2. Create a new workbook
3. Copy each register into a separate sheet:
   - Sheet 1: "Journal Register"
   - Sheet 2: "Purchase GST Exp. Register"  
   - Sheet 3: "Purchase Register"
4. Save as `Tally extract.xlsx`
5. Upload this single file to Lekha AI

**Note:** Lekha AI accepts both formats — 3 separate files OR 1 combined file with 3 sheets.

---

## Also Needed: Form 26 and Form 24

### Form 26 (Non-Salary TDS — 26Q)

1. Log into **TRACES** (https://www.tdscpc.gov.in)
2. Go to **Downloads** → **Form 26**
3. Select **Assessment Year** and **Quarter**
4. Download the **Deduction Register** in Excel format
5. Upload to Lekha AI

### Form 24 (Salary TDS — 24Q) — Optional

1. Same TRACES portal
2. Download **Form 24Q Deduction Register** in Excel
3. Upload to Lekha AI (optional — only needed for Section 192 salary TDS reconciliation)

### Challan Register — Optional

1. TRACES → **Downloads** → **Challan Details**
2. Download in Excel
3. Upload to Lekha AI (enables late deposit penalty checking)

---

## Troubleshooting

### "I don't see columnar format option"
- Press **F5** or **Alt + F5** while viewing the register to switch to Columnar view BEFORE exporting.

### "The exported file has only 3-4 columns"
- You exported in non-columnar (summary) view. Go back to Step 4, switch to Columnar view, then re-export.

### "I can't find Purchase GST Exp Register"
- In some Tally setups, it's called "Expense Register" or "Service Purchase Register". Look for the register that shows GST expense vouchers (freight, advertisement, professional fees etc.)

### "My Tally version is Tally ERP 9, not Prime"
- The steps are almost identical. The export shortcut is **Alt + E** instead of Ctrl+E. Everything else is the same.

### "How do I know which register is which?"
- **Journal Register:** Has entries like Interest Paid, TDS Payable, Salary. These are internal accounting entries.
- **Purchase GST Exp Register:** Has entries with service vendors (freight companies, advertisers, consultants) with GST breakup.
- **Purchase Register:** Has entries for goods purchases (raw materials, finished goods for resale) with GST.

---

## Contact

If you face any issues with the export, reach out to your Lekha AI contact. We can do a 10-minute screen-share to help with the first export.
