# MeatTrack Inventory System — User & Handover Guide

Welcome to your standalone **MeatTrack Inventory System**. This guide provides everything you need to access, install, and operate your daily inventory without any technical setup.

---

## 1. Accessing Your System

* **Website Link:** `https://your-app-name.onrender.com` *(or your custom address)*
* **Default Admin Account:**
  * **Email:** `admin@batangaspremium.test`
  * **Password:** `Admin123!@#`

> **Note on Initial Load:** If you open the link first thing in the morning and there was no activity during the night, please allow 45–60 seconds for the cloud server to spin up. After the initial load, it will stay fast throughout the day.

---

## 2. Install as an App on Android (Mobile Shortcut)

You can use this system on any Android phone or tablet just like a normal mobile app:

1. Open **Google Chrome** on your phone.
2. Visit your system website link.
3. Tap the **Three Dots (⋮)** in the top-right corner of Chrome.
4. Tap **"Add to Home Screen"** or **"Install App"**.
5. An app icon named **Inventory** will be placed on your phone's home screen.
6. When opened from your home screen, it will open **full screen** without browser address bars!

---

## 3. Daily Workflow Quick Reference

### A. Add Raw Materials (Meat, Spices, Packaging)
1. Go to **Inventory Workspace** from the sidebar menu.
2. Click **+ Add Raw Material**.
3. Enter name (e.g. *Pork Shoulder*, *Garlic Powder*, *Curing Salt*), category, unit (`kg`, `g`, `ml`), and starting stock quantity.
4. Click **Save Raw Material**.

### B. Restock / Add Quantity to Existing Raw Material
1. In the **Inventory Workspace**, click **+ Add Quantity**.
2. Select the existing material from the dropdown.
3. Enter the new incoming quantity.
4. Click **Add Quantity**. The stock balance updates immediately in the ledger.

### C. Create Product Recipes
1. In the **Inventory Workspace**, click **+ Create Recipe**.
2. Enter the finished product name (e.g. *Pork Tocino 250g*), category (*Pork*, *Beef*, *Chicken*), and pack size.
3. Add the required ingredient amounts needed for one batch/pack.
4. Click **Save Recipe**.

### D. Record Production (Deducts Ingredients Automatically)
1. In the **Inventory Workspace**, click **Produce Batch**.
2. Select the product and enter the batch code (e.g. *BATCH-202610-01*).
3. Enter the number of packs produced and set the **Expiry Date**.
4. Click **Confirm Production**.
   * *The system automatically deducts the raw ingredients from your inventory according to the recipe.*
   * *A new batch entry with shelf-life tracking is created.*

### E. Monitor Batches & Expiry Dates
1. Click **Product Batches** in the sidebar.
2. View all batches sorted by **Expiring First**, **Newest**, or **Product Name**.
3. Items nearing expiry (within 7 days) are color-coded in yellow/orange. Expired batches are flagged in red.

### F. View Audit Logs & History
1. Click **Inventory Logs** in the sidebar.
2. View a complete audit trail of every receipt, production run, and stock adjustment with exact timestamps and balances.

---

## 4. Changing Your Password
1. Click **Profile** in the bottom of the sidebar.
2. Enter your current password and choose a new password (8+ characters, including numbers and letters).
3. Click **Update Password**.
