# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.tests.utils import FrappeTestCase
from erpnext.buying.doctype.supplier_quotation.supplier_quotation import make_quotation
from frappe.utils import add_days, add_months, flt, getdate, nowdate, today


class TestPurchaseOrder(FrappeTestCase):
	def test_make_purchase_order(self):
		from erpnext.buying.doctype.supplier_quotation.supplier_quotation import make_purchase_order

		sq = frappe.copy_doc(test_records[0]).insert()

		self.assertRaises(frappe.ValidationError, make_purchase_order, sq.name)

		sq = frappe.get_doc("Supplier Quotation", sq.name)
		sq.submit()
		po = make_purchase_order(sq.name)

		self.assertEqual(po.doctype, "Purchase Order")
		self.assertEqual(len(po.get("items")), len(sq.get("items")))

		po.naming_series = "_T-Purchase Order-"

		for doc in po.get("items"):
			if doc.get("item_code"):
				doc.set("schedule_date", "2013-04-12")

		po.insert()

	# test make quotation from supplier quotation 
	def test_make_quotation(self):
		sq = frappe.copy_doc(test_records[0]).insert()
		sq = frappe.get_doc("Supplier Quotation", sq.name)
		sq.submit()
	
		qt = make_quotation(sq.name)
		qt.quotation_to = 'Customer'
		qt.customer_name = '_Test Customer'
		qt.submit()
		
		self.assertEqual(sq.doctype, "Supplier Quotation")
		self.assertEqual(qt.doctype, "Quotation")
		self.assertEqual(len(sq.get("items")), len(qt.get("items")))
		self.assertEqual(sq.get("items")[0].item_code, qt.get("items")[0].item_code)
		self.assertEqual(sq.get("items")[0].qty, qt.get("items")[0].qty)

	# To check if valid_till is yesterday then document status should be Expired
	def test_supplier_quotation_expiry(self):
		from erpnext.buying.doctype.supplier_quotation.supplier_quotation import set_expired_status
		yesterday = add_days(nowdate(), -1)

		sq = frappe.copy_doc(test_records[0]).insert()
		sq = frappe.get_doc("Supplier Quotation", sq.name)
		sq.transaction_date=yesterday
		sq.valid_till = yesterday
		sq.submit()	
		set_expired_status()
		sq.reload()
		self.assertEqual(sq.status, "Expired")

	def test_validate_valid_till_TC_B_175(self):
		sq = frappe.copy_doc(test_records[0]).insert()
		sq.transaction_date = today()
		sq.valid_till = add_days(today(), -1)
		self.assertRaises(frappe.ValidationError, sq.save)

	def test_check_supplier_quotation_status_on_cancel_TC_B_176(self):
		sq = frappe.copy_doc(test_records[0]).insert()
		sq = frappe.get_doc("Supplier Quotation", sq.name)
		sq.submit()
		self.assertEqual(sq.docstatus, 1)

		sq.load_from_db()
		sq.cancel()
		self.assertEqual(sq.status, "Cancelled")

	def test_make_pi_from_sq_TC_B_177(self):
		from .supplier_quotation import make_purchase_invoice

		sq = frappe.copy_doc(test_records[0]).insert()
		sq = frappe.get_doc("Supplier Quotation", sq.name)
		sq.submit()
		self.assertEqual(sq.docstatus, 1)

		pi = make_purchase_invoice(sq.name)
		pi.insert()
		pi.submit()
		self.assertEqual(pi.docstatus, 1)

	def test_get_list_context_TC_B_178(self):
		from .supplier_quotation import get_list_context
		context = {}
		result = get_list_context(context)

		self.assertIsInstance(result, dict)
		self.assertTrue(result.get("show_sidebar"))
		self.assertTrue(result.get("show_search"))
		self.assertTrue(result.get("no_breadcrumbs"))
		self.assertEqual(result.get("title"), ("Supplier Quotation"))

test_records = frappe.get_test_records("Supplier Quotation")
