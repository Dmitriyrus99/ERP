# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json

import frappe
import pandas as pd
from frappe.tests.utils import FrappeTestCase, change_settings
from frappe.utils import add_days, flt, getdate, nowdate
from frappe.utils.data import today

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.party import get_due_date_from_template
from erpnext.buying.doctype.purchase_order.purchase_order import (
	make_inter_company_sales_order,
	make_purchase_receipt,
)
from erpnext.buying.doctype.purchase_order.purchase_order import (
	make_purchase_invoice as make_pi_from_po,
)
from erpnext.controllers.accounts_controller import InvalidQtyError, update_child_qty_rate
from erpnext.manufacturing.doctype.blanket_order.test_blanket_order import make_blanket_order
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.material_request.material_request import make_purchase_order
from erpnext.stock.doctype.material_request.test_material_request import make_material_request
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
	make_purchase_invoice as make_pi_from_pr,
)
from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request
from io import BytesIO

class TestPurchaseOrder(FrappeTestCase):
	def test_purchase_order_qty(self):
		po = create_purchase_order(qty=1, do_not_save=True)
		po.append(
			"items",
			{
				"item_code": "_Test Item",
				"qty": -1,
				"rate": 10,
			},
		)
		self.assertRaises(frappe.NonNegativeError, po.save)

		po.items[1].qty = 0
		self.assertRaises(InvalidQtyError, po.save)

	def test_make_purchase_receipt(self):
		po = create_purchase_order(do_not_submit=True)
		self.assertRaises(frappe.ValidationError, make_purchase_receipt, po.name)
		po.submit()

		pr = create_pr_against_po(po.name)
		self.assertEqual(len(pr.get("items")), 1)

	def test_ordered_qty(self):
		existing_ordered_qty = get_ordered_qty()

		po = create_purchase_order(do_not_submit=True)
		self.assertRaises(frappe.ValidationError, make_purchase_receipt, po.name)

		po.submit()
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 10)

		create_pr_against_po(po.name)
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 6)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 4)

		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 50)

		pr = create_pr_against_po(po.name, received_qty=8)
		self.assertEqual(get_ordered_qty(), existing_ordered_qty)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 12)

		pr.cancel()
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 6)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 4)

	def test_ordered_qty_against_pi_with_update_stock(self):
		existing_ordered_qty = get_ordered_qty()
		po = create_purchase_order()

		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 10)

		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 50)
		frappe.db.set_value("Item", "_Test Item", "over_billing_allowance", 20)

		pi = make_pi_from_po(po.name)
		pi.update_stock = 1
		pi.items[0].qty = 12
		pi.insert()
		pi.submit()

		self.assertEqual(get_ordered_qty(), existing_ordered_qty)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 12)

		pi.cancel()
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 10)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 0)

		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 0)
		frappe.db.set_value("Item", "_Test Item", "over_billing_allowance", 0)
		frappe.db.set_single_value("Accounts Settings", "over_billing_allowance", 0)

	def test_update_remove_child_linked_to_mr(self):
		"""Test impact on linked PO and MR on deleting/updating row."""
		mr = make_material_request(qty=10)
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.save()
		po.submit()

		first_item_of_po = po.get("items")[0]
		existing_ordered_qty = get_ordered_qty()  # 10
		existing_requested_qty = get_requested_qty()  # 0

		# decrease ordered qty by 3 (10 -> 7) and add item
		trans_item = json.dumps(
			[
				{
					"item_code": first_item_of_po.item_code,
					"rate": first_item_of_po.rate,
					"qty": 7,
					"docname": first_item_of_po.name,
				},
				{"item_code": "_Test Item 2", "rate": 200, "qty": 2},
			]
		)
		update_child_qty_rate("Purchase Order", trans_item, po.name)
		mr.reload()

		# requested qty increases as ordered qty decreases
		self.assertEqual(get_requested_qty(), existing_requested_qty + 3)  # 3
		self.assertEqual(mr.items[0].ordered_qty, 7)

		self.assertEqual(get_ordered_qty(), existing_ordered_qty - 3)  # 7

		# delete first item linked to Material Request
		trans_item = json.dumps([{"item_code": "_Test Item 2", "rate": 200, "qty": 2}])
		update_child_qty_rate("Purchase Order", trans_item, po.name)
		mr.reload()

		# requested qty increases as ordered qty is 0 (deleted row)
		self.assertEqual(get_requested_qty(), existing_requested_qty + 10)  # 10
		self.assertEqual(mr.items[0].ordered_qty, 0)

		# ordered qty decreases as ordered qty is 0 (deleted row)
		self.assertEqual(get_ordered_qty(), existing_ordered_qty - 10)  # 0

	def test_update_child(self):
		mr = make_material_request(qty=10)
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.items[0].qty = 4
		po.save()
		po.submit()

		create_pr_against_po(po.name)

		make_pi_from_po(po.name)

		existing_ordered_qty = get_ordered_qty()
		existing_requested_qty = get_requested_qty()

		trans_item = json.dumps(
			[{"item_code": "_Test Item", "rate": 200, "qty": 7, "docname": po.items[0].name}]
		)
		update_child_qty_rate("Purchase Order", trans_item, po.name)

		mr.reload()
		self.assertEqual(mr.items[0].ordered_qty, 7)
		self.assertEqual(mr.per_ordered, 70)
		self.assertEqual(get_requested_qty(), existing_requested_qty - 3)

		po.reload()
		self.assertEqual(po.get("items")[0].rate, 200)
		self.assertEqual(po.get("items")[0].qty, 7)
		self.assertEqual(po.get("items")[0].amount, 1400)
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 3)

	def test_update_child_adding_new_item(self):
		po = create_purchase_order(do_not_save=1)
		po.items[0].qty = 4
		po.save()
		po.submit()
		make_pr_against_po(po.name, 2)

		po.load_from_db()
		existing_ordered_qty = get_ordered_qty()
		first_item_of_po = po.get("items")[0]

		trans_item = json.dumps(
			[
				{
					"item_code": first_item_of_po.item_code,
					"rate": first_item_of_po.rate,
					"qty": first_item_of_po.qty,
					"docname": first_item_of_po.name,
				},
				{"item_code": "_Test Item", "rate": 200, "qty": 7},
			]
		)
		update_child_qty_rate("Purchase Order", trans_item, po.name)

		po.reload()
		self.assertEqual(len(po.get("items")), 2)
		self.assertEqual(po.status, "To Receive and Bill")
		# ordered qty should increase on row addition
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 7)

	def test_update_child_removing_item(self):
		po = create_purchase_order(do_not_save=1)
		po.items[0].qty = 4
		po.save()
		po.submit()
		make_pr_against_po(po.name, 2)

		po.reload()
		first_item_of_po = po.get("items")[0]
		existing_ordered_qty = get_ordered_qty()
		# add an item
		trans_item = json.dumps(
			[
				{
					"item_code": first_item_of_po.item_code,
					"rate": first_item_of_po.rate,
					"qty": first_item_of_po.qty,
					"docname": first_item_of_po.name,
				},
				{"item_code": "_Test Item", "rate": 200, "qty": 7},
			]
		)
		update_child_qty_rate("Purchase Order", trans_item, po.name)

		po.reload()

		# ordered qty should increase on row addition
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 7)

		# check if can remove received item
		trans_item = json.dumps(
			[{"item_code": "_Test Item", "rate": 200, "qty": 7, "docname": po.get("items")[1].name}]
		)
		self.assertRaises(
			frappe.ValidationError, update_child_qty_rate, "Purchase Order", trans_item, po.name
		)

		first_item_of_po = po.get("items")[0]
		trans_item = json.dumps(
			[
				{
					"item_code": first_item_of_po.item_code,
					"rate": first_item_of_po.rate,
					"qty": first_item_of_po.qty,
					"docname": first_item_of_po.name,
				}
			]
		)
		update_child_qty_rate("Purchase Order", trans_item, po.name)

		po.reload()
		self.assertEqual(len(po.get("items")), 1)
		self.assertEqual(po.status, "To Receive and Bill")

		# ordered qty should decrease (back to initial) on row deletion
		self.assertEqual(get_ordered_qty(), existing_ordered_qty)

	def test_update_child_perm(self):
		po = create_purchase_order(item_code="_Test Item", qty=4)

		user = "test@example.com"
		test_user = frappe.get_doc("User", user)
		test_user.add_roles("Accounts User")
		frappe.set_user(user)

		# update qty
		trans_item = json.dumps(
			[{"item_code": "_Test Item", "rate": 200, "qty": 7, "docname": po.items[0].name}]
		)
		self.assertRaises(
			frappe.ValidationError, update_child_qty_rate, "Purchase Order", trans_item, po.name
		)

		# add new item
		trans_item = json.dumps([{"item_code": "_Test Item", "rate": 100, "qty": 2}])
		self.assertRaises(
			frappe.ValidationError, update_child_qty_rate, "Purchase Order", trans_item, po.name
		)
		frappe.set_user("Administrator")

	def test_update_child_with_tax_template(self):
		"""
		Test Action: Create a PO with one item having its tax account head already in the PO.
		Add the same item + new item with tax template via Update Items.
		Expected result: First Item's tax row is updated. New tax row is added for second Item.
		"""
		if not frappe.db.exists("Item", "Test Item with Tax"):
			make_item(
				"Test Item with Tax",
				{
					"is_stock_item": 1,
				},
			)

		if not frappe.db.exists("Item Tax Template", {"title": "Test Update Items Template"}):
			frappe.get_doc(
				{
					"doctype": "Item Tax Template",
					"title": "Test Update Items Template",
					"company": "_Test Company",
					"taxes": [
						{
							"tax_type": "_Test Account Service Tax - _TC",
							"tax_rate": 10,
						}
					],
				}
			).insert()

		new_item_with_tax = frappe.get_doc("Item", "Test Item with Tax")

		if not frappe.db.exists(
			"Item Tax",
			{"item_tax_template": "Test Update Items Template - _TC", "parent": "Test Item with Tax"},
		):
			new_item_with_tax.append(
				"taxes", {"item_tax_template": "Test Update Items Template - _TC", "valid_from": nowdate()}
			)
			new_item_with_tax.save()

		tax_template = "_Test Account Excise Duty @ 10 - _TC"
		item = "_Test Item Home Desktop 100"
		if not frappe.db.exists("Item Tax", {"parent": item, "item_tax_template": tax_template}):
			item_doc = frappe.get_doc("Item", item)
			item_doc.append("taxes", {"item_tax_template": tax_template, "valid_from": nowdate()})
			item_doc.save()
		else:
			# update valid from
			frappe.db.sql(
				"""UPDATE `tabItem Tax` set valid_from = CURRENT_DATE
				where parent = %(item)s and item_tax_template = %(tax)s""",
				{"item": item, "tax": tax_template},
			)

		po = create_purchase_order(item_code=item, qty=1, do_not_save=1)

		po.append(
			"taxes",
			{
				"account_head": "_Test Account Excise Duty - _TC",
				"charge_type": "On Net Total",
				"cost_center": "_Test Cost Center - _TC",
				"description": "Excise Duty",
				"doctype": "Purchase Taxes and Charges",
				"rate": 10,
			},
		)
		po.insert()
		po.submit()

		self.assertEqual(po.taxes[0].tax_amount, 50)
		self.assertEqual(po.taxes[0].total, 550)

		items = json.dumps(
			[
				{"item_code": item, "rate": 500, "qty": 1, "docname": po.items[0].name},
				{
					"item_code": item,
					"rate": 100,
					"qty": 1,
				},  # added item whose tax account head already exists in PO
				{
					"item_code": new_item_with_tax.name,
					"rate": 100,
					"qty": 1,
				},  # added item whose tax account head  is missing in PO
			]
		)
		update_child_qty_rate("Purchase Order", items, po.name)

		po.reload()
		self.assertEqual(po.taxes[0].tax_amount, 70)
		self.assertEqual(po.taxes[0].total, 770)
		self.assertEqual(po.taxes[1].account_head, "_Test Account Service Tax - _TC")
		self.assertEqual(po.taxes[1].tax_amount, 70)
		self.assertEqual(po.taxes[1].total, 840)

		# teardown
		frappe.db.sql(
			"""UPDATE `tabItem Tax` set valid_from = NULL
			where parent = %(item)s and item_tax_template = %(tax)s""",
			{"item": item, "tax": tax_template},
		)
		po.cancel()
		po.delete()
		new_item_with_tax.delete()
		frappe.get_doc("Item Tax Template", "Test Update Items Template - _TC").delete()

	def test_update_qty(self):
		po = create_purchase_order()

		pr = make_pr_against_po(po.name, 2)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 2)

		# Check received_qty after making PI from PR without update_stock checked
		pi1 = make_pi_from_pr(pr.name)
		pi1.get("items")[0].qty = 2
		pi1.insert()
		pi1.submit()

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 2)

		# Check received_qty after making PI from PO with update_stock checked
		pi2 = make_pi_from_po(po.name)
		pi2.set("update_stock", 1)
		pi2.get("items")[0].qty = 3
		pi2.insert()
		pi2.submit()

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 5)

		# Check received_qty after making PR from PO
		pr = make_pr_against_po(po.name, 1)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 6)

	def test_return_against_purchase_order(self):
		po = create_purchase_order()

		pr = make_pr_against_po(po.name, 6)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 6)

		pi2 = make_pi_from_po(po.name)
		pi2.set("update_stock", 1)
		pi2.get("items")[0].qty = 3
		pi2.insert()
		pi2.submit()

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 9)

		# Make return purchase receipt, purchase invoice and check quantity
		from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import (
			make_purchase_invoice as make_purchase_invoice_return,
		)
		from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import (
			make_purchase_receipt as make_purchase_receipt_return,
		)

		pr1 = make_purchase_receipt_return(is_return=1, return_against=pr.name, qty=-3, do_not_submit=True)
		pr1.items[0].purchase_order = po.name
		pr1.items[0].purchase_order_item = po.items[0].name
		pr1.submit()

		pi1 = make_purchase_invoice_return(
			is_return=1, return_against=pi2.name, qty=-1, update_stock=1, do_not_submit=True
		)
		pi1.items[0].purchase_order = po.name
		pi1.items[0].po_detail = po.items[0].name
		pi1.submit()

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 5)

	def test_purchase_order_invoice_receipt_workflow(self):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_purchase_receipt

		po = create_purchase_order()
		pi = make_pi_from_po(po.name)

		pi.submit()

		pr = make_purchase_receipt(pi.name)
		pr.submit()

		pi.load_from_db()

		self.assertEqual(pi.per_received, 100.00)
		self.assertEqual(pi.items[0].qty, pi.items[0].received_qty)

		po.load_from_db()

		self.assertEqual(po.per_received, 100.00)
		self.assertEqual(po.per_billed, 100.00)

		pr.cancel()

		pi.load_from_db()
		pi.cancel()

		po.load_from_db()
		po.cancel()

	def test_make_purchase_invoice(self):
		po = create_purchase_order(do_not_submit=True)

		self.assertRaises(frappe.ValidationError, make_pi_from_po, po.name)

		po.submit()
		pi = make_pi_from_po(po.name)

		self.assertEqual(pi.doctype, "Purchase Invoice")
		self.assertEqual(len(pi.get("items", [])), 1)

	def test_purchase_order_on_hold(self):
		po = create_purchase_order(item_code="_Test Product Bundle Item")
		po.db_set("status", "On Hold")
		pi = make_pi_from_po(po.name)
		pr = make_purchase_receipt(po.name)
		self.assertRaises(frappe.ValidationError, pr.submit)
		self.assertRaises(frappe.ValidationError, pi.submit)

	def test_make_purchase_invoice_with_terms(self):
		from erpnext.selling.doctype.sales_order.test_sales_order import (
			automatically_fetch_payment_terms,
		)

		automatically_fetch_payment_terms()
		po = create_purchase_order(do_not_save=True)

		self.assertRaises(frappe.ValidationError, make_pi_from_po, po.name)

		po.update({"payment_terms_template": "_Test Payment Term Template"})

		po.save()
		po.submit()

		self.assertEqual(po.payment_schedule[0].payment_amount, 2500.0)
		self.assertEqual(getdate(po.payment_schedule[0].due_date), getdate(po.transaction_date))
		self.assertEqual(po.payment_schedule[1].payment_amount, 2500.0)
		self.assertEqual(getdate(po.payment_schedule[1].due_date), add_days(getdate(po.transaction_date), 30))
		pi = make_pi_from_po(po.name)
		pi.save()

		self.assertEqual(pi.doctype, "Purchase Invoice")
		self.assertEqual(len(pi.get("items", [])), 1)

		self.assertEqual(pi.payment_schedule[0].payment_amount, 2500.0)
		self.assertEqual(getdate(pi.payment_schedule[0].due_date), getdate(po.transaction_date))
		self.assertEqual(pi.payment_schedule[1].payment_amount, 2500.0)
		self.assertEqual(getdate(pi.payment_schedule[1].due_date), add_days(getdate(po.transaction_date), 30))
		automatically_fetch_payment_terms(enable=0)

	def test_warehouse_company_validation(self):
		from erpnext.stock.utils import InvalidWarehouseCompany

		po = create_purchase_order(company="_Test Company 1", do_not_save=True)
		self.assertRaises(InvalidWarehouseCompany, po.insert)

	def test_uom_integer_validation(self):
		from erpnext.utilities.transaction_base import UOMMustBeIntegerError

		po = create_purchase_order(qty=3.4, do_not_save=True)
		self.assertRaises(UOMMustBeIntegerError, po.insert)

	def test_ordered_qty_for_closing_po(self):
		bin = frappe.get_all(
			"Bin",
			filters={"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"},
			fields=["ordered_qty"],
		)

		existing_ordered_qty = bin[0].ordered_qty if bin else 0.0

		po = create_purchase_order(item_code="_Test Item", qty=1)

		self.assertEqual(
			get_ordered_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"),
			existing_ordered_qty + 1,
		)

		po.update_status("Closed")

		self.assertEqual(
			get_ordered_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"), existing_ordered_qty
		)

	def test_group_same_items(self):
		frappe.db.set_single_value("Buying Settings", "allow_multiple_items", 1)
		frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"company": "_Test Company",
				"supplier": "_Test Supplier",
				"is_subcontracted": 0,
				"schedule_date": add_days(nowdate(), 1),
				"currency": frappe.get_cached_value("Company", "_Test Company", "default_currency"),
				"conversion_factor": 1,
				"items": get_same_items(),
				"group_same_items": 1,
			}
		).insert(ignore_permissions=True)

	def test_make_po_without_terms(self):
		po = create_purchase_order(do_not_save=1)

		self.assertFalse(po.get("payment_schedule"))

		po.insert()

		self.assertTrue(po.get("payment_schedule"))

	def test_po_for_blocked_supplier_all(self):
		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		supplier.on_hold = 1
		supplier.save()

		self.assertEqual(supplier.hold_type, "All")
		self.assertRaises(frappe.ValidationError, create_purchase_order)

		supplier.on_hold = 0
		supplier.save()

	def test_po_for_blocked_supplier_invoices(self):
		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		supplier.on_hold = 1
		supplier.hold_type = "Invoices"
		supplier.save()

		self.assertRaises(frappe.ValidationError, create_purchase_order)

		supplier.on_hold = 0
		supplier.save()

	def test_po_for_blocked_supplier_payments(self):
		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		supplier.on_hold = 1
		supplier.hold_type = "Payments"
		supplier.save()

		po = create_purchase_order()

		self.assertRaises(
			frappe.ValidationError,
			get_payment_entry,
			dt="Purchase Order",
			dn=po.name,
			bank_account="_Test Bank - _TC",
		)

		supplier.on_hold = 0
		supplier.save()

	def test_po_for_blocked_supplier_payments_with_today_date(self):
		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		supplier.on_hold = 1
		supplier.release_date = nowdate()
		supplier.hold_type = "Payments"
		supplier.save()

		po = create_purchase_order()

		self.assertRaises(
			frappe.ValidationError,
			get_payment_entry,
			dt="Purchase Order",
			dn=po.name,
			bank_account="_Test Bank - _TC",
		)

		supplier.on_hold = 0
		supplier.save()

	def test_po_for_blocked_supplier_payments_past_date(self):
		# this test is meant to fail only if something fails in the try block
		with self.assertRaises(Exception):
			try:
				supplier = frappe.get_doc("Supplier", "_Test Supplier")
				supplier.on_hold = 1
				supplier.hold_type = "Payments"
				supplier.release_date = "2018-03-01"
				supplier.save()

				po = create_purchase_order()
				get_payment_entry("Purchase Order", po.name, bank_account="_Test Bank - _TC")

				supplier.on_hold = 0
				supplier.save()
			except Exception:
				pass
			else:
				raise Exception

	def test_default_payment_terms(self):
		due_date = get_due_date_from_template("_Test Payment Term Template 1", "2023-02-03", None).strftime(
			"%Y-%m-%d"
		)
		self.assertEqual(due_date, "2023-03-31")

	def test_terms_are_not_copied_if_automatically_fetch_payment_terms_is_unchecked(self):
		po = create_purchase_order(do_not_save=1)
		po.payment_terms_template = "_Test Payment Term Template"
		po.save()
		po.submit()

		frappe.db.set_value("Company", "_Test Company", "payment_terms", "_Test Payment Term Template 1")
		pi = make_pi_from_po(po.name)
		pi.save()

		self.assertEqual(pi.get("payment_terms_template"), "_Test Payment Term Template 1")
		frappe.db.set_value("Company", "_Test Company", "payment_terms", "")

	def test_terms_copied(self):
		po = create_purchase_order(do_not_save=1)
		po.payment_terms_template = "_Test Payment Term Template"
		po.insert()
		po.submit()
		self.assertTrue(po.get("payment_schedule"))

		pi = make_pi_from_po(po.name)
		pi.insert()
		self.assertTrue(pi.get("payment_schedule"))

	@change_settings("Accounts Settings", {"unlink_advance_payment_on_cancelation_of_order": 1})
	def test_advance_payment_entry_unlink_against_purchase_order(self):
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry

		po_doc = create_purchase_order()

		pe = get_payment_entry("Purchase Order", po_doc.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "1"
		pe.reference_date = nowdate()
		pe.paid_from_account_currency = po_doc.currency
		pe.paid_to_account_currency = po_doc.currency
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		pe.paid_amount = po_doc.grand_total
		pe.save(ignore_permissions=True)
		pe.submit()

		po_doc = frappe.get_doc("Purchase Order", po_doc.name)
		po_doc.cancel()

		pe_doc = frappe.get_doc("Payment Entry", pe.name)
		pe_doc.cancel()

	def create_account(self, account_name, company, currency, parent):
		if not frappe.db.get_value("Account", filters={"account_name": account_name, "company": company}):
			account = frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": account_name,
					"parent_account": parent,
					"company": company,
					"account_currency": currency,
					"is_group": 0,
					"account_type": "Payable",
				}
			).insert()
		else:
			account = frappe.get_doc("Account", {"account_name": account_name, "company": company})

		return account

	def test_advance_payment_with_separate_party_account_enabled(self):
		"""
		Test "Advance Paid" on Purchase Order, when "Book Advance Payments in Separate Party Account" is enabled and
		the payment entry linked to the Order is allocated to Purchase Invoice.
		"""
		supplier = "_Test Supplier"
		company = "_Test Company"

		# Setup default 'Advance Paid' account
		account = self.create_account("Advance Paid", company, "INR", "Application of Funds (Assets) - _TC")
		company_doc = frappe.get_doc("Company", company)
		company_doc.book_advance_payments_in_separate_party_account = True
		company_doc.default_advance_paid_account = account.name
		company_doc.save()

		po_doc = create_purchase_order(supplier=supplier)

		from erpnext.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry

		pe = get_payment_entry("Purchase Order", po_doc.name)
		pe.save().submit()

		po_doc.reload()
		self.assertEqual(po_doc.advance_paid, 5000)

		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		company_doc.book_advance_payments_in_separate_party_account = False
		company_doc.save()

	@change_settings("Accounts Settings", {"unlink_advance_payment_on_cancelation_of_order": 1})
	def test_advance_paid_upon_payment_entry_cancellation(self):
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry

		supplier = "_Test Supplier USD"
		company = "_Test Company"

		# Setup default USD payable account for Supplier
		account = self.create_account("Creditors USD", company, "USD", "Accounts Payable - _TC")
		supplier_doc = frappe.get_doc("Supplier", supplier)
		if not [x for x in supplier_doc.accounts if x.company == company]:
			supplier_doc.append("accounts", {"company": company, "account": account.name})
			supplier_doc.save()

		po_doc = create_purchase_order(supplier=supplier, currency="USD", do_not_submit=1)
		po_doc.conversion_rate = 80
		po_doc.submit()

		pe = get_payment_entry("Purchase Order", po_doc.name)
		pe.mode_of_payment = "Cash"
		pe.paid_from = "Cash - _TC"
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 80
		pe.paid_amount = po_doc.base_grand_total
		pe.save(ignore_permissions=True)
		pe.submit()

		po_doc.reload()
		self.assertEqual(po_doc.advance_paid, po_doc.grand_total)
		self.assertEqual(po_doc.party_account_currency, "USD")

		pe_doc = frappe.get_doc("Payment Entry", pe.name)
		pe_doc.cancel()

		po_doc.reload()
		self.assertEqual(po_doc.advance_paid, 0)
		self.assertEqual(po_doc.party_account_currency, "USD")

	def test_schedule_date(self):
		po = create_purchase_order(do_not_submit=True)
		po.schedule_date = None
		po.append(
			"items",
			{"item_code": "_Test Item", "qty": 1, "rate": 100, "schedule_date": add_days(nowdate(), 5)},
		)
		po.save()
		self.assertEqual(po.schedule_date, add_days(nowdate(), 1))

		po.items[0].schedule_date = add_days(nowdate(), 2)
		po.save()
		self.assertEqual(po.schedule_date, add_days(nowdate(), 2))

	def test_po_optional_blanket_order(self):
		"""
		Expected result: Blanket order Ordered Quantity should only be affected on Purchase Order with against_blanket_order = 1.
		Second Purchase Order should not add on to Blanket Orders Ordered Quantity.
		"""

		make_blanket_order(blanket_order_type="Purchasing", quantity=10, rate=10)

		po = create_purchase_order(item_code="_Test Item", qty=5, against_blanket_order=1)
		po_doc = frappe.get_doc("Purchase Order", po.get("name"))
		# To test if the PO has a Blanket Order
		self.assertTrue(po_doc.items[0].blanket_order)

		po = create_purchase_order(item_code="_Test Item", qty=5, against_blanket_order=0)
		po_doc = frappe.get_doc("Purchase Order", po.get("name"))
		# To test if the PO does NOT have a Blanket Order
		self.assertEqual(po_doc.items[0].blanket_order, None)

	def test_blanket_order_on_po_close_and_open(self):
		# Step - 1: Create Blanket Order
		bo = make_blanket_order(blanket_order_type="Purchasing", quantity=10, rate=10)

		# Step - 2: Create Purchase Order
		po = create_purchase_order(
			item_code="_Test Item", qty=5, against_blanket_order=1, against_blanket=bo.name
		)

		bo.load_from_db()
		self.assertEqual(bo.items[0].ordered_qty, 5)

		# Step - 3: Close Purchase Order
		po.update_status("Closed")

		bo.load_from_db()
		self.assertEqual(bo.items[0].ordered_qty, 0)

		# Step - 4: Re-Open Purchase Order
		po.update_status("Re-open")

		bo.load_from_db()
		self.assertEqual(bo.items[0].ordered_qty, 5)

	def test_payment_terms_are_fetched_when_creating_purchase_invoice(self):
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import (
			create_payment_terms_template,
		)
		from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
		from erpnext.selling.doctype.sales_order.test_sales_order import (
			automatically_fetch_payment_terms,
			compare_payment_schedules,
		)

		automatically_fetch_payment_terms()

		po = create_purchase_order(qty=10, rate=100, do_not_save=1)
		create_payment_terms_template()
		po.payment_terms_template = "Test Receivable Template"
		po.submit()

		pi = make_purchase_invoice(qty=10, rate=100, do_not_save=1)
		pi.items[0].purchase_order = po.name
		pi.items[0].po_detail = po.items[0].name
		pi.insert()

		# self.assertEqual(po.payment_terms_template, pi.payment_terms_template)
		compare_payment_schedules(self, po, pi)

		automatically_fetch_payment_terms(enable=0)

	def test_internal_transfer_flow(self):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import (
			make_inter_company_purchase_invoice,
		)
		from erpnext.selling.doctype.sales_order.sales_order import (
			make_delivery_note,
			make_sales_invoice,
		)
		from erpnext.stock.doctype.delivery_note.delivery_note import make_inter_company_purchase_receipt

		frappe.db.set_single_value("Selling Settings", "maintain_same_sales_rate", 1)
		frappe.db.set_single_value("Buying Settings", "maintain_same_rate", 1)

		prepare_data_for_internal_transfer()
		supplier = "_Test Internal Supplier 2"

		mr = make_material_request(
			qty=2, company="_Test Company with perpetual inventory", warehouse="Stores - TCP1"
		)

		po = create_purchase_order(
			company="_Test Company with perpetual inventory",
			supplier=supplier,
			warehouse="Stores - TCP1",
			from_warehouse="_Test Internal Warehouse New 1 - TCP1",
			qty=2,
			rate=1,
			material_request=mr.name,
			material_request_item=mr.items[0].name,
		)

		so = make_inter_company_sales_order(po.name)
		so.items[0].delivery_date = today()
		self.assertEqual(so.items[0].warehouse, "_Test Internal Warehouse New 1 - TCP1")
		self.assertTrue(so.items[0].purchase_order)
		self.assertTrue(so.items[0].purchase_order_item)
		so.submit()

		dn = make_delivery_note(so.name)
		dn.items[0].target_warehouse = "_Test Internal Warehouse GIT - TCP1"
		self.assertEqual(dn.items[0].warehouse, "_Test Internal Warehouse New 1 - TCP1")
		self.assertTrue(dn.items[0].purchase_order)
		self.assertTrue(dn.items[0].purchase_order_item)

		self.assertEqual(po.items[0].name, dn.items[0].purchase_order_item)
		dn.submit()

		pr = make_inter_company_purchase_receipt(dn.name)
		self.assertEqual(pr.items[0].warehouse, "Stores - TCP1")
		self.assertTrue(pr.items[0].purchase_order)
		self.assertTrue(pr.items[0].purchase_order_item)
		self.assertEqual(po.items[0].name, pr.items[0].purchase_order_item)
		pr.submit()

		si = make_sales_invoice(so.name)
		self.assertEqual(si.items[0].warehouse, "_Test Internal Warehouse New 1 - TCP1")
		self.assertTrue(si.items[0].purchase_order)
		self.assertTrue(si.items[0].purchase_order_item)
		si.submit()

		pi = make_inter_company_purchase_invoice(si.name)
		self.assertTrue(pi.items[0].purchase_order)
		self.assertTrue(pi.items[0].po_detail)
		pi.submit()
		mr.reload()

		po.load_from_db()
		self.assertEqual(po.status, "Completed")
		self.assertEqual(mr.status, "Received")

	def test_variant_item_po(self):
		po = create_purchase_order(item_code="_Test Variant Item", qty=1, rate=100, do_not_save=1)

		self.assertRaises(frappe.ValidationError, po.save)

	def test_update_items_for_subcontracting_purchase_order(self):
		from erpnext.controllers.tests.test_subcontracting_controller import (
			get_subcontracting_order,
			make_bom_for_subcontracted_items,
			make_raw_materials,
			make_service_items,
			make_subcontracted_items,
		)

		def update_items(po, qty):
			trans_items = [po.items[0].as_dict().update({"docname": po.items[0].name})]
			trans_items[0]["qty"] = qty
			trans_items[0]["fg_item_qty"] = qty
			trans_items = json.dumps(trans_items, default=str)

			return update_child_qty_rate(
				po.doctype,
				trans_items,
				po.name,
			)

		make_subcontracted_items()
		make_raw_materials()
		make_service_items()
		make_bom_for_subcontracted_items()

		service_items = [
			{
				"warehouse": "_Test Warehouse - _TC",
				"item_code": "Subcontracted Service Item 7",
				"qty": 10,
				"rate": 100,
				"fg_item": "Subcontracted Item SA7",
				"fg_item_qty": 10,
			},
		]
		po = create_purchase_order(
			rm_items=service_items,
			is_subcontracted=1,
			supplier_warehouse="_Test Warehouse 1 - _TC",
		)

		update_items(po, qty=20)
		po.reload()

		# Test - 1: Items should be updated as there is no Subcontracting Order against PO
		self.assertEqual(po.items[0].qty, 20)
		self.assertEqual(po.items[0].fg_item_qty, 20)

		sco = get_subcontracting_order(po_name=po.name, warehouse="_Test Warehouse - _TC")

		# Test - 2: ValidationError should be raised as there is Subcontracting Order against PO
		self.assertRaises(frappe.ValidationError, update_items, po=po, qty=30)

		sco.reload()
		sco.cancel()
		po.reload()

		update_items(po, qty=30)
		po.reload()

		# Test - 3: Items should be updated as the Subcontracting Order is cancelled
		self.assertEqual(po.items[0].qty, 30)
		self.assertEqual(po.items[0].fg_item_qty, 30)
	
	def test_new_sc_flow(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_subcontracting_order
		
		po = create_po_for_sc_testing()
		sco = make_subcontracting_order(po.name)
		
		sco.items[0].qty = 5
		sco.items.pop(1)
		sco.items[1].qty = 25
		sco.save()
		sco.submit()

		# Test - 1: Quantity of Service Items should change based on change in Quantity of its corresponding Finished Goods Item
		self.assertEqual(sco.service_items[0].qty, 5)
		
		# Test - 2: Subcontracted Quantity for the PO Items of each line item should be updated accordingly
		po.reload()
		self.assertEqual(po.items[0].sco_qty, 5)
		self.assertEqual(po.items[1].sco_qty, 0)
		self.assertEqual(po.items[2].sco_qty, 12.5)
		
		# Test - 3: Amount for both FG Item and its Service Item should be updated correctly based on change in Quantity
		self.assertEqual(sco.items[0].amount, 2000)
		self.assertEqual(sco.service_items[0].amount, 500)
		
		# Test - 4: Service Items should be removed if its corresponding Finished Good line item is deleted
		self.assertEqual(len(sco.service_items), 2)
		
		# Test - 5: Service Item quantity calculation should be based upon conversion factor calculated from its corresponding PO Item
		self.assertEqual(sco.service_items[1].qty, 12.5)
		
		sco = make_subcontracting_order(po.name)
		
		sco.items[0].qty = 6
		
		# Test - 6: Saving document should not be allowed if Quantity exceeds available Subcontracting Quantity of any Purchase Order Item
		self.assertRaises(frappe.ValidationError, sco.save)
		
		sco.items[0].qty = 5
		sco.items.pop()
		sco.items.pop()
		sco.save()
		sco.submit()
		
		sco = make_subcontracting_order(po.name)
		
		# Test - 7: Since line item 1 is now fully subcontracted, new SCO should by default only have the remaining 2 line items
		self.assertEqual(len(sco.items), 2)
		
		sco.items.pop(0)
		sco.save()
		sco.submit()
		
		# Test - 8: Subcontracted Quantity for each PO Item should be subtracted if SCO gets cancelled
		po.reload()
		self.assertEqual(po.items[2].sco_qty, 25)
		sco.cancel()
		po.reload()
		self.assertEqual(po.items[2].sco_qty, 12.5)
		
		sco = make_subcontracting_order(po.name)
		sco.save()
		sco.submit()
		
		# Test - 8: Since this PO is now fully subcontracted, creating a new SCO from it should throw error
		self.assertRaises(frappe.ValidationError, make_subcontracting_order, po.name)

	@change_settings("Buying Settings", {"auto_create_subcontracting_order": 1})
	def test_auto_create_subcontracting_order(self):
		from erpnext.controllers.tests.test_subcontracting_controller import (
			make_bom_for_subcontracted_items,
			make_raw_materials,
			make_service_items,
			make_subcontracted_items,
		)

		make_subcontracted_items()
		make_raw_materials()
		make_service_items()
		make_bom_for_subcontracted_items()

		service_items = [
			{
				"warehouse": "_Test Warehouse - _TC",
				"item_code": "Subcontracted Service Item 7",
				"qty": 10,
				"rate": 100,
				"fg_item": "Subcontracted Item SA7",
				"fg_item_qty": 10,
			},
		]
		po = create_purchase_order(
			rm_items=service_items,
			is_subcontracted=1,
			supplier_warehouse="_Test Warehouse 1 - _TC",
		)

		self.assertTrue(frappe.db.get_value("Subcontracting Order", {"purchase_order": po.name}))

	def test_po_billed_amount_against_return_entry(self):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		# Create a Purchase Order and Fully Bill it
		po = create_purchase_order()
		pi = make_pi_from_po(po.name)
		pi.insert()
		pi.submit()

		# Debit Note - 50% Qty & enable updating PO billed amount
		pi_return = make_debit_note(pi.name)
		pi_return.items[0].qty = -5
		pi_return.update_billed_amount_in_purchase_order = 1
		pi_return.submit()

		# Check if the billed amount reduced
		po.reload()
		self.assertEqual(po.per_billed, 50)

		pi_return.reload()
		pi_return.cancel()

		# Debit Note - 50% Qty & disable updating PO billed amount
		pi_return = make_debit_note(pi.name)
		pi_return.items[0].qty = -5
		pi_return.update_billed_amount_in_purchase_order = 0
		pi_return.submit()

		# Check if the billed amount stayed the same
		po.reload()
		self.assertEqual(po.per_billed, 100)

	def test_create_purchase_receipt(self):
		po = create_purchase_order(rate=10000,qty=10)
		po.submit()

		pr = create_pr_against_po(po.name, received_qty=10)
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, po.get("items")[0].warehouse)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 100000)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 100000)
	
	def test_single_po_pi_TC_B_001(self):
		# Scenario : PO => PR => 1PI
		args = frappe._dict()
		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 6,
			"rate" : 100,
		}
		
		doc_po = create_purchase_order(**po_data)
		self.assertEqual(doc_po.docstatus, 1)
		
		doc_pr = make_pr_for_po(doc_po.name)
		self.assertEqual(doc_pr.docstatus, 1)

		doc_pi = make_pi_against_pr(doc_pr.name)
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.items[0].qty, doc_po.items[0].qty)
		self.assertEqual(doc_pi.grand_total, doc_po.grand_total)
	
	def test_multi_po_pr_TC_B_008(self):
		# Scenario : 2PO => 2PR => 1PI
		args = frappe._dict()
		purchase_order_list = [{
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 3,
			"rate" : 100,
		},
		{
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 3,
			"rate" : 100,
		}]

		pur_receipt_name_list = []
		pur_order_dict = frappe._dict({
			"total_amount" : 0,
			"total_qty" : 0
		})

		for order in purchase_order_list:
			doc_po = create_purchase_order(**order)
			pur_order_dict.update({"total_amount" : pur_order_dict.total_amount + doc_po.grand_total })
			pur_order_dict.update({"total_qty" : pur_order_dict.total_qty + doc_po.total_qty })
			
			self.assertEqual(doc_po.docstatus, 1)

			doc_pr = make_pr_for_po(doc_po.name)
			self.assertEqual(doc_pr.docstatus, 1)
			self.assertEqual(doc_pr.grand_total, doc_po.grand_total)

			pur_receipt_name_list.append(doc_pr.name)

		item_dict = [
					{"item_code" : "_Test Item",
					"warehouse" : "Stores - _TC",
					"qty" : 3,
					"rate" : 100,
					"purchase_receipt":pur_receipt_name_list[1]
					}]
		
		doc_pi = make_pi_against_pr(pur_receipt_name_list[0], item_dict_list = item_dict)
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.total_qty, pur_order_dict.total_qty)
		self.assertEqual(doc_pi.grand_total, pur_order_dict.total_amount)

	def test_multi_po_single_pr_pi_TC_B_007(self):
		# Scenario : 2PO => 1PR => 1PI
		args = frappe._dict()
		purchase_order_list = [{
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 3,
			"rate" : 100,
		},
		{
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 3,
			"rate" : 100,
		}]

		pur_order_name_list = []
		pur_order_dict = frappe._dict({
			"total_amount" : 0,
			"total_qty" : 0
		})

		for order in purchase_order_list:
			doc_po = create_purchase_order(**order)
			pur_order_dict.update({"total_amount" : pur_order_dict.total_amount + doc_po.grand_total })
			pur_order_dict.update({"total_qty" : pur_order_dict.total_qty + doc_po.total_qty })
			
			self.assertEqual(doc_po.docstatus, 1)
			pur_order_name_list.append(doc_po.name)

		item_dict = [
					{"item_code" : "_Test Item",
					"warehouse" : "Stores - _TC",
					"qty" : 3,
					"rate" : 100,
					"purchase_receipt":pur_order_name_list[1]
					}]

		doc_pr = make_pr_for_po(pur_order_name_list[0], item_dict_list = item_dict)

		doc_pi = make_pi_against_pr(doc_pr.name)
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.total_qty, pur_order_dict.total_qty)
		self.assertEqual(doc_pi.grand_total, pur_order_dict.total_amount)
	
	def test_single_po_multi_pr_pi_TC_B_006(self):
		# Scenario : 1PO => 2PR => 2PI
		
		purchase_order_list = [{
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 6,
			"rate" : 100,
		}]

		pur_invoice_dict = frappe._dict({
			"total_amount" : 0,
			"total_qty" : 0
		})
		pur_receipt_qty = [3, 3]
		doc_po = create_purchase_order(**purchase_order_list[0])
		self.assertEqual(doc_po.docstatus, 1)

		for received_qty in pur_receipt_qty:
			doc_pr = make_pr_for_po(doc_po.name, received_qty)
			self.assertEqual(doc_pr.docstatus, 1)
			
			doc_pi = make_pi_against_pr(doc_pr.name)
			self.assertEqual(doc_pi.docstatus, 1)

			pur_invoice_dict.update({"total_amount" : pur_invoice_dict.total_amount + doc_pi.grand_total })
			pur_invoice_dict.update({"total_qty" : pur_invoice_dict.total_qty + doc_pi.total_qty })
		
		self.assertEqual(doc_po.total_qty, pur_invoice_dict.total_qty)
		self.assertEqual(doc_po.grand_total, pur_invoice_dict.total_amount)
	
	def test_single_po_pi_multi_pr_TC_B_005(self):
		# Scenario : 1PO => 2PR => 1PI
		
		purchase_order_list = [{
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 6,
			"rate" : 100,
		}]

		pur_receipt_qty = [3, 3]
		pur_receipt_name_list = []

		doc_po = create_purchase_order(**purchase_order_list[0])
		self.assertEqual(doc_po.docstatus, 1)

		for received_qty in pur_receipt_qty:
			doc_pr = make_pr_for_po(doc_po.name, received_qty)
			self.assertEqual(doc_pr.docstatus, 1)
			
			pur_receipt_name_list.append(doc_pr.name)
		
		item_dict = [
					{"item_code" : "_Test Item",
					"warehouse" : "Stores - _TC",
					"qty" : 3,
					"rate" : 100,
					"purchase_receipt":pur_receipt_name_list[1]
					}]
		
		doc_pi = make_pi_against_pr(pur_receipt_name_list[0], item_dict_list= item_dict)
		
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_po.total_qty, doc_pi.total_qty)
		self.assertEqual(doc_po.grand_total, doc_pi.grand_total)
	
	def test_create_purchase_receipt_partial_TC_SCK_037(self):
		po = create_purchase_order(rate=10000,qty=10)
		po.submit()

		pr = create_pr_against_po(po.name, received_qty=5)
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, po.get("items")[0].warehouse)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 50000)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 50000)

	def test_pi_return_TC_B_043(self):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note
		from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import check_gl_entries
		from erpnext.stock.doctype.stock_entry.test_stock_entry import get_qty_after_transaction

		po = create_purchase_order(		
			warehouse="Finished Goods - _TC",
			rate=130,
			qty=1,
		)
		self.assertEqual(po.status, "To Receive and Bill")
		actual_qty_0 = get_qty_after_transaction(warehouse="Finished Goods - _TC")

		pi = make_pi_from_po(po.name)
		pi.update_stock = 1
		pi.save()
		pi.submit()
		pi.load_from_db()
		self.assertEqual(pi.status, "Unpaid")
		expected_gle = [
			["Creditors - _TC", 0.0, 130, nowdate()],
			["_Test Account Cost for Goods Sold - _TC", 130, 0.0, nowdate()],
		]
		check_gl_entries(self, pi.name, expected_gle, nowdate())
		actual_qty_1 = get_qty_after_transaction(warehouse="Finished Goods - _TC")
		self.assertEqual(actual_qty_0 + 1, actual_qty_1)

		po_status = frappe.db.get_value("Purchase Order", po.name, "status")
		self.assertEqual(po_status, "Completed")

		pi_return = make_debit_note(pi.name)
		pi_return.update_outstanding_for_self = 0
		pi_return.update_billed_amount_in_purchase_receipt = 0
		pi_return.save()
		pi_return.submit()
		pi_return.load_from_db()
		self.assertEqual(pi_return.status, "Return")
		expected_gle = [
			["Creditors - _TC", 130, 0.0, nowdate()],
			["_Test Account Cost for Goods Sold - _TC", 0.0, 130, nowdate()],
		]
		check_gl_entries(self, pi_return.name, expected_gle, nowdate())
		actual_qty_2 = get_qty_after_transaction(warehouse="Finished Goods - _TC")
		self.assertEqual(actual_qty_1 - 1, actual_qty_2)

		pi_status = frappe.db.get_value("Purchase Invoice", pi.name, "status")
		self.assertEqual(pi_status, "Debit Note Issued")

	def test_payment_entry_TC_B_037(self):
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry
		from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import check_gl_entries

		po = create_purchase_order(		
			warehouse="Finished Goods - _TC",
			rate=30,
			qty=1,
		)

		self.assertEqual(po.status, "To Receive and Bill")
		pi = make_pi_from_po(po.name)
		pi.update_stock = 1
		pi.save()
		pi.submit()
		pi.load_from_db()

		expected_gle = [
			["Creditors - _TC", 0.0, 30, nowdate()],
			["_Test Account Cost for Goods Sold - _TC", 30, 0.0, nowdate()],
		]
		check_gl_entries(self, pi.name, expected_gle, nowdate())

		pe = get_payment_entry("Purchase Invoice", pi.name)
		pe.save()
		pe.submit()
		pi_status = frappe.db.get_value("Purchase Invoice", pi.name, "status")
		self.assertEqual(pi_status, "Paid")
		expected_gle = [
			{"account": "Creditors - _TC", "debit": 30.0, "credit": 0.0},
			{"account": "Cash - _TC", "debit": 0.0, "credit": 30.0},
		]
		check_payment_gl_entries(self, pe.name, expected_gle)

	def test_purchase_invoice_cancellation_TC_B_041(self):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

		po = create_purchase_order(		
			warehouse="Finished Goods - _TC",
			rate=130,
			qty=1,
		)
		self.assertEqual(po.status, "To Receive and Bill")

		pr = make_purchase_receipt(po.name)
		pr.save()
		pr.submit()
		self.assertEqual(pr.status, "To Bill")
		po_status = frappe.db.get_value("Purchase Order", po.name, "status")
		self.assertEqual(po_status, "To Bill")

		pi = make_purchase_invoice(pr.name)
		pi.save()
		pi.submit()
		self.assertEqual(pi.status, "Unpaid")
		po_status = frappe.db.get_value("Purchase Order", po.name, "status")
		self.assertEqual(po_status, "Completed")
		pr_status = frappe.db.get_value("Purchase Receipt", pr.name, "status")
		self.assertEqual(pr_status, "Completed")
		
		pi.cancel()
		self.assertEqual(pi.status, "Cancelled")
		po_status = frappe.db.get_value("Purchase Order", po.name, "status")
		self.assertEqual(po_status, "To Bill")
		pr_status = frappe.db.get_value("Purchase Receipt", pr.name, "status")
		self.assertEqual(pr_status, "To Bill")
	def test_purchase_invoice_return_TC_B_042(self):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		po = create_purchase_order(		
			warehouse="Finished Goods - _TC",
			rate=130,
			qty=1,
		)
		pr = make_purchase_receipt(po.name)
		pr.save()
		pr.submit()

		pi = make_purchase_invoice(pr.name)
		pi.save()
		pi.submit()
		
		pi_return = make_debit_note(pi.name)
		pi_return.update_outstanding_for_self = 0
		pi_return.update_billed_amount_in_purchase_receipt = 0
		pi_return.save()
		pi_return.submit()
		self.assertEqual(pi_return.status, "Return")
		pi_status = frappe.db.get_value("Purchase Invoice", pi.name, "status")
		self.assertEqual(pi_status, "Debit Note Issued")  

	def test_50_50_payment_terms_TC_B_045(self):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry

		po = create_purchase_order(		
			warehouse="Finished Goods - _TC",
			rate=130,
			qty=1,
			do_not_save=1
		)
		po.payment_terms_template = "_Test Payment Term Template"
		po.save()
		po.submit()

		pe = get_payment_entry("Purchase Order", po.name, party_amount=po.grand_total/2)
		pe.save()
		pe.submit()
	
		po_advance_paid = frappe.db.get_value("Purchase Order", po.name, "advance_paid")
		self.assertTrue(po_advance_paid, po.grand_total/2)

		pr = make_purchase_receipt(po.name)
		pr.save()
		pr.submit()
		self.assertTrue(pr.status, "To Bill")

		pi = make_purchase_invoice(pr.name)
		pi.set_advances()
		pi.save()
		pi.submit()
		
		pe = get_payment_entry("Purchase Invoice", pi.name, party_amount=po.grand_total/2)
		pe.save()
		pe.submit()
		po_status = frappe.db.get_value("Purchase Order", po.name, "status")
		self.assertEqual(po_status, "Completed")

		pi_status = frappe.db.get_value("Purchase Invoice", pi.name, "status")
		self.assertEqual(pi_status, "Paid")

		frappe.db.commit()


	def test_status_po_on_pi_cancel_TC_B_038(self):
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_payment_entry
		from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import payment_reconciliation_record_on_unreconcile,create_unreconcile_doc_for_selection

		po = create_purchase_order()
		
		pi = make_pi_from_po(po.name)
		pi.update_stock = 1
		pi.insert()
		pi.submit()

		pe = create_payment_entry(
			company=f"{pi.company}",
			payment_type="Pay",
			party_type="Supplier",
			party=f"{pi.supplier}",
			paid_from="Cash - _TC",
			paid_to="Creditors - _TC",
			paid_amount=pi.grand_total,
		)
		
		pe.append('references',{
			"reference_doctype": "Purchase Invoice",
			"reference_name": pi.name,
			"allocated_amount":pi.grand_total
		})
		pe.save()
		pe.submit()

		before_pi_cancel_status = frappe.db.get_value("Purchase Order", po.name, "status")
		self.assertEqual(before_pi_cancel_status, "Completed")
		
		header = {
			"company":"_Test Company",
			"unreconcile":1,
			"clearing_date":"2025-01-07",
			"party_type":"Supplier",
			"party":"_Test Supplier"
		}
		selection = {"company":"_Test Company","voucher_type":"Payment Entry","voucher_no":f"{pe.name}","against_voucher_type":"Purchase Invoice","against_voucher_no":f"{pi.name}","allocated_amount":pi.rounded_total}
		allocation = [{"reference_type":"Payment Entry","reference_name":pe.name,"invoice_type":"Purchase Invoice","invoice_number":pi.name,"allocated_amount":pi.rounded_total}]
		payment_reconciliation_record_on_unreconcile(header=header,allocation=allocation)
		create_unreconcile_doc_for_selection(selections = json.dumps([selection]))
		
		pi.reload()
		pi.cancel()
		after_pi_cancel_status = frappe.db.get_value("Purchase Order", po.name, "status")
		self.assertEqual(after_pi_cancel_status, "To Receive and Bill")


	def test_full_payment_request_TC_B_030(self):
		# Scenario : PO => Payment Request
		
		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 6,
			"rate" : 100,
		}
		
		doc_po = create_purchase_order(**po_data)
		self.assertEqual(doc_po.docstatus, 1)
		
		args = frappe._dict()
		args = {
				"dt": doc_po.doctype,
				"dn": doc_po.name,
				"recipient_id": doc_po.contact_email,
				"payment_request_type": 'Outward',
				"party_type":  "Supplier",
				"party":  doc_po.supplier,
				"party_name": doc_po.supplier_name
			}
		dict_pr = make_payment_request(**args)
		doc_pr = frappe.get_doc("Payment Request", dict_pr.name)
		doc_pr.submit()
		self.assertEqual(doc_pr.docstatus, 1)
		self.assertEqual(doc_pr.reference_name, doc_po.name)
		self.assertEqual(doc_pr.grand_total, doc_po.grand_total)
	def test_po_to_partial_pr_TC_B_031(self):
		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": "_Test Supplier 1",
			"company": "_Test Company",
			"schedule_date": frappe.utils.nowdate(),
			"items": [
				{
					"item_code": "Testing-31",
					"qty": 6,
					"rate": 100,
					"warehouse": "Stores - _TC",
				}
			]
		})
		po.insert()
		po.submit()

		payment_request = frappe.get_doc({
			"doctype": "Payment Request",
			"reference_doctype": "Purchase Order",
			"reference_name": po.name,
			"payment_request_type": "Outward",
			"party_type": "Supplier",
			"party": po.supplier,
			"grand_total": 300,
		})

		payment_request.insert()
		payment_request.submit()

		self.assertEqual(payment_request.payment_request_type, "Outward")
		self.assertEqual(payment_request.grand_total, 300)
		self.assertEqual(payment_request.reference_name, po.name)
	
	def test_purchase_invoice_return_TC_B_032(self):
		company = "_Test Company"
		item_code = "Testing-31"
		target_warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		qty = 6
		rate = 100
		amount = qty * rate

		purchase_invoice = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier,
			"items": [
				{
					"item_code": item_code,
					"warehouse": target_warehouse,
					"qty": qty,
					"rate": rate,
					"amount": amount,
				}
			],
			"update_stock": 1,
		})
		purchase_invoice.insert()
		purchase_invoice.submit()
		frappe.db.commit()

		purchase_invoice_return = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier,
			"is_return": 1,
			"return_against": purchase_invoice.name,
			"items": [
				{
					"item_code": item_code,
					"warehouse": target_warehouse,
					"qty": -qty,
					"rate": rate,
					"amount": amount,
				}
			],
			"update_stock": 1,
		})
		purchase_invoice_return.insert()
		purchase_invoice_return.submit()
		frappe.db.commit()

		gl_entries = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Purchase Invoice",
				"voucher_no": purchase_invoice_return.name,
				"company": company,
			},
			fields=["account", "debit", "credit"],
		)

		reversal_passed = False
		for entry in gl_entries:
			if "Stock In Hand" in entry["account"]:
				self.assertEqual(entry["credit"], amount)
				reversal_passed = True
			elif "Creditors" in entry["account"]:
				self.assertEqual(entry["debit"], amount)
				reversal_passed = True

		stock_ledger_entries = frappe.get_all(
			"Stock Ledger Entry",
			filters={
				"voucher_type": "Purchase Invoice",
				"voucher_no": purchase_invoice_return.name,
				"warehouse": target_warehouse,
			},
			fields=["actual_qty"],
		)

		stock_decrease_passed = False
		for entry in stock_ledger_entries:
			if entry["actual_qty"] == -qty:
				stock_decrease_passed = True

		self.assertTrue(reversal_passed)
		self.assertTrue(stock_decrease_passed)

	def test_partial_purchase_invoice_return_TC_B_033(self):
		company = "_Test Company"
		item_code = "Testing-31"
		target_warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		original_qty = 6
		return_qty = 3
		rate = 100
		amount = original_qty * rate
		return_amount = return_qty * rate

		purchase_invoice = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier,
			"items": [
				{
					"item_code": item_code,
					"warehouse": target_warehouse,
					"qty": original_qty,
					"rate": rate,
					"amount": amount,
				}
			],
			"update_stock": 1,
		})
		purchase_invoice.insert()
		purchase_invoice.submit()
		frappe.db.commit()

		purchase_invoice_return = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier,
			"is_return": 1,
			"return_against": purchase_invoice.name,
			"items": [
				{
					"item_code": item_code,
					"warehouse": target_warehouse,
					"qty": -return_qty,
					"rate": rate,
					"amount": return_amount,
				}
			],
			"update_stock": 1,
		})
		purchase_invoice_return.insert()
		purchase_invoice_return.submit()

		gl_entries = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Purchase Invoice",
				"voucher_no": purchase_invoice_return.name,
				"company": company,
			},
			fields=["account", "debit", "credit"],
		)

		reversal_passed = False
		for entry in gl_entries:
			if "Stock In Hand" in entry["account"]:
				self.assertEqual(entry["credit"], return_amount)
				reversal_passed = True
			elif "Creditors" in entry["account"]:
				self.assertEqual(entry["debit"], return_amount)
				reversal_passed = True

		stock_ledger_entries = frappe.get_all(
			"Stock Ledger Entry",
			filters={
				"voucher_type": "Purchase Invoice",
				"voucher_no": purchase_invoice_return.name,
				"warehouse": target_warehouse,
			},
			fields=["actual_qty"],
		)

		stock_decrease_passed = False
		for entry in stock_ledger_entries:
			if entry["actual_qty"] == -return_qty:
				stock_decrease_passed = True

		# Assertions
		self.assertTrue(reversal_passed)
		self.assertTrue(stock_decrease_passed)

	def test_pr_to_lcv_add_value_to_stock_TC_B_034(self):
		frappe.db.set_value("Company", "_Test Company", {"enable_perpetual_inventory":1, "stock_received_but_not_billed": "_Test Account Excise Duty - _TC"})
		frappe.db.commit()

		# Step 1: Create Purchase Receipt
		doc_pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"company": "_Test Company",
			"supplier": "_Test Supplier",
			"items": [
				{
					"item_code": "Testing-31",
					"warehouse": "Stores - _TC",
					"qty": 10,
					"rate": 100,
				}
			]
		})
		doc_pr.insert()
		doc_pr.submit()
		self.assertEqual(doc_pr.docstatus, 1)

		doc_lcv = frappe.get_doc({
			"doctype": "Landed Cost Voucher",
			"company": "_Test Company",
			"purchase_receipts": [
				{
					"receipt_document_type": "Purchase Receipt",
					"receipt_document": doc_pr.name,
					"supplier": doc_pr.supplier,
					"grand_total": doc_pr.grand_total
				}
			],
			"taxes": [
				{
					"expense_account": "_Test Account Education Cess - _TC",
					"amount": 500,
					"description": "test_description"
				}
			]
		})
		doc_lcv.insert()
		doc_lcv.submit()
		self.assertEqual(doc_lcv.docstatus, 1)

		# Validate Stock Ledger Entries
		stock_ledger_entries = frappe.get_all(
			"Stock Ledger Entry",
			filters={
				"voucher_no": doc_pr.name,
				"warehouse": "Stores - _TC",
				"item_code": "Testing-31"
			},
			fields=["valuation_rate"],
			order_by="creation desc"
		)
		self.assertGreater(len(stock_ledger_entries), 0)

		updated_valuation_rate = stock_ledger_entries[0]["valuation_rate"]
		self.assertGreater(updated_valuation_rate, 100)

		# Validate GL Entries
		gl_entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": doc_pr.name},
			fields=["account", "debit", "credit"]
		)
		self.assertGreater(len(gl_entries), 0)

	def test_po_and_pi_with_pricing_rule_with_TC_B_048(self):
		company = "_Test Company"
		item_code = "Testing-31"
		target_warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_price = 130

		if not frappe.db.exists("Item", item_code):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"is_stock_item": 1,
				"is_purchase_item": 1,
				"is_sales_item": 0,
				"company": company
			}).insert()

		item_price_doc = frappe.get_doc({
			"doctype": "Item Price",
			"price_list": "Standard Buying",
			"item_code": item_code,
			"price_list_rate": item_price
		}).insert()

		pricing_rule = frappe.get_doc({
			"doctype": "Pricing Rule",
			"title": "10% Discount",
			"company": company,
			"apply_on": "Item Code",
			"items":[
				{
					"item_code":item_code
				}
			],
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 10,
			"selling": 0,
			"buying": 1
		}).insert()

		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": supplier,
			"company": company,
			"schedule_date":today(),
			"set_warehouse": target_warehouse,
			"items": [
				{
					"item_code": item_code,
					"warehouse": target_warehouse,
					"qty": 1
				}
			]
		})
		po.insert()
		po.submit()

		self.assertEqual(len(po.items), 1)
		self.assertEqual(po.items[0].rate, 117)
		self.assertEqual(po.items[0].discount_percentage, 10)

		pi = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"supplier": supplier,
			"company": company,
			"items": [
				{
					"item_code": item_code,
					"purchase_order": po.name,
					"warehouse": target_warehouse,
					"qty": po.items[0].qty
				}
			]
		})
		pi.insert()
		pi.submit()

		self.assertEqual(len(pi.items), 1)
		self.assertEqual(pi.items[0].rate, 117)
		self.assertEqual(pi.items[0].discount_percentage, 10)
	def test_po_to_pr_with_gst_partly_paid_TC_B_085(self):
		# Scenario : PO => PR with GST Partly Paid

		purchase_tax = frappe.new_doc("Purchase Taxes and Charges Template")
		purchase_tax.title = "TEST"
		purchase_tax.company = "_Test Company"
		purchase_tax.tax_category = "_Test Tax Category 1"

		purchase_tax.append("taxes",{
			"category":"Total",
			"add_deduct_tax":"Add",
			"charge_type":"On Net Total",
			"account_head":"_Test Account Excise Duty - _TC",
			"_Test Account Excise Duty":"_Test Account Excise Duty",
			"rate":100,
			"description":"GST"
		})
		purchase_tax.save()
		po = create_purchase_order(do_not_submit=True)
		po.taxes_and_charges = purchase_tax.name
		po.save()
		po.submit()
		self.assertEqual(po.docstatus,1)

		args = {
				"dt": po.doctype,
				"dn": po.name,
				"payment_request_type": 'Outward',
				"party_type":  "Supplier",
				"party":  po.supplier,
				"party_name": po.supplier_name
			}
		partly_pr = make_payment_request(**args)
		doc_pr = frappe.get_doc("Payment Request", partly_pr.name)
		# set half amount to be paid
		doc_pr.grand_total = po.grand_total / 2
		doc_pr.submit()
		po_status = frappe.db.get_value("Purchase Order",po.name,'status')
		self.assertEqual(po_status,'To Receive and Bill')
	
	def test_po_to_pr_with_gst_fully_paid_TC_B_086(self):
		# Scenario : PO => PR with GST Fully Paid

		purchase_tax = frappe.new_doc("Purchase Taxes and Charges Template")
		purchase_tax.title = "TEST"
		purchase_tax.company = "_Test Company"
		purchase_tax.tax_category = "_Test Tax Category 1"

		purchase_tax.append("taxes",{
			"category":"Total",
			"add_deduct_tax":"Add",
			"charge_type":"On Net Total",
			"account_head":"_Test Account Excise Duty - _TC",
			"_Test Account Excise Duty":"_Test Account Excise Duty",
			"rate":100,
			"description":"GST"
		})
		purchase_tax.save()
		po = create_purchase_order(do_not_submit=True)
		po.taxes_and_charges = purchase_tax.name
		po.save()
		po.submit()
		self.assertEqual(po.docstatus,1)

		args = {
				"dt": po.doctype,
				"dn": po.name,
				"payment_request_type": 'Outward',
				"party_type":  "Supplier",
				"party":  po.supplier,
				"party_name": po.supplier_name
			}
		partly_pr = make_payment_request(**args)
		doc_pr = frappe.get_doc("Payment Request", partly_pr.name)
		doc_pr.grand_total = po.grand_total 
		doc_pr.submit()
		po_status = frappe.db.get_value("Purchase Order",po.name,'status')
		self.assertEqual(po_status,'To Receive and Bill')
	
	def test_po_to_pr_to_pi_fully_paid_TC_B_087(self):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

		purchase_tax = frappe.new_doc("Purchase Taxes and Charges Template")
		purchase_tax.title = "TEST"
		purchase_tax.company = "_Test Company"
		purchase_tax.tax_category = "_Test Tax Category 1"

		purchase_tax.append("taxes",{
			"category":"Total",
			"add_deduct_tax":"Add",
			"charge_type":"On Net Total",
			"account_head":"_Test Account Excise Duty - _TC",
			"_Test Account Excise Duty":"_Test Account Excise Duty",
			"rate":100,
			"description":"GST"
		})

		purchase_tax.save()

		po = create_purchase_order(do_not_save=True)
		po.taxes_and_charges = purchase_tax.name
		po.save()
		po.submit()
		po_status_before = frappe.db.get_value("Purchase Order",po.name,'status')
		self.assertEqual(po_status_before,'To Receive and Bill')

		pr = make_purchase_receipt(po.name)
		pr.save()
		pr.submit()

		po_status_after_pr = frappe.db.get_value("Purchase Order",po.name,'status')
		self.assertEqual(po_status_after_pr,'To Bill')

		pi = make_purchase_invoice(pr.name)
		pi.is_paid = 1
		pi.mode_of_payment = "Cash"
		pi.cash_bank_account = "Cash - _TC"
		pi.paid_amount = pr.grand_total
		pi.save()
		pi.submit()

		pi_status = frappe.db.get_value("Purchase Invoice",pi.name,'status')
		self.assertEqual(pi_status,'Paid')

		po_status_after_paid =  frappe.db.get_value("Purchase Order",po.name,'status')
		self.assertEqual(po_status_after_paid,'Completed')
	
	def test_po_to_pr_to_pi_partly_paid_TC_B_089(self):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
		purchase_tax = frappe.new_doc("Purchase Taxes and Charges Template")
		purchase_tax.title = "TEST"
		purchase_tax.company = "_Test Company"
		purchase_tax.tax_category = "_Test Tax Category 1"

		purchase_tax.append("taxes",{
			"category":"Total",
			"add_deduct_tax":"Add",
			"charge_type":"On Net Total",
			"account_head":"_Test Account Excise Duty - _TC",
			"_Test Account Excise Duty":"_Test Account Excise Duty",
			"rate":100,
			"description":"GST"
		})

		purchase_tax.save()

		po = create_purchase_order(do_not_save=True)
		po.taxes_and_charges = purchase_tax.name
		po.save()
		po.submit()
		po_status_before = frappe.db.get_value("Purchase Order",po.name,'status')
		self.assertEqual(po_status_before,'To Receive and Bill')

		pr = make_purchase_receipt(po.name)
		pr.save()
		pr.submit()

		po_status_after_pr = frappe.db.get_value("Purchase Order",po.name,'status')
		self.assertEqual(po_status_after_pr,'To Bill')

		pi = make_purchase_invoice(pr.name)
		pi.is_paid = 1
		pi.mode_of_payment = "Cash"
		pi.cash_bank_account = "Cash - _TC"
		pi.paid_amount = pr.grand_total / 2
		pi.save()
		pi.submit()

		pi_status = frappe.db.get_value("Purchase Invoice",pi.name,'status')
		self.assertEqual(pi_status,'Partly Paid')

		po_status_after_paid =  frappe.db.get_value("Purchase Order",po.name,'status')
		self.assertEqual(po_status_after_paid,'Completed')

	def test_po_return_TC_B_043(self):
		# Scenario : PO => PR => PI => PI(Return)
		args = frappe._dict()
		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 6,
			"rate" : 100,
		}

		doc_po = create_purchase_order(**po_data)
		self.assertEqual(doc_po.docstatus, 1)

		doc_pr = make_pr_for_po(doc_po.name)
		self.assertEqual(doc_pr.docstatus, 1)

		doc_pi = make_pi_against_pr(doc_pr.name)
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.items[0].qty, doc_po.items[0].qty)
		self.assertEqual(doc_pi.grand_total, doc_po.grand_total)

		doc_returned_pi = make_return_pi(doc_pi.name)
		self.assertEqual(doc_returned_pi.total_qty, -doc_po.total_qty)
		doc_pi.reload()
		self.assertEqual(doc_pi.status, 'Debit Note Issued')
		self.assertEqual(doc_returned_pi.status, 'Return')

	def test_po_full_payment_TC_B_045(self):
		# Scenario : PO => Payment Entry => PR => PI => PI(Return)

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"qty" : 6,
			"rate" : 100,
		}

		doc_po = create_purchase_order(**po_data)
		self.assertEqual(doc_po.docstatus, 1)

		doc_pe = get_payment_entry("Purchase Order", doc_po.name, doc_po.grand_total)
		doc_pe.insert()
		doc_pe.submit()
		# doc_pe.paid_from = "Cash"

		doc_pr = make_pr_for_po(doc_po.name)
		self.assertEqual(doc_pr.docstatus, 1)

		doc_pi = make_pi_against_pr(doc_pr.name, args={"is_paid" : 1, "cash_bank_account" : doc_pe.paid_from})
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.items[0].qty, doc_po.items[0].qty)
		self.assertEqual(doc_pi.grand_total, doc_po.grand_total)

		doc_pi.reload()
		doc_po.reload()
		self.assertEqual(doc_pi.status, 'Paid')
		self.assertEqual(doc_po.status, 'Completed')

	def test_po_with_pricing_rule_TC_B_046(self):
		# Scenario : PO => Pricing Rule => PR => PI

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"supplier": "_Test Supplier",
            "schedule_date": "2025-01-13",
			"qty" : 1,
		}

		pricing_rule_record = {
			"doctype": "Pricing Rule",
			"title": "Discount on _Test Item",
			"apply_on": "Item Code",
			"items": [
				{
					"item_code": "_Test Item",
				}
				],
			"price_or_product_discount": "Price",
			"applicable_for": "Supplier",
			"supplier": "_Test Supplier",
			"buying": 1,
			"currency": "INR",

			"min_qty": 1,
			"min_amt": 100,
			"valid_from": "2025-01-01",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 10,
			"price_list": "Standard Buying",
			"company" : "_Test Company",

		}
		rule = frappe.get_doc(pricing_rule_record)
		rule.insert()

		frappe.get_doc(
			{
				"doctype": "Item Price",
				"price_list": "Standard Buying",
				"item_code": "_Test Item",
				"price_list_rate": 130,
			}
		).insert()

		doc_po = create_purchase_order(**po_data)
		doc_po_item = doc_po.items[0]
		self.assertEqual(doc_po_item.discount_percentage, 10)
		self.assertEqual(doc_po_item.rate, 117)  
		self.assertEqual(doc_po_item.amount, 117)

		doc_pr = make_pr_for_po(doc_po.name)

		doc_pi = make_pi_against_pr(doc_pr.name)
		pi_item = doc_pi.items[0]
		self.assertEqual(pi_item.rate, 117)
		self.assertEqual(pi_item.amount, 117)

	def test_po_with_pricing_rule_TC_B_047(self):
		# Scenario : PO => Pricing Rule => PR 

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"supplier": "_Test Supplier",
            "schedule_date": "2025-01-13",
			"qty" : 1,
		}

		pricing_rule_record = {
			"doctype": "Pricing Rule",
			"title": "Discount on _Test Item",
			"apply_on": "Item Code",
			"items": [
				{
					"item_code": "_Test Item",
				}
				],
			"price_or_product_discount": "Price",
			"applicable_for": "Supplier",
			"supplier": "_Test Supplier",
			"buying": 1,
			"currency": "INR",

			"min_qty": 1,
			"min_amt": 100,
			"valid_from": "2025-01-01",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 10,
			"price_list": "Standard Buying",
			"company" : "_Test Company",

		}
		rule = frappe.get_doc(pricing_rule_record)
		rule.insert()

		frappe.get_doc(
			{
				"doctype": "Item Price",
				"price_list": "Standard Buying",
				"item_code": "_Test Item",
				"price_list_rate": 130,
			}
		).insert()

		doc_po = create_purchase_order(**po_data)
		po_item = doc_po.items[0]
		self.assertEqual(po_item.discount_percentage, 10)
		self.assertEqual(po_item.rate, 117)
		self.assertEqual(po_item.amount, 117)


		doc_pr = make_pr_for_po(doc_po.name)
		pr_item = doc_pr.items[0]
		self.assertEqual(pr_item.rate, 117) 
		self.assertEqual(pr_item.amount, 117)

	def test_po_additional_discount_TC_B_052(self):
		# Scenario : PO => PR => PI [With Additional Discount]

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"supplier": "_Test Supplier",
            "schedule_date": "2025-01-13",
			"qty" : 1,
			"rate" : 10000,
			"apply_discount_on" : "Net Total",
			"additional_discount_percentage" :10 ,
			"do_not_submit":1
		}

		acc = frappe.new_doc("Account")
		acc.account_name = "Input Tax IGST"
		acc.parent_account = "Tax Assets - _TC"
		acc.company = "_Test Company"
		account_name = frappe.db.exists("Account", {"account_name" : "Input Tax IGST","company": "_Test Company" })
		if not account_name:
			account_name = acc.insert()

		doc_po = create_purchase_order(**po_data)
		doc_po.append("taxes", {
                    "charge_type": "On Net Total",
                    "account_head": account_name,
                    "rate": 12,
                    "description": "Input GST",
                })
		doc_po.submit()
		self.assertEqual(doc_po.discount_amount, 1000)
		self.assertEqual(doc_po.grand_total, 10080)

		doc_pr = make_pr_for_po(doc_po.name)
		doc_pi = make_pi_against_pr(doc_pr.name)

		self.assertEqual(doc_pi.discount_amount, 1000)
		self.assertEqual(doc_pi.grand_total, 10080)

		# Accounting Ledger Checks
		pi_gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": doc_pi.name}, fields=["account", "debit", "credit"])

		# PI Ledger Validation
		pi_total = sum(entry["debit"] for entry in pi_gl_entries)
		self.assertEqual(pi_total, 10080) 

	def test_po_additional_discount_TC_B_055(self):
		# Scenario : PO => PI [With Additional Discount]

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"supplier": "_Test Supplier",
            "schedule_date": "2025-01-13",
			"qty" : 1,
			"rate" : 10000,
			"apply_discount_on" : "Net Total",
			"additional_discount_percentage" :10 ,
			"do_not_submit":1
		}

		acc = frappe.new_doc("Account")
		acc.account_name = "Input Tax IGST"
		acc.parent_account = "Tax Assets - _TC"
		acc.company = "_Test Company"
		account_name = frappe.db.exists("Account", {"account_name" : "Input Tax IGST","company": "_Test Company" })
		if not account_name:
			account_name = acc.insert()

		doc_po = create_purchase_order(**po_data)
		doc_po.append("taxes", {
                    "charge_type": "On Net Total",
                    "account_head": account_name,
                    "rate": 12,
                    "description": "Input GST",
                })
		doc_po.submit()
		self.assertEqual(doc_po.discount_amount, 1000)
		self.assertEqual(doc_po.grand_total, 10080)

		doc_pi = make_pi_from_po(doc_po.name)
		doc_pi.insert()
		doc_pi.submit()
		self.assertEqual(doc_pi.discount_amount, 1000)
		self.assertEqual(doc_pi.grand_total, 10080)

		# Accounting Ledger Checks
		pi_gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": doc_pi.name}, fields=["account", "debit", "credit"])

		# PI Ledger Validation
		pi_total = sum(entry["debit"] for entry in pi_gl_entries)
		self.assertEqual(pi_total, 10080) 

	def test_po_additional_discount_TC_B_058(self):
		# Scenario : PO => PR => PI [With Additional Discount on Grand Total]

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"supplier": "_Test Supplier",
            "schedule_date": "2025-01-13",
			"qty" : 1,
			"rate" : 10000,
			"apply_discount_on" : "Grand Total",
			"additional_discount_percentage" :10 ,
			"do_not_submit":1
		}

		acc = frappe.new_doc("Account")
		acc.account_name = "Input Tax IGST"
		acc.parent_account = "Tax Assets - _TC"
		acc.company = "_Test Company"
		account_name = frappe.db.exists("Account", {"account_name" : "Input Tax IGST","company": "_Test Company" })
		if not account_name:
			account_name = acc.insert()

		doc_po = create_purchase_order(**po_data)
		doc_po.append("taxes", {
                    "charge_type": "On Net Total",
                    "account_head": account_name,
                    "rate": 12,
                    "description": "Input GST",
                })
		doc_po.submit()
		self.assertEqual(doc_po.discount_amount, 1120)
		self.assertEqual(doc_po.grand_total, 10080)

		doc_pr = make_pr_for_po(doc_po.name)
		doc_pi = make_pi_against_pr(doc_pr.name)

		self.assertEqual(doc_pi.discount_amount, 1120)
		self.assertEqual(doc_pi.grand_total, 10080)

		# Accounting Ledger Checks
		pi_gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": doc_pi.name}, fields=["account", "debit", "credit"])

		# PI Ledger Validation
		pi_total = sum(entry["debit"] for entry in pi_gl_entries)
		self.assertEqual(pi_total, 10080) 

	def test_po_additional_discount_TC_B_061(self):
		# Scenario : PO => PI [With Additional Discount]

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"supplier": "_Test Supplier",
            "schedule_date": "2025-01-13",
			"qty" : 1,
			"rate" : 10000,
			"apply_discount_on" : "Grand Total",
			"additional_discount_percentage" :10 ,
			"do_not_submit":1
		}

		acc = frappe.new_doc("Account")
		acc.account_name = "Input Tax IGST"
		acc.parent_account = "Tax Assets - _TC"
		acc.company = "_Test Company"
		account_name = frappe.db.exists("Account", {"account_name" : "Input Tax IGST","company": "_Test Company" })
		if not account_name:
			account_name = acc.insert()

		doc_po = create_purchase_order(**po_data)
		doc_po.append("taxes", {
                    "charge_type": "On Net Total",
                    "account_head": account_name,
                    "rate": 12,
                    "description": "Input GST",
                })
		doc_po.submit()
		self.assertEqual(doc_po.discount_amount, 1120)
		self.assertEqual(doc_po.grand_total, 10080)

		doc_pi = make_pi_from_po(doc_po.name)
		doc_pi.insert()
		doc_pi.submit()
		self.assertEqual(doc_pi.discount_amount, 1120)
		self.assertEqual(doc_pi.grand_total, 10080)

		# Accounting Ledger Checks
		pi_gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": doc_pi.name}, fields=["account", "debit", "credit"])

		# PI Ledger Validation
		pi_total = sum(entry["debit"] for entry in pi_gl_entries)
		self.assertEqual(pi_total, 10080) 

	def test_po_additional_discount_TC_B_063(self):
		# Scenario : PO => PI [With Additional Discount]

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"supplier": "_Test Supplier",
            "schedule_date": "2025-01-13",
			"qty" : 1,
			"rate" : 10000,
			"apply_discount_on" : "Grand Total",
			"additional_discount_percentage" :10 ,
			"do_not_submit":1
		}

		acc = frappe.new_doc("Account")
		acc.account_name = "Input Tax IGST"
		acc.parent_account = "Tax Assets - _TC"
		acc.company = "_Test Company"
		account_name = frappe.db.exists("Account", {"account_name" : "Input Tax IGST","company": "_Test Company" })
		if not account_name:
			account_name = acc.insert()

		doc_po = create_purchase_order(**po_data)
		doc_po.append("taxes", {
                    "charge_type": "On Net Total",
                    "account_head": account_name,
                    "rate": 12,
                    "description": "Input GST",
                })
		doc_po.submit()
		self.assertEqual(doc_po.discount_amount, 1120)
		self.assertEqual(doc_po.grand_total, 10080)

	def test_po_with_additional_discount_TC_B_057(self):
		company = "_Test Company"
		item_code = "Testing-31"
		target_warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_price = 10000
		if not frappe.db.exists("Item", item_code):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"is_stock_item": 1,
				"is_purchase_item": 1,
				"is_sales_item": 0,
				"company": company
			}).insert()
		pi = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": supplier,
			"company": company,
			"schedule_date": today(),
			"set_warehouse": target_warehouse,
			"items": [
				{
					"item_code": item_code,
					"warehouse": target_warehouse,
					"qty": 1,
					"rate": item_price
				}
			]
		})
		pi.insert()
		self.assertEqual(len(pi.items), 1)
		self.assertEqual(pi.items[0].rate, item_price)
		self.assertEqual(pi.net_total, item_price)
		pi.apply_discount_on = "Net Total"
		pi.additional_discount_percentage = 10
		pi.save()
		pi.submit()
		self.assertEqual(pi.discount_amount, 1000)
		self.assertEqual(pi.net_total, 9000)

	def test_partial_pr_pi_flow_TC_B_103(self):
		# 1. Create PO
		po_data = {
			"doctype": "Purchase Order",
			"supplier": "_Test Supplier",
			"company": "_Test Company",
			"items": [
				{
					"item_code": "_Test Item",
					"qty": 10,
					"rate": 100,
					"warehouse": "Stores - _TC",
					"schedule_date": "2025-01-09"
				},
				{
					"item_code": "Book",
					"qty": 5,
					"rate": 500,
					"warehouse": "Stores - _TC",
					"schedule_date": "2025-01-10"
				}
			],
		}
		purchase_order = frappe.get_doc(po_data)
		purchase_order.insert()
		tax_list = create_taxes_interstate()
		for tax in tax_list:
			purchase_order.append("taxes", tax)
		purchase_order.submit()

		# Validate PO Analytics
		po_status = frappe.get_doc("Purchase Order", purchase_order.name)
		self.assertEqual(po_status.status, "To Receive and Bill")
		self.assertEqual(po_status.items[0].received_qty, 0)
		self.assertEqual(po_status.items[0].billed_qty, 0)

		# 2. Create Partial PR
		pr_data = {
			"doctype": "Purchase Receipt",
			"supplier": "_Test Supplier",
			"company": "_Test Company",
			"items": [
				{
					"item_code": "_Test Item",
					"qty": 2,
					"warehouse": "Stores - _TC",
					"purchase_order": purchase_order.name
				},
				{
					"item_code": "Book",
					"qty": 5,
					"warehouse": "Stores - _TC",
					"purchase_order": purchase_order.name
				}
			]
		}
		purchase_receipt = frappe.get_doc(pr_data)
		purchase_receipt.insert()
		purchase_receipt.submit()

		# Validate PR Analytics
		po_status.reload()
		self.assertEqual(po_status.items[0].received_qty, 2)
		self.assertEqual(po_status.items[1].received_qty, 5)

		# 3. Create PI for Partial PR
		pi_data = {
			"doctype": "Purchase Invoice",
			"supplier": "_Test Supplier",
			"company": "_Test Company",
			"items": purchase_receipt.items,
			"taxes": purchase_order.taxes,
			"supplier_invoice_no": "INV-002"
		}
		purchase_invoice = frappe.get_doc(pi_data)
		purchase_invoice.insert()
		purchase_invoice.submit()

		# Validate PI Accounting Entries
		pi_gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": purchase_invoice.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed" and entry["debit"] == 1200 for entry in pi_gl_entries))
		self.assertTrue(any(entry["account"] == "CGST" and entry["debit"] == 54 for entry in pi_gl_entries))
		self.assertTrue(any(entry["account"] == "SGST" and entry["debit"] == 54 for entry in pi_gl_entries))
		self.assertTrue(any(entry["account"] == "Creditors" and entry["credit"] == 1308 for entry in pi_gl_entries))

	def test_po_with_uploader_TC_B_091(self):
		# Test Data
		po_data = {
			"doctype": "Purchase Order",
			"company": "_Test Company",
			"supplier": "_Test Supplier",
			"set_posting_time": 1,
			"posting_date": "2025-01-10",
			"update_stock": 1,
			"items": []
		}

		# Create PO Document
		po_doc = frappe.get_doc(po_data)
		
		# Create Excel Data
		excel_data = {
			"Item Code": ["_Test Item", "_Test Item Home Desktop 200"],
			"Warehouse": ["_Test Warehouse 1 - _TC", "_Test Warehouse 1 - _TC"],
			"Qty": [1, 1],
			"Rate": [2000, 1000]
		}

		# Create DataFrame and save to Excel
		df = pd.DataFrame(excel_data)
		with BytesIO() as output:
			with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
				df.to_excel(writer, index=False)
			output.seek(0)
			# Simulate the upload
			# Assuming the item table is uploaded from an Excel file

		# Now, we would have the uploaded data in PO items table.
		for index, row in df.iterrows():
			po_doc.append("items", {
				"item_code": row['Item Code'],
				"warehouse": row['Warehouse'],
				"qty": row['Qty'],
				"rate": row['Rate']
			})
		
		# Insert and Submit PO
		po_doc.insert()
		po_doc.submit()

		# Assertions for PO Items table
		self.assertEqual(len(po_doc.items), 2, "All items should be added to the PO.")
		self.assertEqual(po_doc.items[0].item_code, "_Test Item", "First item code should be '_Test Item'.")
		self.assertEqual(po_doc.items[1].item_code, "_Test Item Home Desktop 200", "Second item code should be '_Test Item Home Desktop 200'.")
		self.assertEqual(po_doc.items[0].rate, 2000, "Rate for _Test Item should be 2000.")
		self.assertEqual(po_doc.items[1].rate, 1000, "Rate for _Test Item Home Desktop 200 should be 1000.")
		
		# Create PR and PI from PO
		pr_doc = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"purchase_order": po_doc.name,
			"items": po_doc.items
		})
		pr_doc.insert()
		pr_doc.submit()

		pi_doc = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"purchase_receipt": pr_doc.name,
			"items": pr_doc.items
		})
		pi_doc.insert()
		pi_doc.submit()

		# Assertions for Accounting Entries
		gle = frappe.get_all("GL Entry", filters={"voucher_no": pi_doc.name}, fields=["account", "debit", "credit"])
		self.assertGreater(len(gle), 0, "GL Entries should be created.")

		# Validate Stock Ledger
		sle = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": pi_doc.name}, fields=["item_code", "actual_qty", "stock_value"])
		self.assertEqual(len(sle), 2, "Stock Ledger should have entries for both items.")
		self.assertEqual(sle[0]["item_code"], "_Test Item", "Stock Ledger should contain _Test Item.")
		self.assertEqual(sle[1]["item_code"], "_Test Item Home Desktop 200", "Stock Ledger should contain _Test Item Home Desktop 200.")
		self.assertEqual(sle[0]["actual_qty"], 1, "Quantity for _Test Item should be 1.")
		self.assertEqual(sle[1]["actual_qty"], 1, "Quantity for _Test Item Home Desktop 200 should be 1.")

		# Cleanup
		pi_doc.cancel()
		pr_doc.cancel()
		po_doc.cancel()

	def test_po_pr_pi_with_shipping_rule_TC_B_064(self):
		# Scenario : PO=>PR=>PI [With Shipping Rule]
		po = {
			"doctype": "Purchase Order",
			"company": "_Test Company",
			
			"supplier": "_Test Supplier",
			"set_posting_time": 1,
			"posting_date": "2025-01-15",
			"required_by_date": "2025-01-20",
			"shipping_rule": "Ship-Buy",
			"item_code": "_Test Item",
			"warehouse": "_Test Warehouse 1 - _TC",
			"qty": 1,
			"rate": 3000
		}
		doc_po = make_purchase_order(**po)
		doc_po.insert()
		doc_po.submit()

		self.assertEqual(doc_po.grand_total, 3200, "Grand Total should include Shipping Rule (3000 + 200 = 3200).")
		self.assertEqual(doc_po.status, "To Receive and Bill", "PO status should be 'To Receive and Bill'.")

		doc_pr = make_pr_for_po(po.name)

		sle = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": doc_pr.name}, fields=["actual_qty", "item_code"])
		self.assertEqual(len(sle), 1, "Stock Ledger Entry should exist for the received item.")
		self.assertEqual(sle[0]["actual_qty"], 1, "Stock Ledger should reflect 1 qty received for _Test Item.")

		gl_entries_pr = frappe.get_all("GL Entry", filters={"voucher_no": doc_pr.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock In Hand - _Test Company" and entry["debit"] == 3200 for entry in gl_entries_pr),
						"Stock In Hand account should be debited with 3200.")
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _Test Company" and entry["credit"] == 3000 for entry in gl_entries_pr),
						"Stock Received But Not Billed account should be credited with 3000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _Test Company" and entry["credit"] == 200 for entry in gl_entries_pr),
						"Shipping Rule account should be credited with 200.")
		self.assertEqual(doc_pr.status, "To Bill", "PR status should be 'To Bill'.")

		doc_pi = make_pi_against_pr(doc_pr.name)

		gl_entries_pi = frappe.get_all("GL Entry", filters={"voucher_no": doc_pi.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _Test Company" and entry["debit"] == 3000 for entry in gl_entries_pi),
						"Stock Received But Not Billed account should be debited with 3000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _Test Company" and entry["debit"] == 200 for entry in gl_entries_pi),
						"Shipping Rule account should be debited with 200.")
		self.assertTrue(any(entry["account"] == "Creditors - _Test Company" and entry["credit"] == 3200 for entry in gl_entries_pi),
						"Creditors account should be credited with 3200.")
		self.assertEqual(doc_pi.status, "Unpaid", "PI status should be 'Unpaid'.")

		po.reload()
		doc_pr.reload()
		self.assertEqual(po.status, "Completed", "PO status should be 'Completed'.")
		self.assertEqual(doc_pr.status, "Completed", "PR status should be 'Completed'.")

		self.assertEqual(doc_pr.purchase_order, po.name, "PR should be linked to the PO.")
		self.assertEqual(doc_pi.purchase_receipt, doc_pr.name, "PI should be linked to the PR.")

		# Cleanup
		doc_pi.cancel()
		doc_pr.cancel()
		po.cancel()

	def test_po_pi_pr_flow_TC_B_067(self):
		# Scenario : PO=>PI=>PR [With Shipping Rule]
		po = {
			"doctype": "Purchase Order",
			"company": "_Test Company",
			"supplier": "_Test Supplier",
			"set_posting_time": 1,
			"posting_date": "2025-01-15",
			"required_by_date": "2025-01-20",
			"shipping_rule": "Ship-Buy",
			"item_code": "_Test Item",
			"warehouse": "_Test Warehouse 1 - _TC",
			"qty": 1,
			"rate": 3000
		}

		doc_po = create_purchase_order(**po)

		self.assertEqual(po.grand_total, 3200, "Grand Total should include Shipping Rule (3000 + 200 = 3200).")
		self.assertEqual(po.status, "To Receive and Bill", "PO status should be 'To Receive and Bill'.")

		pi = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"purchase_order": doc_po.name,
			"items": [
				{
					"item_code": "_Test Item",
					"qty": 1,
					"rate": 3000
				}
			]
		})
		pi.insert()
		pi.submit()

		gl_entries_pi = frappe.get_all("GL Entry", filters={"voucher_no": pi.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed -  - _TC" and entry["debit"] == 3000 for entry in gl_entries_pi),
						"Stock Received But Not Billed account should be debited with 3000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule -  - _TC" and entry["debit"] == 200 for entry in gl_entries_pi),
						"Shipping Rule account should be debited with 200.")
		self.assertTrue(any(entry["account"] == "Creditors -  - _TC" and entry["credit"] == 3200 for entry in gl_entries_pi),
						"Creditors account should be credited with 3200.")
		self.assertEqual(pi.status, "Unpaid", "PI status should be 'Unpaid'.")
		doc_po.reload()
		self.assertEqual(doc_po.status, "To Receive", "doc_po status should update to 'To Receive' after PI submission.")

		pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"purchase_invoice": pi.name,
			"items": [
				{
					"item_code": "_Test Item",
					"warehouse": "_Test Warehouse 1 - _TC",
					"qty": 1,
					"rate": 3000
				}
			]
		})
		pr.insert()
		pr.submit()

		sle = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": pr.name}, fields=["actual_qty", "item_code"])
		self.assertEqual(len(sle), 1, "Stock Ledger Entry should exist for the received item.")
		self.assertEqual(sle[0]["actual_qty"], 1, "Stock Ledger should reflect 1 qty received for _Test Item.")

		gl_entries_pr = frappe.get_all("GL Entry", filters={"voucher_no": pr.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock In Hand -  - _TC" and entry["debit"] == 3200 for entry in gl_entries_pr),
						"Stock In Hand account should be debited with 3200.")
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed -  - _TC" and entry["credit"] == 3000 for entry in gl_entries_pr),
						"Stock Received But Not Billed account should be credited with 3000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule -  - _TC" and entry["credit"] == 200 for entry in gl_entries_pr),
						"Shipping Rule account should be credited with 200.")
		self.assertEqual(pr.status, "Completed", "PR status should be 'Completed'.")

		self.assertEqual(pr.purchase_invoice, pi.name, "PR should be linked to the PI.")
		self.assertEqual(pi.purchase_order, po.name, "PI should be linked to the PO.")
		po.reload()
		self.assertEqual(po.status, "Completed", "PO status should be 'Completed' after PR submission.")

		# Cleanup
		pr.cancel()
		pi.cancel()
		po.cancel()

	def test_po_pr_multiple_pi_flow_TC_B_066(self):
		#Scenario : PO=>PR=>2PI 

		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"company": "_Test Company",
			"supplier": "_Test Supplier",
			"set_posting_time": 1,
			"posting_date": "2025-01-15",
			"required_by_date": "2025-01-20",
			"shipping_rule": "Ship-Buy",
			"items": [
				{
					"item_code": "_Test Item",
					"warehouse": "_Test Warehouse 1 - _TC",
					"qty": 4,
					"rate": 3000
     }]
		})
	
	def test_inter_state_CGST_and_SGST_TC_B_097(self):
		po = create_purchase_order(qty=1,rate = 100,do_not_save=True)
		po.save()
		purchase_tax_and_value = frappe.db.get_value('Purchase Taxes and Charges Template',{'company':po.company,'tax_category':'In-State'},'name')
		po.taxes_and_charges = purchase_tax_and_value
		po.save()
		po.submit()
		po.reload()
	
		self.assertEqual(po.grand_total, 118)
	
		pr = make_purchase_receipt(po.name)
		pr.taxes_and_charges = purchase_tax_and_value
		pr.save()
		frappe.db.set_value('Company',pr.company,'enable_perpetual_inventory',1)
		frappe.db.set_value('Company',pr.company,'enable_provisional_accounting_for_non_stock_items',1)
		frappe.db.set_value('Company',pr.company,'stock_received_but_not_billed','Stock Received But Not Billed - _TC')
		frappe.db.set_value('Company',pr.company,'default_inventory_account','Stock In Hand - _TC')
		frappe.db.set_value('Company',pr.company,'default_provisional_account','Stock In Hand - _TC')
		pr.submit()
		pr.reload()
		account_entries = frappe.db.get_all('GL Entry',{'voucher_type':'Purchase Receipt','voucher_no':pr.name},['account','debit','credit'])
		for entries in account_entries:
			if entries.account == 'Stock In Hand - _TC':
				self.assertEqual(entries.debit, 100)
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.credit, 100)

		stock_entries = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':pr.name},'item_code')
		self.assertEqual(stock_entries,pr.items[0].item_code)

		pi = make_pi_from_pr(pr.name)
		pi.save()
		pi.submit()

		account_entries_pi = frappe.db.get_all('GL Entry',{'voucher_no':pi.name},['account','debit','credit'])
		for entries in account_entries_pi:
			if entries.account == 'Input Tax SGST - _TC':
				self.assertEqual(entries.debit, 9)
			if entries.account == 'Input Tax CGST - _TC':
				self.assertEqual(entries.debit, 9)
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.debit,100)
			if entries.account == 'Creditors - _TC':
				self.assertEqual(entries.credit, 118.0)

	

	def test_outer_state_IGST_TC_B_098(self):
		po = create_purchase_order(supplier='_Test Registered Supplier',qty=1,rate = 100,do_not_save=True)
		po.save()
		purchase_tax_and_value = frappe.db.get_value('Purchase Taxes and Charges Template',{'company':po.company,'tax_category':'Out-State'},'name')
		po.taxes_and_charges = purchase_tax_and_value
		po.save()
		po.submit()
		po.reload()
		self.assertEqual(po.grand_total, 118)
		pr = make_purchase_receipt(po.name)
		pr.taxes_and_charges = purchase_tax_and_value
		pr.save()

		frappe.db.set_value('Company',pr.company,'enable_perpetual_inventory',1)
		frappe.db.set_value('Company',pr.company,'enable_provisional_accounting_for_non_stock_items',1)
		frappe.db.set_value('Company',pr.company,'stock_received_but_not_billed','Stock Received But Not Billed - _TC')
		frappe.db.set_value('Company',pr.company,'default_inventory_account','Stock In Hand - _TC')
		frappe.db.set_value('Company',pr.company,'default_provisional_account','Stock In Hand - _TC')

		pr.submit()
		pr.reload()
		
		account_entries = frappe.db.get_all('GL Entry',{'voucher_type':'Purchase Receipt','voucher_no':pr.name},['account','debit','credit'])
		for entries in account_entries:
			if entries.account == 'Stock In Hand - _TC':
				self.assertEqual(entries.debit, 100)
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.credit, 100)

		stock_entries = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':pr.name},'item_code')
		self.assertEqual(stock_entries,pr.items[0].item_code)
		self.assertEqual(pr.status,'To Bill')
		pi = make_pi_from_pr(pr.name)
		pi.save()
		pi.submit()

		account_entries_pi = frappe.db.get_all('GL Entry',{'voucher_no':pi.name},['account','debit','credit'])
		for entries in account_entries_pi:
			if entries.account == 'Input Tax IGST - _TC':
				self.assertEqual(entries.debit, 18)
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.debit,100)
			if entries.account == 'Creditors - _TC':
				self.assertEqual(entries.credit, 118.0)
		pi.reload()
		self.assertEqual(pi.status,'Unpaid')

	def test_po_ignore_pricing_rule_TC_B_049(self):
		company = "_Test Company"
		item_code = "Testing-31"
		target_warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_price = 130

		if not frappe.db.exists("Item", item_code):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"is_stock_item": 1,
				"is_purchase_item": 1,
				"is_sales_item": 0,
				"company": company
			}).insert()

		item_price_doc = frappe.get_doc({
			"doctype": "Item Price",
			"price_list": "Standard Buying",
			"item_code": item_code,
			"price_list_rate": item_price
		}).insert()

		pricing_rule = frappe.get_doc({
			"doctype": "Pricing Rule",
			"title": "10% Discount",
			"company": company,
			"apply_on": "Item Code",
			"items":[
				{
					"item_code":item_code
				}
			],
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 10,
			"selling": 0,
			"buying": 1
		}).insert()

		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": supplier,
			"company": company,
			"schedule_date":today(),
			"set_warehouse": target_warehouse,
			"items": [
				{
					"item_code": item_code,
					"warehouse": target_warehouse,
					"qty": 1
				}
			]
		})
		po.insert()
		po.submit()

		
		self.assertEqual(po.grand_total, 12200, "Grand Total should include Shipping Rule (12000 + 200 = 12200).")
		self.assertEqual(po.status, "To Receive and Bill", "PO status should be 'To Receive and Bill'.")

		
		pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"purchase_order": po.name,
			"items": [
				{
					"item_code": "_Test Item",
					"warehouse": "_Test Warehouse 1 - _TC",
					"qty": 4,
					"rate": 3000
				}
			]
		})
		pr.insert()
		pr.submit()

		
		sle = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": pr.name}, fields=["actual_qty", "item_code"])
		self.assertEqual(len(sle), 1, "Stock Ledger Entry should exist for the received item.")
		self.assertEqual(sle[0]["actual_qty"], 4, "Stock Ledger should reflect 4 qty received for _Test Item.")

		gl_entries_pr = frappe.get_all("GL Entry", filters={"voucher_no": pr.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock In Hand - _TC" and entry["debit"] == 12200 for entry in gl_entries_pr),
						"Stock In Hand account should be debited with 12200.")
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _TC" and entry["credit"] == 12000 for entry in gl_entries_pr),
						"Stock Received But Not Billed account should be credited with 12000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _TC" and entry["credit"] == 200 for entry in gl_entries_pr),
						"Shipping Rule account should be credited with 200.")
		self.assertEqual(pr.status, "To Bill", "PR status should be 'To Bill'.")

		
		pi_1 = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"purchase_receipt": pr.name,
			"items": [
				{
					"item_code": "_Test Item",
					"qty": 2,
					"rate": 3000
				}
			]
		})
		pi_1.insert()
		pi_1.submit()

		
		gl_entries_pi_1 = frappe.get_all("GL Entry", filters={"voucher_no": pi_1.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _TC" and entry["debit"] == 6000 for entry in gl_entries_pi_1),
						"Stock Received But Not Billed account should be debited with 6000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _TC" and entry["debit"] == 200 for entry in gl_entries_pi_1),
						"Shipping Rule account should be debited with 200.")
		self.assertTrue(any(entry["account"] == "Creditors - _TC" and entry["credit"] == 6200 for entry in gl_entries_pi_1),
						"Creditors account should be credited with 6200.")
		self.assertEqual(pi_1.status, "Unpaid", "1st PI status should be 'Unpaid'.")
		pr.reload()
		self.assertEqual(pr.status, "Partially Billed", "PR status should be 'Partially Billed' after 1st PI.")

		
		pi_2 = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"purchase_receipt": pr.name,
			"items": [
				{
					"item_code": "_Test Item",
					"qty": 2,
					"rate": 3000
				}
			]
		})
		pi_2.insert()
		pi_2.submit()

		
		gl_entries_pi_2 = frappe.get_all("GL Entry", filters={"voucher_no": pi_2.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _TC" and entry["debit"] == 6000 for entry in gl_entries_pi_2),
						"Stock Received But Not Billed account should be debited with 6000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _TC" and entry["debit"] == 200 for entry in gl_entries_pi_2),
						"Shipping Rule account should be debited with 200.")
		self.assertTrue(any(entry["account"] == "Creditors - _TC" and entry["credit"] == 6200 for entry in gl_entries_pi_2),
						"Creditors account should be credited with 6200.")
		self.assertEqual(pi_2.status, "Unpaid", "2nd PI status should be 'Unpaid'.")
		pr.reload()
		po.reload()
		self.assertEqual(pr.status, "Completed", "PR status should be 'Completed' after 2nd PI.")
		self.assertEqual(po.status, "Completed", "PO status should be 'Completed' after 2nd PI.")

		
		self.assertEqual(pr.purchase_order, po.name, "PR should be linked to the PO.")
		self.assertEqual(pi_1.purchase_receipt, pr.name, "1st PI should be linked to the PR.")
		self.assertEqual(pi_2.purchase_receipt, pr.name, "2nd PI should be linked to the PR.")

		
		pi_2.cancel()
		pi_1.cancel()
		pr.cancel()
		po.cancel()

	def test_po_pr_pi_multiple_flow_TC_B_065(self):
		# Scenario : PO=>2PR=>2PI 
		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"company": "_Test Company",
			"supplier": "_Test Supplier",
			"set_posting_time": 1,
			"posting_date": "2025-01-15",
			"required_by_date": "2025-01-20",
			"shipping_rule": "Ship-Buy",
			"items": [
				{
					"item_code": "_Test Item",
					"warehouse": "_Test Warehouse 1 - _TC",
					"qty": 4,
					"rate": 3000
				}
			]
		})
		po.insert()
		po.submit()

		self.assertEqual(po.grand_total, 12200, "Grand Total should include Shipping Rule (12000 + 200 = 12200).")
		self.assertEqual(po.status, "To Receive and Bill", "PO status should be 'To Receive and Bill'.")

		pr_1 = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"purchase_order": po.name,
			"items": [
				{
					"item_code": "_Test Item",
					"warehouse": "_Test Warehouse 1 - _TC",
					"qty": 2,
					"rate": 3000
				}
			]
		})
		pr_1.insert()
		pr_1.submit()

		gl_entries_pr_1 = frappe.get_all("GL Entry", filters={"voucher_no": pr_1.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock In Hand - _TCd" and entry["debit"] == 6200 for entry in gl_entries_pr_1),
						"Stock In Hand account should be debited with 6200.")
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _TCd" and entry["credit"] == 6000 for entry in gl_entries_pr_1),
						"Stock Received But Not Billed account should be credited with 6000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _TCd" and entry["credit"] == 200 for entry in gl_entries_pr_1),
						"Shipping Rule account should be credited with 200.")
		self.assertEqual(pr_1.status, "To Bill", "1st PR status should be 'To Bill'.")

		pi_1 = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"purchase_receipt": pr_1.name,
			"items": [
				{
					"item_code": "_Test Item",
					"qty": 2,
					"rate": 3000
				}
			]
		})
		pi_1.insert()
		pi_1.submit()

		gl_entries_pi_1 = frappe.get_all("GL Entry", filters={"voucher_no": pi_1.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _TCd" and entry["debit"] == 6000 for entry in gl_entries_pi_1),
						"Stock Received But Not Billed account should be debited with 6000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _TCd" and entry["debit"] == 200 for entry in gl_entries_pi_1),
						"Shipping Rule account should be debited with 200.")
		self.assertTrue(any(entry["account"] == "Creditors - _TCd" and entry["credit"] == 6200 for entry in gl_entries_pi_1),
						"Creditors account should be credited with 6200.")
		self.assertEqual(pi_1.status, "Unpaid", "1st PI status should be 'Unpaid'.")
		pr_1.reload()
		self.assertEqual(pr_1.status, "Completed", "1st PR status should be 'Completed' after 1st PI.")

		pr_2 = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"purchase_order": po.name,
			"items": [
				{
					"item_code": "_Test Item",
					"warehouse": "_Test Warehouse 1 - _TC",
					"qty": 2,
					"rate": 3000
				}
			]
		})
		pr_2.insert()
		pr_2.submit()

		gl_entries_pr_2 = frappe.get_all("GL Entry", filters={"voucher_no": pr_2.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock In Hand - _TCd" and entry["debit"] == 6200 for entry in gl_entries_pr_2),
						"Stock In Hand account should be debited with 6200.")
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _TCd" and entry["credit"] == 6000 for entry in gl_entries_pr_2),
						"Stock Received But Not Billed account should be credited with 6000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _TCd" and entry["credit"] == 200 for entry in gl_entries_pr_2),
						"Shipping Rule account should be credited with 200.")
		self.assertEqual(pr_2.status, "To Bill", "2nd PR status should be 'To Bill'.")

		pi_2 = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"purchase_receipt": pr_2.name,
			"items": [
				{
					"item_code": "_Test Item",
					"qty": 2,
					"rate": 3000
				}
			]
		})
		pi_2.insert()
		pi_2.submit()

		gl_entries_pi_2 = frappe.get_all("GL Entry", filters={"voucher_no": pi_2.name}, fields=["account", "debit", "credit"])
		self.assertTrue(any(entry["account"] == "Stock Received But Not Billed - _TCd" and entry["debit"] == 6000 for entry in gl_entries_pi_2),
						"Stock Received But Not Billed account should be debited with 6000.")
		self.assertTrue(any(entry["account"] == "Shipping Rule - _TCd" and entry["debit"] == 200 for entry in gl_entries_pi_2),
						"Shipping Rule account should be debited with 200.")
		self.assertTrue(any(entry["account"] == "Creditors - _TCd" and entry["credit"] == 6200 for entry in gl_entries_pi_2),
						"Creditors account should be credited with 6200.")
		self.assertEqual(pi_2.status, "Unpaid", "2nd PI status should be 'Unpaid'.")
		pr_2.reload()
		po.reload()
		self.assertEqual(pr_2.status, "Completed", "2nd PR status should be 'Completed' after 2nd PI.")
		self.assertEqual(po.status, "Completed", "PO status should be 'Completed' after 2nd PI.")

		self.assertEqual(pr_1.purchase_order, po.name, "1st PR should be linked to the PO.")
		self.assertEqual(pr_2.purchase_order, po.name, "2nd PR should be linked to the PO.")
		self.assertEqual(pi_1.purchase_receipt, pr_1.name, "1st PI should be linked to the 1st PR.")
		self.assertEqual(pi_2.purchase_receipt, pr_2.name, "2nd PI should be linked to the 2nd PR.")

		pi_2.cancel()
		pi_1.cancel()
		pr_2.cancel()
		pr_1.cancel()
		po.cancel()

		self.assertEqual(len(po.items), 1)
		self.assertEqual(po.items[0].rate, 117)
		self.assertEqual(po.items[0].discount_percentage, 10)
		po.ignore_pricing_rule = 1
		po.save()
		po.submit()
		self.assertEqual(po.items[0].rate, 130)


	def test_po_to_pi_with_deferred_expense_TC_B_094(self):
		item = frappe.get_doc({
			'doctype': 'Item',
			'item_code': 'test_expense',
			'item_name': 'Test Expense',
			'is_stock_item': 0,  # Not a stock item
			'enable_deferred_expense': 1,
			'gst_hsn_code': '01011010'
		})
		item.insert()
		po = frappe.get_doc({
			'doctype': 'Purchase Order',
			'supplier': '_Test Supplier 1',
			'schedule_date': today(),
			'items': [{
				'item_code': item.item_code,
				'qty': 1,
				'rate': 1000  # Adjust the rate as needed
			}]
		})
		po.insert()
		po.submit()
		pi = frappe.get_doc({
			'doctype': 'Purchase Invoice',
			'supplier': po.supplier,
			'items': [{
				'item_code': item.item_code,
				'qty': 1,
				'rate': 1000  # Same as PO
			}]
		})
		pi.insert()
		item = frappe.get_doc('Item', item.item_code)
		pi.items[0].enable_deferred_expense = item.enable_deferred_expense
		pi.save()
		self.assertEqual(pi.items[0].enable_deferred_expense, 1)
		pi.submit()
		self.assertEqual(pi.docstatus, 1)

	def test_po_with_actual_account_type_TC_B_133(self):
		po = create_purchase_order(qty=10,rate = 1000, do_not_save=True)
		po.save()
		purchase_tax_and_value = frappe.db.get_value('Purchase Taxes and Charges Template',{'company':po.company,'tax_category':'In-State'},'name')
		po.taxes_and_charges = purchase_tax_and_value
		po.save()
		po.append('taxes',{
			'charge_type':'Actual',
			'account_head' : 'Freight and Forwarding Charges - _TC',
			'description': 'Freight and Forwarding Charges',
			'tax_amount' : 100
		})
		po.save()
		po.submit()
		self.assertEqual(po.grand_total, 11900)
		self.assertEqual(po.taxes_and_charges_added, 1900)

		pr = make_purchase_receipt(po.name)
		pr.save()

		frappe.db.set_value('Company',pr.company,'enable_perpetual_inventory',1)
		frappe.db.set_value('Company',pr.company,'enable_provisional_accounting_for_non_stock_items',1)
		frappe.db.set_value('Company',pr.company,'stock_received_but_not_billed','Stock Received But Not Billed - _TC')
		frappe.db.set_value('Company',pr.company,'default_inventory_account','Stock In Hand - _TC')
		frappe.db.set_value('Company',pr.company,'default_provisional_account','Stock In Hand - _TC')

		pr.submit()
		self.assertEqual(po.grand_total, po.grand_total)
		self.assertEqual(po.taxes_and_charges_added, po.taxes_and_charges_added)


		account_entries_pr = frappe.db.get_all('GL Entry',{'voucher_type':'Purchase Receipt','voucher_no':pr.name},['account','debit','credit'])
		for entries in account_entries_pr:
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.credit,pr.total)
			if entries.account == 'Stock In Hand - _TC':
				self.assertEqual(entries.debit,pr.total)

		stock_entries_item = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':pr.name},'item_code')
		stock_entries_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':pr.name},'actual_qty')
		self.assertEqual(stock_entries_item,pr.items[0].item_code)
		self.assertEqual(stock_entries_qty,pr.items[0].qty)

		pi = make_pi_from_pr(pr.name)
		pi.save()
		pi.submit()

		account_entries_pi = frappe.db.get_all('GL Entry',{'voucher_no':pi.name},['account','debit','credit'])
		
		for entries in account_entries_pi:
			if entries.account == 'Freight and Forwarding Charges - _TC':
				self.assertEqual(entries.debit, 100)
			if entries.account == 'Input Tax SGST - _TC':
				self.assertEqual(entries.debit, 900)
			if entries.account == 'Input Tax CGST - _TC':
				self.assertEqual(entries.debit, 900)
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.debit,10000)
			if entries.account == 'Creditors - _TC':
				self.assertEqual(entries.credit,11900)

	def test_po_with_on_net_total_account_type_TC_B_134(self):
		parking_charges_account = create_new_account(account_name='Parking Charges Account',company='_Test Company',parent_account = 'Cash In Hand - _TC')
		po = create_purchase_order(qty=10,rate = 100, do_not_save=True)
		po.save()
		purchase_tax_and_value = frappe.db.get_value('Purchase Taxes and Charges Template',{'company':po.company,'tax_category':'In-State'},'name')
		po.taxes_and_charges = purchase_tax_and_value
		po.save()
		po.append('taxes',{
			'charge_type':'On Net Total',
			'account_head' : parking_charges_account,
			'description': parking_charges_account,
			'rate' : 5
		})
		po.save()
		po.submit()
		self.assertEqual(po.grand_total, 1230)
		self.assertEqual(po.taxes_and_charges_added, 230)
		pr = make_purchase_receipt(po.name)
		pr.save()
		frappe.db.set_value('Company',pr.company,'enable_perpetual_inventory',1)
		frappe.db.set_value('Company',pr.company,'enable_provisional_accounting_for_non_stock_items',1)
		frappe.db.set_value('Company',pr.company,'stock_received_but_not_billed','Stock Received But Not Billed - _TC')
		frappe.db.set_value('Company',pr.company,'default_inventory_account','Stock In Hand - _TC')
		frappe.db.set_value('Company',pr.company,'default_provisional_account','Stock In Hand - _TC')

		pr.submit()
		self.assertEqual(po.grand_total, po.grand_total)
		self.assertEqual(po.taxes_and_charges_added, po.taxes_and_charges_added)

		account_entries_pr = frappe.db.get_all('GL Entry',{'voucher_type':'Purchase Receipt','voucher_no':pr.name},['account','debit','credit'])

		for entries in account_entries_pr:
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.credit,1000)
			if entries.account == 'Stock In Hand - _TC':
				self.assertEqual(entries.debit,1000)
	

		stock_entries_item = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':pr.name},'item_code')
		stock_entries_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':pr.name},'actual_qty')
		self.assertEqual(stock_entries_item,pr.items[0].item_code)
		self.assertEqual(stock_entries_qty,pr.items[0].qty)

		pi = make_pi_from_pr(pr.name)
		pi.save()
		pi.submit()

		account_entries_pi = frappe.db.get_all('GL Entry',{'voucher_no':pi.name},['account','debit','credit'])

		for entries in account_entries_pi:
			if entries.account == 'Parking Charges Account - _TC':
				self.assertEqual(entries.debit, 50)
			if entries.account == 'Input Tax SGST - _TC':
				self.assertEqual(entries.debit, 90)
			if entries.account == 'Input Tax CGST - _TC':
				self.assertEqual(entries.debit, 90)
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.debit,1000)
			if entries.account == 'Creditors - _TC':
				self.assertEqual(entries.credit,1230)
	
	def test_po_with_on_item_quntity_account_type_TC_B_135(self):
		transportation_chrages_account = create_new_account(account_name='Transportation Charges Account',company='_Test Company',parent_account = 'Cash In Hand - _TC')
		po = create_purchase_order(qty=10,rate = 100, do_not_save=True)
		po.save()
		po.append('items',{
			'item_code':'_Test Item 2',
			'qty':5,
			'rate':200
		})

		po.save()
		purchase_tax_and_value = frappe.db.get_value('Purchase Taxes and Charges Template',{'company':po.company,'tax_category':'In-State'},'name')
		po.taxes_and_charges = purchase_tax_and_value
		po.save()
		po.append('taxes',{
			'charge_type':'On Item Quantity',
			'account_head' : transportation_chrages_account,
			'description': transportation_chrages_account,
			'rate' : 20
		})
		po.save()
		po.submit()
		self.assertEqual(po.grand_total, 2660)
	
		pr = make_purchase_receipt(po.name)

		pr.save()

		frappe.db.set_value('Company',pr.company,'enable_perpetual_inventory',1)
		frappe.db.set_value('Company',pr.company,'enable_provisional_accounting_for_non_stock_items',1)
		frappe.db.set_value('Company',pr.company,'stock_received_but_not_billed','Stock Received But Not Billed - _TC')
		frappe.db.set_value('Company',pr.company,'default_inventory_account','Stock In Hand - _TC')
		frappe.db.set_value('Company',pr.company,'default_provisional_account','Stock In Hand - _TC')

		pr.submit()
		self.assertEqual(po.grand_total, po.grand_total)
		self.assertEqual(po.taxes_and_charges_added, po.taxes_and_charges_added)

		account_entries_pr = frappe.db.get_all('GL Entry',{'voucher_type':'Purchase Receipt','voucher_no':pr.name},['account','debit','credit'])

		for entries in account_entries_pr:
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.credit,2000)
			if entries.account == 'Stock In Hand - _TC':
				self.assertEqual(entries.debit,2000)
	
		stock_entries = frappe.db.get_all('Stock Ledger Entry',{'voucher_no':pr.name},['item_code','actual_qty'])
		for entries in stock_entries:
			if entries.item_code == pr.items[0].item_code:
				self.assertEqual(entries.actual_qty,pr.items[0].qty)
			if entries.item_code == pr.items[1].item_code:
				self.assertEqual(entries.actual_qty,pr.items[1].qty)
		
		pi = make_pi_from_pr(pr.name)
		pi.save()
		pi.submit()

		account_entries_pi = frappe.db.get_all('GL Entry',{'voucher_no':pi.name},['account','debit','credit'])

		for entries in account_entries_pi:
			if entries.account == 'Transportation Charges Account - _TC':
				self.assertEqual(entries.debit, 300)
			if entries.account == 'Input Tax SGST - _TC':
				self.assertEqual(entries.debit, 180)
			if entries.account == 'Input Tax CGST - _TC':
				self.assertEqual(entries.debit, 180)
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.debit,2000)
			if entries.account == 'Creditors - _TC':
				self.assertEqual(entries.credit,2660)
	
	def test_po_with_all_account_type_TC_B_136(self):
		parking_charges_account = create_new_account(account_name='Parking Charges Account',company='_Test Company',parent_account = 'Cash In Hand - _TC')
		transportation_chrages_account = create_new_account(account_name='Transportation Charges Account',company='_Test Company',parent_account = 'Cash In Hand - _TC')
		output_cess_account = create_new_account(account_name='Output Cess Account',company='_Test Company',parent_account = 'Cash In Hand - _TC')
		po = create_purchase_order(qty=10,rate = 100, do_not_save=True)
		po.save()
		po.append('items',{
			'item_code':'_Test Item 2',
			'qty':5,
			'rate':200
		})
		po.save()
		purchase_tax_and_value = frappe.db.get_value('Purchase Taxes and Charges Template',{'company':po.company,'tax_category':'In-State'},'name')
		po.taxes_and_charges = purchase_tax_and_value
		po.save()
		taxes = [
			{
			'charge_type':'Actual',
			'account_head' : 'Freight and Forwarding Charges - _TC',
			'description': 'Freight and Forwarding Charges',
			'tax_amount' : 100
			},
			{
			'charge_type':'On Net Total',
			'account_head' : parking_charges_account,
			'description': parking_charges_account,
			'rate' : 5
			},
			{
			'charge_type':'On Item Quantity',
			'account_head' : transportation_chrages_account,
			'description': transportation_chrages_account,
			'rate' : 20
			},
			{
			'charge_type':'On Previous Row Amount',
			'account_head' : output_cess_account,
			'description': output_cess_account,
			'rate' : 5,
			'row_id':5
			}
		]
		for tax in taxes:
			po.append('taxes',tax)
		po.save()
		po.submit()
		self.assertEqual(po.grand_total, 2875)
	
		pr = make_purchase_receipt(po.name)

		pr.save()

		frappe.db.set_value('Company',pr.company,'enable_perpetual_inventory',1)
		frappe.db.set_value('Company',pr.company,'enable_provisional_accounting_for_non_stock_items',1)
		frappe.db.set_value('Company',pr.company,'stock_received_but_not_billed','Stock Received But Not Billed - _TC')
		frappe.db.set_value('Company',pr.company,'default_inventory_account','Stock In Hand - _TC')
		frappe.db.set_value('Company',pr.company,'default_provisional_account','Stock In Hand - _TC')

		pr.submit()
		self.assertEqual(po.grand_total, po.grand_total)
		
		account_entries_pr = frappe.db.get_all('GL Entry',{'voucher_type':'Purchase Receipt','voucher_no':pr.name},['account','debit','credit'])

		for entries in account_entries_pr:
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.credit,2000)
			if entries.account == 'Stock In Hand - _TC':
				self.assertEqual(entries.debit,2000)
	
		stock_entries = frappe.db.get_all('Stock Ledger Entry',{'voucher_no':pr.name},['item_code','actual_qty'])
		for entries in stock_entries:
			if entries.item_code == pr.items[0].item_code:
				self.assertEqual(entries.actual_qty,pr.items[0].qty)
			if entries.item_code == pr.items[1].item_code:
				self.assertEqual(entries.actual_qty,pr.items[1].qty)
		
		pi = make_pi_from_pr(pr.name)
		pi.save()
		pi.submit()

		account_entries_pi = frappe.db.get_all('GL Entry',{'voucher_no':pi.name},['account','debit','credit'])
		
		for entries in account_entries_pi:
			if entries.account == 'Transportation Charges Account - _TC':
				self.assertEqual(entries.debit, 300)
			if entries.account == 'Output Cess Account - _TC':
				self.assertEqual(entries.debit, 15)
			if entries.account == 'Parking Charges Account - _TC':
				self.assertEqual(entries.debit, 100)
			if entries.account == 'Freight and Forwarding Charges - _TC':
				self.assertEqual(entries.debit, 100)
			if entries.account == 'Input Tax SGST - _TC':
				self.assertEqual(entries.debit, 180)
			if entries.account == 'Input Tax CGST - _TC':
				self.assertEqual(entries.debit, 180)
			if entries.account == 'Stock Received But Not Billed - _TC':
				self.assertEqual(entries.debit,2000)
			if entries.account == 'Creditors - _TC':
				self.assertEqual(entries.credit,2875)

	def test_create_po_pr_partial_TC_SCK_046(self):
		po = create_purchase_order(rate=10000,qty=10)
		po.submit()

		pr = create_pr_against_po(po.name, received_qty=5)
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, po.get("items")[0].warehouse)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 50000)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 50000)


		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pr = make_return_doc("Purchase Receipt", pr.name)
		return_pr.get("items")[0].received_qty = -5
		return_pr.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_po_pr_TC_SCK_177(self):
		from erpnext.stock.doctype.warehouse.test_warehouse import create_warehouse

		po = create_purchase_order(qty=10)
		po.submit()

		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 10)
		pr = make_purchase_receipt(po.name)
		pr.company = "_Test Company"
		pr.set_warehouse = "All Warehouses - _TC"
		pr.rejected_warehouse = create_warehouse("_Test Warehouse8", company=pr.company)
		pr.get("items")[0].qty = 8
		pr.get("items")[0].rejected_qty = 2
		pr.insert()
		pr.submit()

		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, 2)
		
def create_po_for_sc_testing():
	from erpnext.controllers.tests.test_subcontracting_controller import (
		make_bom_for_subcontracted_items,
		make_raw_materials,
		make_service_items,
		make_subcontracted_items,
	)

	make_subcontracted_items()
	make_raw_materials()
	make_service_items()
	make_bom_for_subcontracted_items()

	service_items = [
		{
			"warehouse": "_Test Warehouse - _TC",
			"item_code": "Subcontracted Service Item 1",
			"qty": 10,
			"rate": 100,
			"fg_item": "Subcontracted Item SA1",
			"fg_item_qty": 10,
		},
		{
			"warehouse": "_Test Warehouse - _TC",
			"item_code": "Subcontracted Service Item 2",
			"qty": 20,
			"rate": 25,
			"fg_item": "Subcontracted Item SA2",
			"fg_item_qty": 15,
		},
		{
			"warehouse": "_Test Warehouse - _TC",
			"item_code": "Subcontracted Service Item 3",
			"qty": 25,
			"rate": 10,
			"fg_item": "Subcontracted Item SA3",
			"fg_item_qty": 50,
		},
	]

	return create_purchase_order(
		rm_items=service_items,
		is_subcontracted=1,
		supplier_warehouse="_Test Warehouse 1 - _TC",
	)

def prepare_data_for_internal_transfer():
	from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_internal_supplier
	from erpnext.selling.doctype.customer.test_customer import create_internal_customer
	from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import make_purchase_receipt
	from erpnext.stock.doctype.warehouse.test_warehouse import create_warehouse

	company = "_Test Company with perpetual inventory"

	create_internal_customer(
		"_Test Internal Customer 2",
		company,
		company,
	)

	create_internal_supplier(
		"_Test Internal Supplier 2",
		company,
		company,
	)

	warehouse = create_warehouse("_Test Internal Warehouse New 1", company=company)

	create_warehouse("_Test Internal Warehouse GIT", company=company)

	make_purchase_receipt(company=company, warehouse=warehouse, qty=2, rate=100)

	if not frappe.db.get_value("Company", company, "unrealized_profit_loss_account"):
		account = "Unrealized Profit and Loss - TCP1"
		if not frappe.db.exists("Account", account):
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": "Unrealized Profit and Loss",
					"parent_account": "Direct Income - TCP1",
					"company": company,
					"is_group": 0,
					"account_type": "Income Account",
				}
			).insert()

		frappe.db.set_value("Company", company, "unrealized_profit_loss_account", account)


def make_pr_against_po(po, received_qty=0):
	pr = make_purchase_receipt(po)
	pr.get("items")[0].qty = received_qty or 5
	pr.insert()
	pr.submit()
	return pr

def make_return_pi(source_name):
	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

	return_pi = make_debit_note(source_name)
	return_pi.update_outstanding_for_self = 0
	return_pi.insert()
	return_pi.submit()
	return return_pi

def get_same_items():
	return [
		{
			"item_code": "_Test FG Item",
			"warehouse": "_Test Warehouse - _TC",
			"qty": 1,
			"rate": 500,
			"schedule_date": add_days(nowdate(), 1),
		},
		{
			"item_code": "_Test FG Item",
			"warehouse": "_Test Warehouse - _TC",
			"qty": 4,
			"rate": 500,
			"schedule_date": add_days(nowdate(), 1),
		},
	]


def create_purchase_order(**args):
	po = frappe.new_doc("Purchase Order")
	args = frappe._dict(args)
	if args.transaction_date:
		po.transaction_date = args.transaction_date

	po.schedule_date = add_days(nowdate(), 1)
	po.company = args.company or "_Test Company"
	po.supplier = args.supplier or "_Test Supplier"
	po.is_subcontracted = args.is_subcontracted or 0
	po.currency = args.currency or frappe.get_cached_value("Company", po.company, "default_currency")
	po.conversion_factor = args.conversion_factor or 1
	po.supplier_warehouse = args.supplier_warehouse or None
	po.apply_discount_on = args.apply_discount_on or None
	po.additional_discount_percentage = args.additional_discount_percentage or None
	po.discount_amount = args.discount_amount or None

	if args.rm_items:
		for row in args.rm_items:
			po.append("items", row)
	else:
		po.append(
			"items",
			{
				"item_code": args.item or args.item_code or "_Test Item",
				"warehouse": args.warehouse or "_Test Warehouse - _TC",
				"from_warehouse": args.from_warehouse,
				"qty": args.qty or 10,
				"rate": args.rate or 500,
				"schedule_date": add_days(nowdate(), 1),
				"include_exploded_items": args.get("include_exploded_items", 1),
				"against_blanket_order": args.against_blanket_order,
				"against_blanket": args.against_blanket,
				"material_request": args.material_request,
				"material_request_item": args.material_request_item,
			},
		)

	if not args.do_not_save:
		po.set_missing_values()
		po.insert()
		if not args.do_not_submit:
			if po.is_subcontracted:
				supp_items = po.get("supplied_items")
				for d in supp_items:
					if not d.reserve_warehouse:
						d.reserve_warehouse = args.warehouse or "_Test Warehouse - _TC"
			po.submit()

	return po


def create_pr_against_po(po, received_qty=4):
	pr = make_purchase_receipt(po)
	pr.get("items")[0].qty = received_qty
	pr.insert()
	pr.submit()
	return pr


def get_ordered_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"):
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "ordered_qty"))


def get_requested_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"):
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "indented_qty"))


test_dependencies = ["BOM", "Item Price"]

test_records = frappe.get_test_records("Purchase Order")

def make_pi_against_pr(source_name, received_qty=0, item_dict_list = None, args = None):

	doc_pi =  make_pi_from_pr(source_name)
	if received_qty != 0: doc_pi.get("items")[0].qty = received_qty
	
	if item_dict_list is not None:
		for item in item_dict_list:
			doc_pi.append("items", item)

	if args:
		args = frappe._dict(args)
		doc_pi.update(args)

	doc_pi.insert()
	doc_pi.submit()
	return doc_pi


def make_pr_for_po(source_name, received_qty=0, item_dict_list = None):
	doc_pr = make_purchase_receipt(source_name)
	if received_qty != 0: doc_pr.get("items")[0].qty = received_qty
	
	if item_dict_list is not None:
		for item in item_dict_list:
			doc_pr.append("items", item)

	
	doc_pr.insert()
	doc_pr.submit()
	return doc_pr

def check_payment_gl_entries(
	self,
	voucher_no,
	expected_gle,):
	gle = frappe.qb.DocType("GL Entry")
	gl_entries = (
		frappe.qb.from_(gle)
		.select(
			gle.account,
			gle.debit,
			gle.credit,
		)
		.where((gle.voucher_no == voucher_no) & (gle.is_cancelled == 0))
		.orderby(gle.account, gle.debit, gle.credit, order=frappe.qb.desc)
	).run(as_dict=True)
	for row in range(len(expected_gle)):
		for field in ["account", "debit", "credit"]:
			self.assertEqual(expected_gle[row][field], gl_entries[row][field])

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
def create_new_account(account_name,company,parent_account):
		account =  frappe.new_doc('Account')
		account.account_name = account_name
		account.company	= company
		account.parent_account	= parent_account
		account.save()
		return account.name
