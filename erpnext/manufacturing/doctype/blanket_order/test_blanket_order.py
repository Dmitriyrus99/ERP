# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, today

from erpnext import get_company_currency
from erpnext.stock.doctype.item.test_item import make_item

from .blanket_order import make_order


class TestBlanketOrder(FrappeTestCase):
	def setUp(self):
		frappe.flags.args = frappe._dict()

	def test_sales_order_creation(self):
		bo = make_blanket_order(blanket_order_type="Selling")

		frappe.flags.args.doctype = "Sales Order"
		so = make_order(bo.name)
		so.currency = get_company_currency(so.company)
		so.delivery_date = today()
		so.items[0].qty = 10
		so.submit()

		self.assertEqual(so.doctype, "Sales Order")
		self.assertEqual(len(so.get("items")), len(bo.get("items")))

		# check the rate, quantity and updation for the ordered quantity
		self.assertEqual(so.items[0].rate, bo.items[0].rate)

		bo = frappe.get_doc("Blanket Order", bo.name)
		self.assertEqual(so.items[0].qty, bo.items[0].ordered_qty)

		# test the quantity
		frappe.flags.args.doctype = "Sales Order"
		so1 = make_order(bo.name)
		so1.currency = get_company_currency(so1.company)
		self.assertEqual(so1.items[0].qty, (bo.items[0].qty - bo.items[0].ordered_qty))

	def test_purchase_order_creation(self):
		bo = make_blanket_order(blanket_order_type="Purchasing")

		frappe.flags.args.doctype = "Purchase Order"
		po = make_order(bo.name)
		po.currency = get_company_currency(po.company)
		po.schedule_date = today()
		po.items[0].qty = 10
		po.submit()

		self.assertEqual(po.doctype, "Purchase Order")
		self.assertEqual(len(po.get("items")), len(bo.get("items")))

		# check the rate, quantity and updation for the ordered quantity
		self.assertEqual(po.items[0].rate, po.items[0].rate)

		bo = frappe.get_doc("Blanket Order", bo.name)
		self.assertEqual(po.items[0].qty, bo.items[0].ordered_qty)

		# test the quantity
		frappe.flags.args.doctype = "Purchase Order"
		po1 = make_order(bo.name)
		po1.currency = get_company_currency(po1.company)
		self.assertEqual(po1.items[0].qty, (bo.items[0].qty - bo.items[0].ordered_qty))

	def test_blanket_order_allowance(self):
		# Sales Order
		bo = make_blanket_order(blanket_order_type="Selling", quantity=100)

		frappe.flags.args.doctype = "Sales Order"
		so = make_order(bo.name)
		so.currency = get_company_currency(so.company)
		so.delivery_date = today()
		so.items[0].qty = 110
		self.assertRaises(frappe.ValidationError, so.submit)

		frappe.db.set_single_value("Selling Settings", "blanket_order_allowance", 10)
		so.submit()

		# Purchase Order
		bo = make_blanket_order(blanket_order_type="Purchasing", quantity=100)

		frappe.flags.args.doctype = "Purchase Order"
		po = make_order(bo.name)
		po.currency = get_company_currency(po.company)
		po.schedule_date = today()
		po.items[0].qty = 110
		self.assertRaises(frappe.ValidationError, po.submit)

		frappe.db.set_single_value("Buying Settings", "blanket_order_allowance", 10)
		po.submit()

	def test_party_item_code(self):
		item_doc = make_item("_Test Item 1 for Blanket Order")
		item_code = item_doc.name

		customer = "_Test Customer"
		supplier = "_Test Supplier"

		if not frappe.db.exists("Item Customer Detail", {"customer_name": customer, "parent": item_code}):
			item_doc.append("customer_items", {"customer_name": customer, "ref_code": "CUST-REF-1"})
			item_doc.save()

		if not frappe.db.exists("Item Supplier", {"supplier": supplier, "parent": item_code}):
			item_doc.append("supplier_items", {"supplier": supplier, "supplier_part_no": "SUPP-PART-1"})
			item_doc.save()

		# Blanket Order for Selling
		bo = make_blanket_order(blanket_order_type="Selling", customer=customer, item_code=item_code)
		self.assertEqual(bo.items[0].party_item_code, "CUST-REF-1")

		bo = make_blanket_order(blanket_order_type="Purchasing", supplier=supplier, item_code=item_code)
		self.assertEqual(bo.items[0].party_item_code, "SUPP-PART-1")

	def test_blanket_order_to_invoice_TC_B_102(self):
		#Scenario : BO=>PO=>PR=PI
		item_doc = make_item("_Test Item 1 for Blanket Order")
		item_code = item_doc.name

		# 1. Create Blanket Order
		bo_data = {
			"doctype": "Blanket Order",
			"order_type": "Purchasing",
			"supplier": "_Test Suppliers",
			"company": "_Test Company",
			"from_date": "2025-01-01",
			"to_date": "2025-01-31",
			"items": [
				{
					"item_code": item_code,
					"qty": 1000,
					"rate": 100
				}
			]
		}
		blanket_order = frappe.get_doc(bo_data)
		blanket_order.insert()
		blanket_order.submit()

		# 2. Create Purchase Order from Blanket Order
		po_data = {
			"doctype": "Purchase Order",
			"supplier": "_Test Suppliers",
			"company": "_Test Company",
			"blanket_order": blanket_order.name,
			"schedule_date": "2025-01-10",
			"items": [
				{
					"item_code": item_code,
					"qty": 1000,
					"rate": 100,
					"warehouse": "Stores - _TC"
				}
			],
		}
		purchase_order = frappe.get_doc(po_data)
		purchase_order.insert()

		tax_list = create_taxes_interstate()
		for tax in tax_list:
			purchase_order.append("taxes", tax)
		purchase_order.submit()

		# 3. Validate Blanket Order Updates
		blanket_order.reload()
		self.assertEqual(blanket_order.ordered_qty, 1000)
		self.assertIn(purchase_order.name, [ref.reference_name for ref in blanket_order.references])

		# 4. Create Purchase Receipt from PO
		pr_data = {
			"doctype": "Purchase Receipt",
			"supplier": "_Test Suppliers",
			"company": "_Test Company",
			"items": purchase_order.items
		}
		purchase_receipt = frappe.get_doc(pr_data)
		purchase_receipt.insert()
		purchase_receipt.submit()

		# Validate PR Accounting Entries
		pr_gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": purchase_receipt.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock In Hand" and entry["debit"] == 100000 for entry in pr_gl_entries))
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed" and entry["credit"] == 100000 for entry in pr_gl_entries))

		# 5. Create Purchase Invoice from PR
		pi_data = {
			"doctype": "Purchase Invoice",
			"supplier": "_Test Suppliers",
			"company": "_Test Company",
			"items": purchase_receipt.items,
			"taxes": purchase_order.taxes,
			"supplier_invoice_no": "INV-001"
		}
		purchase_invoice = frappe.get_doc(pi_data)
		purchase_invoice.insert()
		purchase_invoice.submit()

		# Validate PI Accounting Entries
		pi_gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": purchase_invoice.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed" and entry["debit"] == 100000 for entry in pi_gl_entries))
		self.assertTrue(any(entry["account"] == "CGST" and entry["debit"] == 9000 for entry in pi_gl_entries))
		self.assertTrue(any(entry["account"] == "SGST" and entry["debit"] == 9000 for entry in pi_gl_entries))
		self.assertTrue(any(entry["account"] == "Creditors" and entry["credit"] == 118000 for entry in pi_gl_entries))

def make_blanket_order(**args):
	args = frappe._dict(args)
	bo = frappe.new_doc("Blanket Order")
	bo.blanket_order_type = args.blanket_order_type
	bo.company = args.company or "_Test Company"

	if args.blanket_order_type == "Selling":
		bo.customer = args.customer or "_Test Customer"
	else:
		bo.supplier = args.supplier or "_Test Supplier"

	bo.from_date = today()
	bo.to_date = add_months(bo.from_date, months=12)

	bo.append(
		"items",
		{
			"item_code": args.item_code or "_Test Item",
			"qty": args.quantity or 1000,
			"rate": args.rate or 100,
		},
	)

	bo.insert()
	bo.submit()
	return bo

def create_taxes_interstate():

		acc = frappe.new_doc("Account")
		acc.account_name = "Input Tax CGST"
		acc.parent_account = "Tax Assets - _TC"
		acc.company = "_Test Company"
		account_name_cgst = frappe.db.exists("Account", {"account_name" : "Input Tax CGST","company": "_Test Company" })
		if not account_name_cgst:
			account_name_cgst = acc.insert()

		
		acc = frappe.new_doc("Account")
		acc.account_name = "Input Tax SGST"
		acc.parent_account = "Tax Assets - _TC"
		acc.company = "_Test Company"
		account_name_sgst = frappe.db.exists("Account", {"account_name" : "Input Tax SGST","company": "_Test Company" })
		if not account_name_sgst:
			account_name_sgst = acc.insert()
		
		return [
			{
                    "charge_type": "On Net Total",
                    "account_head": account_name_cgst,
                    "rate": 9,
                    "description": "Input GST",
            },
			{
                    "charge_type": "On Net Total",
                    "account_head": account_name_sgst,
                    "rate": 9,
                    "description": "Input GST",
            }
		]
