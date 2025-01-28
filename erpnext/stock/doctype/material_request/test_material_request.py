# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# ERPNext - web based ERP (http://erpnext.com)
# For license information, please see license.txt


import frappe
import json
from frappe.tests.utils import FrappeTestCase, change_settings
from frappe.utils import flt, today, add_days, nowdate, getdate
from datetime import date

from erpnext.stock.doctype.item.test_item import create_item
from erpnext.stock.doctype.material_request.material_request import (
	make_in_transit_stock_entry,
	make_purchase_order,
	make_stock_entry,
	make_supplier_quotation,
	raise_work_orders,
	make_request_for_quotation
)
from erpnext.stock.doctype.warehouse.test_warehouse import create_warehouse
from erpnext.stock.doctype.pick_list.pick_list import create_stock_entry as pl_stock_entry
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.accounts.doctype.account.test_account import get_inventory_account
from erpnext.stock.doctype.warehouse.test_warehouse import create_warehouse
from erpnext.stock.doctype.item.test_item import create_item, make_item
from erpnext.buying.doctype.request_for_quotation.request_for_quotation import make_supplier_quotation_from_rfq
from erpnext.buying.doctype.supplier_quotation.supplier_quotation import make_purchase_order as create_po_aganist_sq
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt as make_purchase_receipt_aganist_mr
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as create_purchase_invoice
from erpnext.buying.doctype.supplier.test_supplier import create_supplier

class TestMaterialRequest(FrappeTestCase):
	def test_make_purchase_order(self):
		mr = frappe.copy_doc(test_records[0]).insert()

		self.assertRaises(frappe.ValidationError, make_purchase_order, mr.name)

		mr = frappe.get_doc("Material Request", mr.name)
		mr.submit()
		po = make_purchase_order(mr.name)

		self.assertEqual(po.doctype, "Purchase Order")
		self.assertEqual(len(po.get("items")), len(mr.get("items")))

	def test_make_supplier_quotation(self):
		mr = frappe.copy_doc(test_records[0]).insert()

		self.assertRaises(frappe.ValidationError, make_supplier_quotation, mr.name)

		mr = frappe.get_doc("Material Request", mr.name)
		mr.submit()
		sq = make_supplier_quotation(mr.name)

		self.assertEqual(sq.doctype, "Supplier Quotation")
		self.assertEqual(len(sq.get("items")), len(mr.get("items")))

	def test_make_stock_entry(self):
		mr = frappe.copy_doc(test_records[0]).insert()

		self.assertRaises(frappe.ValidationError, make_stock_entry, mr.name)

		mr = frappe.get_doc("Material Request", mr.name)
		mr.material_request_type = "Material Transfer"
		mr.submit()
		se = make_stock_entry(mr.name)

		self.assertEqual(se.stock_entry_type, "Material Transfer")
		self.assertEqual(se.purpose, "Material Transfer")
		self.assertEqual(se.doctype, "Stock Entry")
		self.assertEqual(len(se.get("items")), len(mr.get("items")))


	def test_partial_make_stock_entry(self):
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry as _make_stock_entry
		mr = frappe.copy_doc(test_records[0]).insert()
		source_wh = create_warehouse(
			warehouse_name="_Test Source Warehouse",
			properties={"parent_warehouse": "All Warehouses - _TC"},
			company="_Test Company",
		)
		mr = frappe.get_doc("Material Request", mr.name)
		mr.material_request_type = "Material Transfer"
		for row in mr.items:
			_make_stock_entry(
				item_code=row.item_code,
				qty=10,
				to_warehouse=source_wh,
				company="_Test Company",
				rate=100,
			)
			row.from_warehouse = source_wh
			row.qty = 10
		mr.save()
		mr.submit()
		se = make_stock_entry(mr.name)
		se.get("items")[0].qty = 5
		se.insert()
		se.submit()
		mr.reload()
		self.assertEqual(mr.status, "Partially Received")
		

	def test_in_transit_make_stock_entry(self):
		mr = frappe.copy_doc(test_records[0]).insert()

		self.assertRaises(frappe.ValidationError, make_stock_entry, mr.name)

		mr = frappe.get_doc("Material Request", mr.name)
		mr.material_request_type = "Material Transfer"
		mr.submit()

		in_transit_warehouse = get_in_transit_warehouse(mr.company)
		se = make_in_transit_stock_entry(mr.name, in_transit_warehouse)

		self.assertEqual(se.stock_entry_type, "Material Transfer")
		self.assertEqual(se.purpose, "Material Transfer")
		self.assertEqual(se.doctype, "Stock Entry")
		for row in se.get("items"):
			self.assertEqual(row.t_warehouse, in_transit_warehouse)

	def _insert_stock_entry(self, qty1, qty2, warehouse=None):
		se = frappe.get_doc(
			{
				"company": "_Test Company",
				"doctype": "Stock Entry",
				"posting_date": "2013-03-01",
				"posting_time": "00:00:00",
				"purpose": "Material Receipt",
				"items": [
					{
						"conversion_factor": 1.0,
						"doctype": "Stock Entry Detail",
						"item_code": "_Test Item Home Desktop 100",
						"parentfield": "items",
						"basic_rate": 100,
						"qty": qty1,
						"stock_uom": "_Test UOM 1",
						"transfer_qty": qty1,
						"uom": "_Test UOM 1",
						"t_warehouse": warehouse or "_Test Warehouse 1 - _TC",
						"cost_center": "_Test Cost Center - _TC",
					},
					{
						"conversion_factor": 1.0,
						"doctype": "Stock Entry Detail",
						"item_code": "_Test Item Home Desktop 200",
						"parentfield": "items",
						"basic_rate": 100,
						"qty": qty2,
						"stock_uom": "_Test UOM 1",
						"transfer_qty": qty2,
						"uom": "_Test UOM 1",
						"t_warehouse": warehouse or "_Test Warehouse 1 - _TC",
						"cost_center": "_Test Cost Center - _TC",
					},
				],
			}
		)

		se.set_stock_entry_type()
		se.insert()
		se.submit()

	def test_cannot_stop_cancelled_material_request(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()

		mr.load_from_db()
		mr.cancel()
		self.assertRaises(frappe.ValidationError, mr.update_status, "Stopped")

	def test_mr_changes_from_stopped_to_pending_after_reopen(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()
		self.assertEqual("Pending", mr.status)

		mr.update_status("Stopped")
		self.assertEqual("Stopped", mr.status)

		mr.update_status("Submitted")
		self.assertEqual("Pending", mr.status)

	def test_cannot_submit_cancelled_mr(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()
		mr.load_from_db()
		mr.cancel()
		self.assertRaises(frappe.ValidationError, mr.submit)

	def test_mr_changes_from_pending_to_cancelled_after_cancel(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()
		mr.cancel()
		self.assertEqual("Cancelled", mr.status)

	def test_cannot_change_cancelled_mr(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()
		mr.load_from_db()
		mr.cancel()

		self.assertRaises(frappe.InvalidStatusError, mr.update_status, "Draft")
		self.assertRaises(frappe.InvalidStatusError, mr.update_status, "Stopped")
		self.assertRaises(frappe.InvalidStatusError, mr.update_status, "Ordered")
		self.assertRaises(frappe.InvalidStatusError, mr.update_status, "Issued")
		self.assertRaises(frappe.InvalidStatusError, mr.update_status, "Transferred")
		self.assertRaises(frappe.InvalidStatusError, mr.update_status, "Pending")

	def test_cannot_submit_deleted_material_request(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.delete()

		self.assertRaises(frappe.ValidationError, mr.submit)

	def test_cannot_delete_submitted_mr(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()

		self.assertRaises(frappe.ValidationError, mr.delete)

	def test_stopped_mr_changes_to_pending_after_reopen(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()
		mr.load_from_db()

		mr.update_status("Stopped")
		mr.update_status("Submitted")
		self.assertEqual(mr.status, "Pending")

	def test_pending_mr_changes_to_stopped_after_stop(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()
		mr.load_from_db()

		mr.update_status("Stopped")
		self.assertEqual(mr.status, "Stopped")

	def test_cannot_stop_unsubmitted_mr(self):
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		self.assertRaises(frappe.InvalidStatusError, mr.update_status, "Stopped")

	def test_completed_qty_for_purchase(self):
		existing_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		existing_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		# submit material request of type Purchase
		mr = frappe.copy_doc(test_records[0])
		mr.insert()
		mr.submit()

		# map a purchase order
		po_doc = make_purchase_order(mr.name)
		po_doc.supplier = "_Test Supplier"
		po_doc.transaction_date = "2013-07-07"
		po_doc.schedule_date = "2013-07-09"
		po_doc.get("items")[0].qty = 27.0
		po_doc.get("items")[1].qty = 1.5
		po_doc.get("items")[0].schedule_date = "2013-07-09"
		po_doc.get("items")[1].schedule_date = "2013-07-09"

		# check for stopped status of Material Request
		po = frappe.copy_doc(po_doc)
		po.insert()
		po.load_from_db()
		mr.update_status("Stopped")
		self.assertRaises(frappe.InvalidStatusError, po.submit)
		po.db_set("docstatus", 1)
		self.assertRaises(frappe.InvalidStatusError, po.cancel)

		# resubmit and check for per complete
		mr.load_from_db()
		mr.update_status("Submitted")
		po = frappe.copy_doc(po_doc)
		po.insert()
		po.submit()

		# check if per complete is as expected
		mr.load_from_db()
		self.assertEqual(mr.per_ordered, 50)
		self.assertEqual(mr.get("items")[0].ordered_qty, 27.0)
		self.assertEqual(mr.get("items")[1].ordered_qty, 1.5)

		current_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		current_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		self.assertEqual(current_requested_qty_item1, existing_requested_qty_item1 + 27.0)
		self.assertEqual(current_requested_qty_item2, existing_requested_qty_item2 + 1.5)

		po.cancel()
		# check if per complete is as expected
		mr.load_from_db()
		self.assertEqual(mr.per_ordered, 0)
		self.assertEqual(mr.get("items")[0].ordered_qty, 0)
		self.assertEqual(mr.get("items")[1].ordered_qty, 0)

		current_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		current_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		self.assertEqual(current_requested_qty_item1, existing_requested_qty_item1 + 54.0)
		self.assertEqual(current_requested_qty_item2, existing_requested_qty_item2 + 3.0)

	def test_completed_qty_for_transfer(self):
		existing_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		existing_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		# submit material request of type Purchase
		mr = frappe.copy_doc(test_records[0])
		mr.material_request_type = "Material Transfer"
		mr.insert()
		mr.submit()

		# check if per complete is None
		mr.load_from_db()
		self.assertEqual(mr.per_ordered, 0)
		self.assertEqual(mr.get("items")[0].ordered_qty, 0)
		self.assertEqual(mr.get("items")[1].ordered_qty, 0)

		current_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		current_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		self.assertEqual(current_requested_qty_item1, existing_requested_qty_item1 + 54.0)
		self.assertEqual(current_requested_qty_item2, existing_requested_qty_item2 + 3.0)

		# map a stock entry
		se_doc = make_stock_entry(mr.name)
		se_doc.update(
			{
				"posting_date": "2013-03-01",
				"posting_time": "01:00",
				"fiscal_year": "_Test Fiscal Year 2013",
			}
		)
		se_doc.get("items")[0].update(
			{"qty": 27.0, "transfer_qty": 27.0, "s_warehouse": "_Test Warehouse 1 - _TC", "basic_rate": 1.0}
		)
		se_doc.get("items")[1].update(
			{"qty": 1.5, "transfer_qty": 1.5, "s_warehouse": "_Test Warehouse 1 - _TC", "basic_rate": 1.0}
		)

		# make available the qty in _Test Warehouse 1 before transfer
		self._insert_stock_entry(27.0, 1.5)

		# check for stopped status of Material Request
		se = frappe.copy_doc(se_doc)
		se.insert()
		mr.update_status("Stopped")
		self.assertRaises(frappe.InvalidStatusError, se.submit)

		mr.update_status("Submitted")

		se.flags.ignore_validate_update_after_submit = True
		se.submit()
		mr.update_status("Stopped")
		self.assertRaises(frappe.InvalidStatusError, se.cancel)

		mr.update_status("Submitted")
		se = frappe.copy_doc(se_doc)
		se.insert()
		se.submit()

		# check if per complete is as expected
		mr.load_from_db()
		self.assertEqual(mr.per_ordered, 50)
		self.assertEqual(mr.get("items")[0].ordered_qty, 27.0)
		self.assertEqual(mr.get("items")[1].ordered_qty, 1.5)

		current_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		current_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		self.assertEqual(current_requested_qty_item1, existing_requested_qty_item1 + 27.0)
		self.assertEqual(current_requested_qty_item2, existing_requested_qty_item2 + 1.5)

		# check if per complete is as expected for Stock Entry cancelled
		se.cancel()
		mr.load_from_db()
		self.assertEqual(mr.per_ordered, 0)
		self.assertEqual(mr.get("items")[0].ordered_qty, 0)
		self.assertEqual(mr.get("items")[1].ordered_qty, 0)

		current_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		current_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		self.assertEqual(current_requested_qty_item1, existing_requested_qty_item1 + 54.0)
		self.assertEqual(current_requested_qty_item2, existing_requested_qty_item2 + 3.0)

	def test_over_transfer_qty_allowance(self):
		mr = frappe.new_doc("Material Request")
		mr.company = "_Test Company"
		mr.scheduled_date = today()
		mr.append(
			"items",
			{
				"item_code": "_Test FG Item",
				"item_name": "_Test FG Item",
				"qty": 10,
				"schedule_date": today(),
				"uom": "_Test UOM 1",
				"warehouse": "_Test Warehouse - _TC",
			},
		)

		mr.material_request_type = "Material Transfer"
		mr.insert()
		mr.submit()

		frappe.db.set_single_value("Stock Settings", "mr_qty_allowance", 20)

		# map a stock entry

		se_doc = make_stock_entry(mr.name)
		se_doc.update(
			{
				"posting_date": today(),
				"posting_time": "00:00",
			}
		)
		se_doc.get("items")[0].update(
			{
				"qty": 13,
				"transfer_qty": 12.0,
				"s_warehouse": "_Test Warehouse - _TC",
				"t_warehouse": "_Test Warehouse 1 - _TC",
				"basic_rate": 1.0,
			}
		)

		# make available the qty in _Test Warehouse 1 before transfer
		sr = frappe.new_doc("Stock Reconciliation")
		sr.company = "_Test Company"
		sr.purpose = "Opening Stock"
		sr.append(
			"items",
			{
				"item_code": "_Test FG Item",
				"warehouse": "_Test Warehouse - _TC",
				"qty": 20,
				"valuation_rate": 0.01,
			},
		)
		sr.insert()
		sr.submit()
		se = frappe.copy_doc(se_doc)
		se.insert()
		self.assertRaises(frappe.ValidationError)
		se.items[0].qty = 12
		se.submit()

	def test_completed_qty_for_over_transfer(self):
		existing_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		existing_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		# submit material request of type Purchase
		mr = frappe.copy_doc(test_records[0])
		mr.material_request_type = "Material Transfer"
		mr.insert()
		mr.submit()

		# map a stock entry

		se_doc = make_stock_entry(mr.name)
		se_doc.update(
			{
				"posting_date": "2013-03-01",
				"posting_time": "00:00",
				"fiscal_year": "_Test Fiscal Year 2013",
			}
		)
		se_doc.get("items")[0].update(
			{"qty": 54.0, "transfer_qty": 54.0, "s_warehouse": "_Test Warehouse 1 - _TC", "basic_rate": 1.0}
		)
		se_doc.get("items")[1].update(
			{"qty": 3.0, "transfer_qty": 3.0, "s_warehouse": "_Test Warehouse 1 - _TC", "basic_rate": 1.0}
		)

		# make available the qty in _Test Warehouse 1 before transfer
		self._insert_stock_entry(60.0, 3.0)

		# check for stopped status of Material Request
		se = frappe.copy_doc(se_doc)
		se.set_stock_entry_type()
		se.insert()
		mr.update_status("Stopped")
		self.assertRaises(frappe.InvalidStatusError, se.submit)
		self.assertRaises(frappe.InvalidStatusError, se.cancel)

		mr.update_status("Submitted")
		se = frappe.copy_doc(se_doc)
		se.set_stock_entry_type()
		se.insert()
		se.submit()

		# check if per complete is as expected
		mr.load_from_db()

		self.assertEqual(mr.per_ordered, 100)
		self.assertEqual(mr.get("items")[0].ordered_qty, 54.0)
		self.assertEqual(mr.get("items")[1].ordered_qty, 3.0)

		current_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		current_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		self.assertEqual(current_requested_qty_item1, existing_requested_qty_item1)
		self.assertEqual(current_requested_qty_item2, existing_requested_qty_item2)

		# check if per complete is as expected for Stock Entry cancelled
		se.cancel()
		mr.load_from_db()
		self.assertEqual(mr.per_ordered, 0)
		self.assertEqual(mr.get("items")[0].ordered_qty, 0)
		self.assertEqual(mr.get("items")[1].ordered_qty, 0)

		current_requested_qty_item1 = self._get_requested_qty(
			"_Test Item Home Desktop 100", "_Test Warehouse - _TC"
		)
		current_requested_qty_item2 = self._get_requested_qty(
			"_Test Item Home Desktop 200", "_Test Warehouse - _TC"
		)

		self.assertEqual(current_requested_qty_item1, existing_requested_qty_item1 + 54.0)
		self.assertEqual(current_requested_qty_item2, existing_requested_qty_item2 + 3.0)

	def test_incorrect_mapping_of_stock_entry(self):
		# submit material request of type Transfer
		mr = frappe.copy_doc(test_records[0])
		mr.material_request_type = "Material Transfer"
		mr.insert()
		mr.submit()

		se_doc = make_stock_entry(mr.name)
		se_doc.update(
			{
				"posting_date": "2013-03-01",
				"posting_time": "00:00",
				"fiscal_year": "_Test Fiscal Year 2013",
			}
		)
		se_doc.get("items")[0].update(
			{
				"qty": 60.0,
				"transfer_qty": 60.0,
				"s_warehouse": "_Test Warehouse - _TC",
				"t_warehouse": "_Test Warehouse 1 - _TC",
				"basic_rate": 1.0,
			}
		)
		se_doc.get("items")[1].update(
			{
				"item_code": "_Test Item Home Desktop 100",
				"qty": 3.0,
				"transfer_qty": 3.0,
				"s_warehouse": "_Test Warehouse 1 - _TC",
				"basic_rate": 1.0,
			}
		)

		# check for stopped status of Material Request
		se = frappe.copy_doc(se_doc)
		self.assertRaises(frappe.MappingMismatchError, se.insert)

		# submit material request of type Transfer
		mr = frappe.copy_doc(test_records[0])
		mr.material_request_type = "Material Issue"
		mr.insert()
		mr.submit()

		se_doc = make_stock_entry(mr.name)
		self.assertEqual(se_doc.get("items")[0].s_warehouse, "_Test Warehouse - _TC")

	def test_warehouse_company_validation(self):
		from erpnext.stock.utils import InvalidWarehouseCompany

		mr = frappe.copy_doc(test_records[0])
		mr.company = "_Test Company 1"
		self.assertRaises(InvalidWarehouseCompany, mr.insert)

	def _get_requested_qty(self, item_code, warehouse):
		return flt(
			frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "indented_qty")
		)

	def test_make_stock_entry_for_material_issue(self):
		mr = frappe.copy_doc(test_records[0]).insert()

		self.assertRaises(frappe.ValidationError, make_stock_entry, mr.name)

		mr = frappe.get_doc("Material Request", mr.name)
		mr.material_request_type = "Material Issue"
		mr.submit()
		se = make_stock_entry(mr.name)

		self.assertEqual(se.doctype, "Stock Entry")
		self.assertEqual(len(se.get("items")), len(mr.get("items")))

	def test_completed_qty_for_issue(self):
		def _get_requested_qty():
			return flt(
				frappe.db.get_value(
					"Bin",
					{"item_code": "_Test Item Home Desktop 100", "warehouse": "_Test Warehouse - _TC"},
					"indented_qty",
				)
			)

		existing_requested_qty = _get_requested_qty()

		mr = frappe.copy_doc(test_records[0])
		mr.material_request_type = "Material Issue"
		mr.submit()
		frappe.db.value_cache = {}

		# testing bin value after material request is submitted
		self.assertEqual(_get_requested_qty(), existing_requested_qty - 54.0)

		# receive items to allow issue
		self._insert_stock_entry(60, 6, "_Test Warehouse - _TC")

		# make stock entry against MR

		se_doc = make_stock_entry(mr.name)
		se_doc.fiscal_year = "_Test Fiscal Year 2014"
		se_doc.get("items")[0].qty = 54.0
		se_doc.insert()
		se_doc.submit()

		# check if per complete is as expected
		mr.load_from_db()
		self.assertEqual(mr.get("items")[0].ordered_qty, 54.0)
		self.assertEqual(mr.get("items")[1].ordered_qty, 3.0)

		# testing bin requested qty after issuing stock against material request
		self.assertEqual(_get_requested_qty(), existing_requested_qty)

	def test_material_request_type_manufacture(self):
		mr = frappe.copy_doc(test_records[1]).insert()
		mr = frappe.get_doc("Material Request", mr.name)
		mr.submit()
		completed_qty = mr.items[0].ordered_qty
		requested_qty = frappe.db.sql(
			"""select indented_qty from `tabBin` where \
			item_code= %s and warehouse= %s """,
			(mr.items[0].item_code, mr.items[0].warehouse),
		)[0][0]

		prod_order = raise_work_orders(mr.name)
		po = frappe.get_doc("Work Order", prod_order[0])
		po.wip_warehouse = "_Test Warehouse 1 - _TC"
		po.submit()

		mr = frappe.get_doc("Material Request", mr.name)
		self.assertEqual(completed_qty + po.qty, mr.items[0].ordered_qty)

		new_requested_qty = frappe.db.sql(
			"""select indented_qty from `tabBin` where \
			item_code= %s and warehouse= %s """,
			(mr.items[0].item_code, mr.items[0].warehouse),
		)[0][0]

		self.assertEqual(requested_qty - po.qty, new_requested_qty)

		po.cancel()

		mr = frappe.get_doc("Material Request", mr.name)
		self.assertEqual(completed_qty, mr.items[0].ordered_qty)

		new_requested_qty = frappe.db.sql(
			"""select indented_qty from `tabBin` where \
			item_code= %s and warehouse= %s """,
			(mr.items[0].item_code, mr.items[0].warehouse),
		)[0][0]
		self.assertEqual(requested_qty, new_requested_qty)

	def test_requested_qty_multi_uom(self):
		existing_requested_qty = self._get_requested_qty("_Test FG Item", "_Test Warehouse - _TC")

		mr = make_material_request(
			item_code="_Test FG Item",
			material_request_type="Manufacture",
			uom="_Test UOM 1",
			conversion_factor=12,
		)

		requested_qty = self._get_requested_qty("_Test FG Item", "_Test Warehouse - _TC")

		self.assertEqual(requested_qty, existing_requested_qty + 120)

		work_order = raise_work_orders(mr.name)
		wo = frappe.get_doc("Work Order", work_order[0])
		wo.qty = 50
		wo.wip_warehouse = "_Test Warehouse 1 - _TC"
		wo.submit()

		requested_qty = self._get_requested_qty("_Test FG Item", "_Test Warehouse - _TC")
		self.assertEqual(requested_qty, existing_requested_qty + 70)

		wo.cancel()

		requested_qty = self._get_requested_qty("_Test FG Item", "_Test Warehouse - _TC")
		self.assertEqual(requested_qty, existing_requested_qty + 120)

		mr.reload()
		mr.cancel()
		requested_qty = self._get_requested_qty("_Test FG Item", "_Test Warehouse - _TC")
		self.assertEqual(requested_qty, existing_requested_qty)

	def test_multi_uom_for_purchase(self):
		mr = frappe.copy_doc(test_records[0])
		mr.material_request_type = "Purchase"
		item = mr.items[0]
		mr.schedule_date = today()

		if not frappe.db.get_value("UOM Conversion Detail", {"parent": item.item_code, "uom": "Kg"}):
			item_doc = frappe.get_doc("Item", item.item_code)
			item_doc.append("uoms", {"uom": "Kg", "conversion_factor": 5})
			item_doc.save(ignore_permissions=True)

		item.uom = "Kg"
		for item in mr.items:
			item.schedule_date = mr.schedule_date

		mr.insert()
		self.assertRaises(frappe.ValidationError, make_purchase_order, mr.name)

		mr = frappe.get_doc("Material Request", mr.name)
		mr.submit()
		item = mr.items[0]

		self.assertEqual(item.uom, "Kg")
		self.assertEqual(item.conversion_factor, 5.0)
		self.assertEqual(item.stock_qty, flt(item.qty * 5))

		po = make_purchase_order(mr.name)
		self.assertEqual(po.doctype, "Purchase Order")
		self.assertEqual(len(po.get("items")), len(mr.get("items")))

		po.supplier = "_Test Supplier"
		po.insert()
		po.submit()
		mr = frappe.get_doc("Material Request", mr.name)
		self.assertEqual(mr.per_ordered, 100)

	def test_customer_provided_parts_mr(self):
		create_item("CUST-0987", is_customer_provided_item=1, customer="_Test Customer", is_purchase_item=0)
		existing_requested_qty = self._get_requested_qty("_Test Customer", "_Test Warehouse - _TC")

		mr = make_material_request(item_code="CUST-0987", material_request_type="Customer Provided")
		se = make_stock_entry(mr.name)
		se.insert()
		se.submit()
		self.assertEqual(se.get("items")[0].amount, 0)
		self.assertEqual(se.get("items")[0].material_request, mr.name)
		mr = frappe.get_doc("Material Request", mr.name)
		mr.submit()
		current_requested_qty = self._get_requested_qty("_Test Customer", "_Test Warehouse - _TC")

		self.assertEqual(mr.per_ordered, 100)
		self.assertEqual(existing_requested_qty, current_requested_qty)

	def test_auto_email_users_with_company_user_permissions(self):
		from erpnext.stock.reorder_item import get_email_list

		comapnywise_users = {
			"_Test Company": "test_auto_email_@example.com",
			"_Test Company 1": "test_auto_email_1@example.com",
		}

		permissions = []

		for company, user in comapnywise_users.items():
			if not frappe.db.exists("User", user):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": user,
						"first_name": user,
						"send_notifications": 0,
						"enabled": 1,
						"user_type": "System User",
						"roles": [{"role": "Purchase Manager"}],
					}
				).insert(ignore_permissions=True)

			if not frappe.db.exists(
				"User Permission", {"user": user, "allow": "Company", "for_value": company}
			):
				perm_doc = frappe.get_doc(
					{
						"doctype": "User Permission",
						"user": user,
						"allow": "Company",
						"for_value": company,
						"apply_to_all_doctypes": 1,
					}
				).insert(ignore_permissions=True)

				permissions.append(perm_doc)

		comapnywise_mr_list = frappe._dict({})
		mr1 = make_material_request()
		comapnywise_mr_list.setdefault(mr1.company, []).append(mr1.name)

		mr2 = make_material_request(
			company="_Test Company 1", warehouse="Stores - _TC1", cost_center="Main - _TC1"
		)
		comapnywise_mr_list.setdefault(mr2.company, []).append(mr2.name)

		for company, _mr_list in comapnywise_mr_list.items():
			emails = get_email_list(company)

			self.assertTrue(comapnywise_users[company] in emails)

		for perm in permissions:
			perm.delete()

	@change_settings("Stock Settings",{"allow_negative_stock": 1})
	def test_material_request_transfer_to_stock_entry(self):
		item = create_item("OP-MB-001")
		mr = frappe.new_doc("Material Request")
		mr.company = "_Test Company"
		mr.scheduled_date = today()
		from_warehouse = create_warehouse("Source Warehouse", properties=None, company=mr.company)
		target_warehouse = create_warehouse("Target Warehouse", properties=None, company=mr.company)
		mr.append(
			"items",
			{
				"item_code": item.item_code,
				"item_name": item.name,
				"qty": 10,
				"rate": 120,
				"schedule_date": today(),
				"uom": "Nos",
				"from_warehouse": from_warehouse,
				"warehouse": target_warehouse,
			},
		)
		mr.material_request_type = "Material Transfer"
		mr.insert()
		mr.submit()
		self.assertEqual(mr.status, "Pending")

		se = make_stock_entry(mr.name)
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Transferred")
		
		from_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':from_warehouse},['qty_after_transaction'])
		target_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':target_warehouse},['qty_after_transaction'])
		self.assertEqual(from_warehouse_qty, -10)
		self.assertEqual(target_warehouse_qty, 10)

	@change_settings("Stock Settings",{"allow_negative_stock": 1})
	def test_material_request_issue_to_stock_entry(self):
		item = create_item("OP-MB-001")
		mr = frappe.new_doc("Material Request")
		mr.company = "_Test Company"
		mr.scheduled_date = today()
		target_warehouse = create_warehouse("Target Warehouse", properties=None, company=mr.company)
		mr.append(
			"items",
			{
				"item_code": item.item_code,
				"item_name": item.name,
				"qty": 5,
				"schedule_date": today(),
				"uom": "Nos",
				"warehouse": target_warehouse,
			},
		)
		mr.material_request_type = "Material Issue"
		mr.insert()
		mr.submit()
		self.assertEqual(mr.status, "Pending")

		se = make_stock_entry(mr.name)
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Issued")
		
		warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name},['qty_after_transaction'])
		self.assertEqual(warehouse_qty, -5)
		
	@change_settings("Stock Settings",{"allow_negative_stock": 1})
	def test_material_request_transfer_to_stock_entry_partial(self):
		item = create_item("OP-MB-001")
		mr = frappe.new_doc("Material Request")
		mr.company = "_Test Company"
		mr.scheduled_date = today()
		from_warehouse = create_warehouse("Source Warehouse", properties=None, company=mr.company)
		target_warehouse = create_warehouse("Target Warehouse", properties=None, company=mr.company)
		mr.append(
			"items",
			{
				"item_code": item.item_code,
				"item_name": item.name,
				"qty": 10,
				"rate": 120,
				"schedule_date": today(),
				"uom": "Nos",
				"from_warehouse": from_warehouse,
				"warehouse": target_warehouse,
			},
		)
		mr.material_request_type = "Material Transfer"
		mr.insert()
		mr.submit()
		self.assertEqual(mr.status, "Pending")

		se = make_stock_entry(mr.name)
		se.get("items")[0].update({"qty": 5.0})
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Partially Received")

		from_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':from_warehouse},['qty_after_transaction'])
		target_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':target_warehouse},['qty_after_transaction'])
		self.assertEqual(from_warehouse_qty, -5.0)
		self.assertEqual(target_warehouse_qty, 5.0)

		se = make_stock_entry(mr.name)
		se.get("items")[0].update({"qty": 5.0})
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Transferred")
		
		from_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':from_warehouse},['qty_after_transaction'])
		target_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':target_warehouse},['qty_after_transaction'])
		self.assertEqual(from_warehouse_qty, -10)
		self.assertEqual(target_warehouse_qty, 10)

	@change_settings("Stock Settings",{"allow_negative_stock": 1})
	def test_material_request_issue_to_stock_entry_partial(self):
		item = create_item("OP-MB-001")
		mr = frappe.new_doc("Material Request")
		mr.company = "_Test Company"
		mr.scheduled_date = today()
		target_warehouse = create_warehouse("Target Warehouse", properties=None, company=mr.company)
		mr.append(
			"items",
			{
				"item_code": item.item_code,
				"item_name": item.name,
				"qty": 10,
				"rate": 120,
				"schedule_date": today(),
				"uom": "Nos",
				"warehouse": target_warehouse,
			},
		)
		mr.material_request_type = "Material Issue"
		mr.insert()
		mr.submit()
		self.assertEqual(mr.status, "Pending")

		se = make_stock_entry(mr.name)
		se.get("items")[0].update({"qty": 5.0})
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Partially Ordered")

		target_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':target_warehouse},['qty_after_transaction'])
		self.assertEqual(target_warehouse_qty, -5.0)

		se = make_stock_entry(mr.name)
		se.get("items")[0].update({"qty": 5.0})
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Issued")
		
		target_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':target_warehouse},['qty_after_transaction'])
		self.assertEqual(target_warehouse_qty, -10)

	@change_settings("Stock Settings",{"allow_negative_stock": 1})
	def test_make_material_req_to_pick_list_to_stock_entry(self):
		item = create_item("OP-MB-001")
		mr = frappe.new_doc("Material Request")
		mr.company = "_Test Company"
		mr.scheduled_date = today()
		from_warehouse = create_warehouse("Source Warehouse", properties=None, company=mr.company)
		target_warehouse = create_warehouse("Target Warehouse", properties=None, company=mr.company)
		mr.append(
			"items",
			{
				"item_code": item.item_code,
				"item_name": item.name,
				"qty": 10,
				"rate": 120,
				"schedule_date": today(),
				"uom": "Nos",
				"from_warehouse": from_warehouse,
				"warehouse": target_warehouse,
			},
		)
		mr.material_request_type = "Material Transfer"
		mr.insert()
		mr.submit()
		self.assertEqual(mr.status, "Pending")

		pl = frappe.new_doc("Pick List")
		pl.purpose = "Material Transfer"
		pl.material_request = mr.name
		pl.company = mr.company
		pl.ignore_pricing_rule = 1
		pl.warehouse = from_warehouse
		pl.append("locations", {
			"item_code": item.item_code,
			"item_name": item.name,
			"qty": 10,
			"uom": "Nos",
			"warehouse": from_warehouse,
			"stock_qty": 10,
			"stock_reserved_qty": 10,
			"conversion_factor": 1,
			"stock_uom": "Nos",
			"use_serial_batch_fields":1,
			"material_request": mr.name,
			"material_request_item": mr.get("items")[0].name,
			"picked_qty": 0,
			"allow_zero_valuation_rate" : 1,
		})
		pl.submit()

		import json
		# Set valutaion rate of temporary test item 
		frappe.db.set_value("Item",item.name,"valuation_rate",10)
		se_data = pl_stock_entry(json.dumps(pl.as_dict()))
		se = frappe.get_doc(se_data)
		se.company = mr.company
		se.save()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Transferred")
		
		from_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':se.get("items")[0].s_warehouse},['qty_after_transaction'])
		target_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':se.get("items")[0].t_warehouse},['qty_after_transaction'])
		self.assertEqual(from_warehouse_qty, -10)
		self.assertEqual(target_warehouse_qty, 10)

	def test_create_material_req_to_po_to_pr(self):
		mr = make_material_request()

		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 10)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_create_material_req_to_2po_to_2pr(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_po_to_2pr(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.get("items")[0].qty = 5
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		debit_act = frappe.db.get_value("Company",pr.company,"stock_received_but_not_billed")
		if debit_act:
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': debit_act},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
		self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.get("items")[0].qty = 5
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		debit_act = frappe.db.get_value("Company",pr.company,"stock_received_but_not_billed")
		if debit_act:
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': debit_act},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
		self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_1pr(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = make_purchase_receipt(po.name)
		pr = make_purchase_receipt(po1.name, target_doc=pr)
		pr.submit()
		
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_create_material_req_to_po_to_pr_return(self):
		mr = make_material_request()

		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 10)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

		pr.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pr = make_return_doc("Purchase Receipt", pr.name)
		return_pr.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 1000)
	
	def test_mr_pi_TC_B_002(self):
		# MR =>  PO => PR => PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 6,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pr = make_test_pr(doc_po.name)
		doc_pi = make_test_pi(doc_pr.name)

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")
		
	def test_mr_pi_TC_B_009(self):
		# MR =>  PO => PR => 2PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 6,
				"rate" : 100,
			},
		]
		pi_recevied_qty_list = [4, 2]
		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pr = make_test_pr(doc_po.name)

		for received_qty in pi_recevied_qty_list:
			doc_pi = make_test_pi(doc_pr.name, received_qty)

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_pi_TC_B_010(self):
		# MR =>  PO => 2PR => 2PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 6,
				"rate" : 100,
			},
		]
		pr_recevied_qty_list = [4, 2]
		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)

		for received_qty in pr_recevied_qty_list:
			doc_pr = make_test_pr(doc_po.name, received_qty)
			doc_pi = make_test_pi(doc_pr.name)

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_pi_TC_B_011(self):
		# MR =>  2PO => 2PR => 2PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 6,
				"rate" : 100,
			},
		]
		po_recevied_qty_list = [4, 2]
		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		for received_qty in po_recevied_qty_list:
			doc_po = make_test_po(doc_mr.name, received_qty = received_qty)
			doc_pr = make_test_pr(doc_po.name)
			doc_pi = make_test_pi(doc_pr.name)

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_pi_TC_B_013(self):
		# 2MR =>  2PO => 1PR => 1PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 4,
				"rate" : 100,
			},
			{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
			}
		]
		po_name_list = []
		for mr_dict in mr_dict_list:
			doc_mr = make_material_request(**mr_dict)
			self.assertEqual(doc_mr.docstatus, 1)
			doc_po = make_test_po(doc_mr.name)
			po_name_list.append(doc_po.name)
		
		pr_item_dict = {
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
				"purchase_order" : po_name_list[1]

			}

		doc_pr = make_test_pr(po_name_list[0], item_dict=pr_item_dict)
		doc_pi = make_test_pi(doc_pr.name)

		self.assertEqual(doc_pi.docstatus, 1)

	def test_mr_pi_TC_B_012(self):
		# 2MR =>  1PO => 1PR => 1PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 4,
				"rate" : 100,
			},
			{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
			}
		]
		mr_name_list = []
		for mr_dict in mr_dict_list:
			doc_mr = make_material_request(**mr_dict)
			self.assertEqual(doc_mr.docstatus, 1)
			mr_name_list.append(doc_mr.name)


		po_item_dict = {
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
				"purchase_order" : mr_name_list[1]

		}

		doc_po = make_test_po(mr_name_list[0], item_dict=po_item_dict)
		
		doc_pr = make_test_pr(doc_po.name)
		doc_pi = make_test_pi(doc_pr.name)

		self.assertEqual(doc_pi.docstatus, 1)

	def test_mr_pi_TC_B_014(self):
		# 2MR =>  2PO => 2PR => 1PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 4,
				"rate" : 100,
			},
			{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
			}
		]
		pr_name_list = []
		for mr_dict in mr_dict_list:
			doc_mr = make_material_request(**mr_dict)
			self.assertEqual(doc_mr.docstatus, 1)
			
			doc_po = make_test_po(doc_mr.name)
			doc_pr = make_test_pr(doc_po.name)
			pr_name_list.append(doc_pr.name)

		pr_item_dict = {
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
				"purchase_receipt" : pr_name_list[1]

		}
		doc_pi = make_test_pi(pr_name_list[0], item_dict = pr_item_dict)

		self.assertEqual(doc_pi.docstatus, 1)

	def test_mr_pi_TC_B_015(self):
		# MR => RFQ => SQ => PO => 1PR => 2PI

		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
			}
		]
		pi_received_qty = [1, 1]
		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)
		
		doc_po = make_test_po(doc_mr.name)
		doc_pr = make_test_pr(doc_po.name)

		for received_qty in pi_received_qty :
			doc_pi = make_test_pi(doc_pr.name, received_qty= received_qty)

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, 'Received')

	def test_mr_pi_TC_B_003(self):
		# MR => RFQ => SQ => PO => PR => PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**args['mr'][0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_rfq = make_test_rfq(doc_mr.name)
		doc_sq= make_test_sq(doc_rfq.name, 100)
		doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')
		doc_pr = make_test_pr(doc_po.name)
		doc_pi = make_test_pi(doc_pr.name)

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_to_partial_pi_TC_B_016(self):
		# MR => RFQ => SQ => PO => PR => 2PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
			},
		]

		args['pr'] = []
		args['pi'] = [1, 1]
		total_pi_qty = 0 

		doc_mr = make_material_request(**args['mr'][0])
		doc_rfq = make_test_rfq(doc_mr.name)
		doc_sq= make_test_sq(doc_rfq.name, 100)
		doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')

		doc_pr = make_test_pr(doc_po.name)
		for pi_received_qty in args['pi']:
			doc_pi = make_test_pi(doc_pr.name, received_qty = pi_received_qty)
			total_pi_qty += doc_pi.items[0].qty

		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_to_partial_pr_TC_B_017(self):
		# MR => RFQ => SQ => PO => 2PR => 2PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 2,
				"rate" : 100,
			},
		]

		args['pr'] = [1, 1]
		args['pi'] = []
		total_pi_qty = 0 

		doc_mr = make_material_request(**args['mr'][0])
		doc_rfq = make_test_rfq(doc_mr.name)
		doc_sq= make_test_sq(doc_rfq.name, 100)
		doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')
		for pr_received_qty in args['pr']:
			doc_pr = make_test_pr(doc_po.name, received_qty=pr_received_qty)
			doc_pi = make_test_pi(doc_pr.name)
			total_pi_qty += doc_pi.items[0].qty

		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_to_partial_pr_TC_B_018(self):
		# MR => RFQ => 2SQ => 2PO => 2PR => 2PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 20,
				"rate" : 100,
			},
		]

		args['sq'] = [10, 10]
		total_pi_qty = 0 

		doc_mr = make_material_request(**args['mr'][0])
		doc_rfq = make_test_rfq(doc_mr.name)
		
		for sq_received_qty in args['sq']:
			doc_sq= make_test_sq(doc_rfq.name, 100, received_qty=sq_received_qty)
			doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')
		
			doc_pr = make_test_pr(doc_po.name)
			doc_pi = make_test_pi(doc_pr.name)
			total_pi_qty += doc_pi.items[0].qty

		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_to_partial_pr_TC_B_019(self):
		# MR => 2RFQ => 2SQ => 2PO => 2PR => 2PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 20,
				"rate" : 100,
			},
		]

		args['rfq'] = [10, 10]
		total_pi_qty = 0 

		doc_mr = make_material_request(**args['mr'][0])
		for sq_received_qty in args['rfq']:
			doc_rfq = make_test_rfq(doc_mr.name, received_qty=sq_received_qty)
		
			doc_sq= make_test_sq(doc_rfq.name, 100)
			doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')
		
			doc_pr = make_test_pr(doc_po.name)
			doc_pi = make_test_pi(doc_pr.name)
			total_pi_qty += doc_pi.items[0].qty

		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_to_partial_pi_TC_B_020(self):
		# MR => 2RFQ => 1SQ => 2PO => 2PR => 2PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 20,
				"rate" : 100,
			},
		]

		args['rfq'] = [10, 10]
		total_pi_qty = 0 
		rfq_name_list = []
		po_received_qty = [10, 10]

		doc_mr = make_material_request(**args['mr'][0])
		for sq_received_qty in args['rfq']:
			doc_rfq = make_test_rfq(doc_mr.name, received_qty=sq_received_qty)
			rfq_name_list.append(doc_rfq.name)

		item_dict_sq = {
			"item_code" : "Testing-31",
			"qty" : 20,
			"rate" : 200,
			"request_for_quotation" : rfq_name_list[1]
		}
		doc_sq= make_test_sq(rfq_name_list[0], 100, item_dict = item_dict_sq)

		for received_qty in po_received_qty:
			doc_po = make_test_po(doc_sq.name, type='Supplier Quotation', received_qty=received_qty)
			doc_pr = make_test_pr(doc_po.name, received_qty=received_qty)
			doc_pi = make_test_pi(doc_pr.name)
			total_pi_qty += doc_pi.items[0].qty

		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_to_partial_pi_TC_B_021(self):
		# MR => 2RFQ => 2SQ => 1PO => 2PR => 2PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 20,
				"rate" : 100,
			},
		]

		args['rfq'] = [10, 10]
		total_pi_qty = 0 
		sq_name_list = []
		pr_received_qty = [10, 10]

		doc_mr = make_material_request(**args['mr'][0])
		for sq_received_qty in args['rfq']:
			doc_rfq = make_test_rfq(doc_mr.name, received_qty=sq_received_qty)
			doc_sq= make_test_sq(doc_rfq.name, 100)
			sq_name_list.append(doc_sq.name)


		item_dict_sq = {
			"item_code" : "Testing-31",
			"qty" : 10,
			"rate" : 100,
			"supplier_quotation" : sq_name_list[1],
			"material_request": doc_mr.name
		}

		doc_po = make_test_po(sq_name_list[0], type='Supplier Quotation', item_dict=item_dict_sq)

		
		index = 0
		while index < len(pr_received_qty):
			item_dict_pr = {
				"item_code" : "Testing-31",
				"qty" : pr_received_qty[index],
				"rate" : 100,
				"purchase_order" : doc_po.name,
				"material_request": doc_mr.name
			}
			doc_pr = make_test_pr(doc_po.name,  item_dict=item_dict_pr, remove_items = True)
			doc_pi = make_test_pi(doc_pr.name)
			total_pi_qty += doc_pi.total_qty
			
			index+=1


		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)

	def test_mr_to_partial_pi_TC_B_022(self):
		# MR => 2RFQ => 2SQ => 2PO => 1PR => 1PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 20,
				"rate" : 100,
			},
		]

		args['rfq'] = [10, 10]
		total_pi_qty = 0 
		po_name_list = []

		doc_mr = make_material_request(**args['mr'][0])
		for sq_received_qty in args['rfq']:
			doc_rfq = make_test_rfq(doc_mr.name, received_qty=sq_received_qty)
			doc_sq= make_test_sq(doc_rfq.name, 100)
			doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')
			self.assertEqual(doc_po.docstatus, 1)
			po_name_list.append(doc_po.name)
			total_pi_qty += doc_po.total_qty

		item_dict_po = {
			"item_code" : "Testing-31",
			"qty" : 10,
			"rate" : 100,
			"purchase_order" : po_name_list[1],
			"material_request": doc_mr.name,
		}
		doc_pr = make_test_pr(po_name_list[0],  item_dict=item_dict_po)
		doc_pi = make_test_pi(doc_pr.name)

		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)

	def test_mr_to_partial_pi_TC_B_026(self):
		# 2MR => 2RFQ => 2SQ => 1PO => 1PR => 1PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
			{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			}
		]

		sq_name_list = []
		total_mr_qty = 0
		for mr_dict in args['mr']:
			doc_mr = make_material_request(**mr_dict)
			doc_rfq = make_test_rfq(doc_mr.name)
			self.assertEqual(doc_mr.docstatus, 1)
			total_mr_qty += doc_mr.items[0].qty
			
			doc_sq= make_test_sq(doc_rfq.name, 100)
			self.assertEqual(doc_sq.docstatus, 1)
			sq_name_list.append(doc_sq.name)
		
		item_dict = {
			"item_code" : "Testing-31",
			"warehouse" : "Stores - _TC",
			"qty" : 10,
			"rate" : 100,
			"supplier_quotation" : sq_name_list[1]
		}
		doc_po = make_test_po(sq_name_list[0], type='Supplier Quotation', item_dict=item_dict)
		doc_pr = make_test_pr(doc_po.name)
		doc_pi = make_test_pi(doc_pr.name)
		
		self.assertEqual(doc_pi.docstatus, 1)


	def test_create_material_req_to_2po_to_2pr_return_TC_SCK_031(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr1 = make_purchase_receipt(po1.name)
		pr1.insert()
		pr1.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)
			
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pr = make_return_doc("Purchase Receipt", pr.name)
		return_pr.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		return_pr1 = make_return_doc("Purchase Receipt", pr1.name)
		return_pr1.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr1.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_po_to_2pr_return_TC_SCK_032(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.get("items")[0].qty = 5
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
		self.assertEqual(gl_temp_credit, 500)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
		self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr1 = make_purchase_receipt(po.name)
		pr1.get("items")[0].qty = 5
		pr1.insert()
		pr1.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
		self.assertEqual(gl_temp_credit, 500)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock In Hand - _TC'},'debit')
		self.assertEqual(gl_stock_debit, 500)

		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pr = make_return_doc("Purchase Receipt", pr.name)
		return_pr.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		return_pr1 = make_return_doc("Purchase Receipt", pr1.name)
		return_pr1.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr1.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_1pr_return_TC_SCK_033(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = make_purchase_receipt(po.name)
		pr = make_purchase_receipt(po1.name, target_doc=pr)
		pr.submit()
		
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pr = make_return_doc("Purchase Receipt", pr.name)
		return_pr.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_create_material_issue_and_check_status_and_TC_SCK_047(self):
		company = "_Test Company"
		qty = 10
		target_warehouse = create_warehouse("_Test Warehouse", properties=None, company=company)
		
		mr = make_material_request(material_request_type="Material Issue", qty=qty, warehouse=target_warehouse, item_code="_Test Item")
		self.assertEqual(mr.status, "Pending")
		
		frappe.db.set_value("Company", company,"enable_perpetual_inventory", 1)
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": target_warehouse}, "actual_qty") or 0
		stock_in_hand_account = get_inventory_account(company, target_warehouse)

		# Make stock entry against material request issue
		se = make_stock_entry(mr.name)
		se.items[0].expense_account = "Cost of Goods Sold - _TC"
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Issued")

		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no': se.name})
		stock_value_diff = abs(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_type": "Stock Entry", "voucher_no": se.name},
				"stock_value_difference",
			)
		)
		gle = get_gle(company, se.name, stock_in_hand_account)
		gle1 = get_gle(company, se.name, "Cost of Goods Sold - _TC")
		self.assertEqual(sle.qty_after_transaction, bin_qty-qty)
		self.assertEqual(gle[1], stock_value_diff)
		self.assertEqual(gle1[0], stock_value_diff)
		se.cancel()
		mr.load_from_db()

		# After stock entry cancel
		current_bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": target_warehouse}, "actual_qty") or 0
		sh_gle = get_gle(company, se.name, stock_in_hand_account)
		cogs_gle = get_gle(company, se.name, "Cost of Goods Sold - _TC")
		
		self.assertEqual(sh_gle[0], sh_gle[1])
		self.assertEqual(cogs_gle[0], cogs_gle[1])
		self.assertEqual(current_bin_qty, bin_qty)
	
	def test_create_material_req_issue_to_2stock_entry_and_TC_SCK_049(self):
		from erpnext.stock.doctype.stock_entry.test_stock_entry import TestStockEntry as tse

		company = "_Test Company"
		target_warehouse = create_warehouse("_Test Warehouse", properties=None, company=company)
		mr = make_material_request(material_request_type="Material Issue", qty=10, warehouse=target_warehouse, item_code="_Test Item")
		self.assertEqual(mr.status, "Pending")
		
		frappe.db.set_value("Company", company,"enable_perpetual_inventory", 1)
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": target_warehouse}, "actual_qty") or 0
		stock_in_hand_account = get_inventory_account(company, target_warehouse)

		# Make two stock entry against material request issue
		se = make_stock_entry(mr.name)
		se.items[0].qty = 5
		se.items[0].expense_account = "Cost of Goods Sold - _TC"
		se.insert()
		se.submit()
		mr.load_from_db()
		sh_gle = get_gle(company, se.name, stock_in_hand_account)
		cogs_gle = get_gle(company, se.name, "Cost of Goods Sold - _TC")
		tse.check_stock_ledger_entries(self, "Stock Entry", se.name, [["_Test Item", target_warehouse, -5]])
		stock_value_diff = abs(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_type": "Stock Entry", "voucher_no": se.name},
				"stock_value_difference",
			)
		)
		self.assertEqual(mr.status, "Partially Ordered")
		self.assertEqual(sh_gle[1], stock_value_diff)
		self.assertEqual(cogs_gle[0], stock_value_diff)

		se1 = make_stock_entry(mr.name)
		se1.items[0].qty = 5
		se1.items[0].expense_account = "Cost of Goods Sold - _TC"
		se1.insert()
		se1.submit()
		mr.load_from_db()
		sh_gle1 = get_gle(company, se1.name, stock_in_hand_account)
		cogs_gle1 = get_gle(company, se1.name, "Cost of Goods Sold - _TC")
		tse.check_stock_ledger_entries(self, "Stock Entry", se1.name, [["_Test Item", target_warehouse, -5]])
		stock_value_diff1 = abs(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_type": "Stock Entry", "voucher_no": se1.name},
				"stock_value_difference",
			)
		)
		self.assertEqual(mr.status, "Issued")
		self.assertEqual(sh_gle1[1], stock_value_diff1)
		self.assertEqual(cogs_gle1[0], stock_value_diff1)

		# After stock entry cancel
		se.cancel()
		mr.load_from_db()
		sh_gle = get_gle(company, se.name, stock_in_hand_account)
		cogs_gle = get_gle(company, se.name, "Cost of Goods Sold - _TC")
		self.assertEqual(mr.status, "Partially Ordered")
		self.assertEqual(sh_gle[0], sh_gle[1])
		self.assertEqual(cogs_gle[0], cogs_gle[1])

		se1.cancel()
		mr.load_from_db()
		sh_gle1 = get_gle(company, se1.name, stock_in_hand_account)
		cogs_gle1 = get_gle(company, se1.name, "Cost of Goods Sold - _TC")
		self.assertEqual(mr.status, "Pending")
		self.assertEqual(sh_gle1[0], sh_gle1[1])
		self.assertEqual(cogs_gle1[0], cogs_gle1[1])

		current_bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": target_warehouse}, "actual_qty") or 0
		self.assertEqual(current_bin_qty, bin_qty)

	def test_material_transfer_pick_list_to_stock_and_TC_SCK_050(self):
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry as _make_stock_entry
		from erpnext.stock.doctype.stock_entry.test_stock_entry import TestStockEntry as tse
		from erpnext.stock.doctype.putaway_rule.test_putaway_rule import create_putaway_rule
		from erpnext.stock.doctype.material_request.material_request import create_pick_list

		item = create_item("OP-MB-001")
		source_warehouse = create_warehouse("_Test Source Warehouse", properties=None, company="_Test Company")
		t_warehouse = create_warehouse(warehouse_name="_Test Warehouse 1", properties=None, company="_Test Company")
		t_warehouse1 = create_warehouse(warehouse_name="_Test Warehouse 2", properties=None, company="_Test Company")
		create_putaway_rule(item_code=item.name, warehouse=t_warehouse, capacity=5, uom="Nos")
		create_putaway_rule(item_code=item.name, warehouse=t_warehouse1, capacity=5, uom="Nos")
		_make_stock_entry(
			item_code=item.name,
			qty=10,
			to_warehouse=source_warehouse,
			company="_Test Company",
			rate=120,
		)
		s_bin_qty = frappe.db.get_value("Bin", {"item_code": item.name, "warehouse": source_warehouse}, "actual_qty") or 0

		mr = make_material_request(material_request_type="Material Transfer", qty=10, warehouse=t_warehouse, from_warehouse=source_warehouse, item_code=item.name)
		self.assertEqual(mr.status, "Pending")
		pl = create_pick_list(mr.name)
		pl.save()
		pl.submit()

		se_data = pl_stock_entry(json.dumps(pl.as_dict()))
		se = frappe.get_doc(se_data)
		se.apply_putaway_rule = 1
		se.save()
		se.submit()
		tse.check_stock_ledger_entries(
			self, 
			"Stock Entry", 
			se.name, 
			[
				[item.name, t_warehouse, 5], 
				[item.name, source_warehouse, -5], 
				[item.name, t_warehouse1, 5], 
				[item.name, source_warehouse, -5]
			]
		)
		mr.load_from_db()
		self.assertEqual(mr.status, "Transferred")
		self.assertEqual(se.items[0].qty, 5)
		self.assertEqual(len(se.items), 2)

		se.cancel()
		mr.load_from_db()
		current_qty = frappe.db.get_value("Bin", {"item_code": item.name, "warehouse": source_warehouse}, "actual_qty") or 0
		self.assertEqual(current_qty, s_bin_qty)
		self.assertEqual(mr.status, "Pending")

	
	def test_mr_to_partial_pi_TC_B_027(self):
		# 2MR => 2RFQ => 2SQ => 2PO => 1PR => 1PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
			{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			}
		]

		po_name_list = []
		total_mr_qty = 0
		for mr_dict in args['mr']:
			doc_mr = make_material_request(**mr_dict)
			doc_rfq = make_test_rfq(doc_mr.name)
			self.assertEqual(doc_mr.docstatus, 1)
			total_mr_qty += doc_mr.items[0].qty
			
			doc_sq= make_test_sq(doc_rfq.name, 100)
			doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')
			self.assertEqual(doc_po.docstatus, 1)
			po_name_list.append(doc_po.name)


		item_dict = {
			"item_code" : "Testing-31",
			"warehouse" : "Stores - _TC",
			"qty" : 10,
			"rate" : 100,
			"purchase_order" : po_name_list[1]
		}
		
		doc_pr = make_test_pr(po_name_list[0], item_dict=item_dict)
		doc_pi = make_test_pi(doc_pr.name)
		
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.total_qty, total_mr_qty)

	def test_mr_to_partial_pi_TC_B_028(self):
		# 2MR => 2RFQ => 2SQ => 2PO => 2PR => 1PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
			{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			}
		]

		pr_name_list = []
		total_mr_qty = 0
		for mr_dict in args['mr']:
			doc_mr = make_material_request(**mr_dict)
			doc_rfq = make_test_rfq(doc_mr.name)
			self.assertEqual(doc_mr.docstatus, 1)
			total_mr_qty += doc_mr.items[0].qty
			
			doc_sq= make_test_sq(doc_rfq.name, 100)
			doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')
			doc_pr = make_test_pr(doc_po.name)
			self.assertEqual(doc_pr.docstatus, 1)
			pr_name_list.append(doc_pr.name)


		item_dict = {
			"item_code" : "Testing-31",
			"warehouse" : "Stores - _TC",
			"qty" : 10,
			"rate" : 100,
			"purchase_receipt" : pr_name_list[1]
		}
		
		
		doc_pi = make_test_pi(pr_name_list[0], item_dict=item_dict)
		
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.total_qty, total_mr_qty)
	
	def test_mr_to_partial_pi_TC_B_029(self):
		# 1MR => 1RFQ => 1SQ => 1PO => 1PR => 2PI
		args = frappe._dict()
		args['mr'] = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 20,
				"rate" : 100,
			}
		]

		pi_received_qty = [10, 10]
		total_pi_qty = 0
		
		doc_mr = make_material_request(**args['mr'][0])
		doc_rfq = make_test_rfq(doc_mr.name)
		self.assertEqual(doc_mr.docstatus, 1)
		
		doc_sq= make_test_sq(doc_rfq.name, 100)
		doc_po = make_test_po(doc_sq.name, type='Supplier Quotation')
		doc_pr = make_test_pr(doc_po.name)
		self.assertEqual(doc_pr.docstatus, 1)
		
		for received_qty in pi_received_qty:
			doc_pi = make_test_pi(doc_pr.name, received_qty=received_qty)
			total_pi_qty += doc_pi.total_qty
			self.assertEqual(doc_pi.docstatus, 1)

		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, 'Received')

	def test_create_material_req_to_po_to_2pr_return_TC_SCK_035(self):
		#batch item
		batch_item_code = make_item(
			"Test Batch No for Validation",
			{"has_batch_no": 1, "batch_number_series": "BT-TSNFVAL-.#####", "create_new_batch": 1},
		).name
		mr = make_material_request(item_code=batch_item_code)
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": batch_item_code, "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.get("items")[0].qty = 10
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 10)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
		self.assertEqual(gl_temp_credit, 1000)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
		self.assertEqual(gl_stock_debit, 1000)

		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pr = make_return_doc("Purchase Receipt", pr.name)
		return_pr.items[0].qty = -5
		return_pr.items[0].received_qty = -5
		return_pr.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": batch_item_code, "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		return_pr1 = make_return_doc("Purchase Receipt", pr.name)
		return_pr.items[0].qty = -5
		return_pr.items[0].received_qty = -5
		return_pr1.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": batch_item_code, "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		# if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr1.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_2pr_TC_SCK_040(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr1 = make_purchase_receipt(po.name)
		pr1.insert()
		pr1.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pr = make_return_doc("Purchase Receipt", pr.name)
		return_pr.items[0].qty = -5
		return_pr.items[0].received_qty = -5
		return_pr.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		return_pr1 = make_return_doc("Purchase Receipt", pr1.name)
		return_pr1.items[0].qty = -5
		return_pr1.items[0].received_qty = -5
		return_pr1.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':return_pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		# if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pr1.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_mr_to_partial_pr_TC_B_023(self):
		# MR => 1RFQ => 2SQ => 2PO => 1PR => 1PI
		args = frappe._dict()
		args['mr'] = [{
			"company": "_Test Company",
			"item_code": "Testing-31",
			"warehouse": "Stores - _TC",
			"qty": 20,
			"rate": 100,
		}]
		args['sq'] = [10, 10]
		total_po_qty = sum(args['sq'])
		total_pi_qty = 0
		doc_mr = make_material_request(**args['mr'][0])
		doc_rfq = make_test_rfq(doc_mr.name, received_qty=args['mr'][0]["qty"])
		for sq_qty in args['sq']:
			doc_sq = make_test_sq(doc_rfq.name, rate=100, received_qty=sq_qty)
			doc_po = make_test_po(doc_sq.name, type='Supplier Quotation', received_qty=sq_qty)
		doc_pr = make_test_pr(doc_po.name, received_qty=total_po_qty)
		doc_pi = make_test_pi(doc_pr.name, received_qty=total_po_qty)
		total_pi_qty += doc_pi.items[0].qty
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_mr.items[0].qty, total_pi_qty)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

	def test_mr_to_partial_pi_TC_B_024(self):
		# 2MR => 1RFQ => 1SQ => 1PO => 1PR => 1PI
		args = frappe._dict()
		args['mr'] = [
			{
				"company": "_Test Company",
				"item_code": "Testing-31",
				"warehouse": "Stores - _TC",
				"qty": 10,
				"rate": 100,
			},
			{
				"company": "_Test Company",
				"item_code": "Testing-31",
				"warehouse": "Stores - _TC",
				"qty": 15,
				"rate": 100,
			}
		]
		total_mr_qty = 0
		rfq_name = None
		for mr_dict in args['mr']:
			doc_mr = make_material_request(**mr_dict)
			self.assertEqual(doc_mr.docstatus, 1)
			total_mr_qty += doc_mr.items[0].qty

			if not rfq_name:
					doc_rfq = make_test_rfq(doc_mr.name)
					rfq_name = doc_rfq.name

		doc_sq = make_test_sq(rfq_name, 100)
		self.assertEqual(doc_sq.docstatus, 1)
		item_dict = {
			"item_code": "Testing-31",
			"warehouse": "Stores - _TC",
			"qty": total_mr_qty,
			"rate": 100,
			"supplier_quotation": doc_sq.name
		}
		doc_po = make_test_po(doc_sq.name, type='Supplier Quotation', item_dict=item_dict)
		self.assertEqual(doc_po.docstatus, 1)

		doc_pr = make_test_pr(doc_po.name)
		self.assertEqual(doc_pr.docstatus, 1)

		doc_pi = make_test_pi(doc_pr.name)
		self.assertEqual(doc_pi.docstatus, 1)

	def test_mr_to_partial_pi_TC_B_025(self):
		# 2MR => 2RFQ => 1SQ => 1PO => 1PR => 1PI
		args = frappe._dict()
		args['mr'] = [
			{
				"company": "_Test Company",
				"item_code": "Testing-31",
				"warehouse": "Stores - _TC",
				"qty": 10,
				"rate": 100,
			},
			{
				"company": "_Test Company",
				"item_code": "Testing-31",
				"warehouse": "Stores - _TC",
				"qty": 15,
				"rate": 100,
			}
		]

		rfq_name_list = []
		total_mr_qty = 0
		for mr_dict in args['mr']:
			doc_mr = make_material_request(**mr_dict)
			self.assertEqual(doc_mr.docstatus, 1)
			total_mr_qty += doc_mr.items[0].qty

			doc_rfq = make_test_rfq(doc_mr.name)
			self.assertEqual(doc_rfq.docstatus, 1)
			rfq_name_list.append(doc_rfq.name)

		doc_sq = make_test_sq(rfq_name_list, 100)
		self.assertEqual(doc_sq.docstatus, 1)

		item_dict = {
			"item_code": "Testing-31",
			"warehouse": "Stores - _TC",
			"qty": total_mr_qty,
			"rate": 100,
			"supplier_quotation": doc_sq.name
		}
		doc_po = make_test_po(doc_sq.name, type='Supplier Quotation', item_dict=item_dict)
		self.assertEqual(doc_po.docstatus, 1)

		doc_pr = make_test_pr(doc_po.name)
		self.assertEqual(doc_pr.docstatus, 1)

		doc_pi = make_test_pi(doc_pr.name)
		self.assertEqual(doc_pi.docstatus, 1)

	def test_create_mr_to_po_to_pr_cancel_TC_SCK_055(self):
		mr = make_material_request()

		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 10)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

		#PR Cancel
		pr.cancel()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, 0)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 0)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 0)

	def test_create_material_req_to_2po_to_2pr_cancel_TC_SCK_056(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr1 = make_purchase_receipt(po.name)
		pr1.insert()
		pr1.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		#PR Cancel
		pr.cancel()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, 0)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 0)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 0)

		#PR Cancel
		pr1.cancel()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, 0)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 0)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 0)

	def test_create_material_req_to_po_to_2pr_cancel_TC_SCK_057(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		pr.get("items")[0].qty = 5
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
		self.assertEqual(gl_temp_credit, 500)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
		self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr1 = make_purchase_receipt(po.name)
		pr1.get("items")[0].qty = 5
		pr1.insert()
		pr1.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
		self.assertEqual(gl_temp_credit, 500)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock In Hand - _TC'},'debit')
		self.assertEqual(gl_stock_debit, 500)

		pr.cancel()
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, 0)

		pr1.cancel()
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, 0)

	def test_create_material_req_to_2po_to_1pr_cancel_TC_SCK_058(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = make_purchase_receipt(po.name)
		pr = make_purchase_receipt(po1.name, target_doc=pr)
		pr.submit()
		
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

		pr.cancel()
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, 0)

	def test_create_mr_issue_to_stock_entry_with_batch_and_TC_SCK_062(self):
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry as _make_stock_entry

		fields = {
			"has_batch_no": 1,
			"is_stock_item": 1,
			"create_new_batch": 1,
			"batch_naming_series": "Test-SBBTYT-NNS.#####",
		}

		if frappe.db.has_column("Item", "gst_hsn_code"):
			fields["gst_hsn_code"] = "01011010"

		company = "_Test Company"
		qty = 10
		frappe.db.set_value("Company", "_Test Company", "enable_perpetual_inventory", 1)
		frappe.db.set_value("Company", "_Test Company", "stock_adjustment_account", "Stock Adjustment - _TC")
		target_warehouse = create_warehouse("_Test Warehouse", properties=None, company=company)
		item = make_item("Test Use Serial and Batch Item SN Item", fields).name

		new_stock = _make_stock_entry(
			item_code=item,
			qty=10,
			to_warehouse=target_warehouse,
			company="_Test Company",
			rate=100,
		)
		self.assertTrue(new_stock.items[0].serial_and_batch_bundle)

		mr = make_material_request(
			material_request_type="Material Issue", qty=qty, warehouse=target_warehouse, item_code=item
		)
		self.assertEqual(mr.status, "Pending")

		bin_qty = (
			frappe.db.get_value("Bin", {"item_code": item, "warehouse": target_warehouse}, "actual_qty") or 0
		)
		stock_in_hand_account = get_inventory_account(company, target_warehouse)

		# Make stock entry against material request issue
		se = make_stock_entry(mr.name)
		se.items[0].expense_account = "Cost of Goods Sold - _TC"
		se.serial_and_batch_bundle = new_stock.items[0].serial_and_batch_bundle
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Issued")

		sle = frappe.get_doc("Stock Ledger Entry", {"voucher_no": se.name})
		stock_value_diff = abs(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"voucher_type": "Stock Entry", "voucher_no": se.name},
				"stock_value_difference",
			)
		)
		gle = get_gle(company, se.name, stock_in_hand_account)
		gle1 = get_gle(company, se.name, "Cost of Goods Sold - _TC")
		self.assertEqual(sle.qty_after_transaction, bin_qty - qty)
		self.assertEqual(gle[1], stock_value_diff)
		self.assertEqual(gle1[0], stock_value_diff)
		se.cancel()
		mr.load_from_db()

		# After stock entry cancel
		current_bin_qty = (
			frappe.db.get_value("Bin", {"item_code": item, "warehouse": target_warehouse}, "actual_qty") or 0
		)
		sh_gle = get_gle(company, se.name, stock_in_hand_account)
		cogs_gle = get_gle(company, se.name, "Cost of Goods Sold - _TC")

		self.assertEqual(sh_gle[0], sh_gle[1])
		self.assertEqual(cogs_gle[0], cogs_gle[1])
		self.assertEqual(current_bin_qty, bin_qty)

	def test_mr_transfer_to_se_cancel_TC_SCK_061(self):
		source_wh = create_warehouse(
			warehouse_name="_Test Source Warehouse",
			properties={"parent_warehouse": "All Warehouses - _TC"},
			company="_Test Company",
		)
		target_wh = create_warehouse(
			warehouse_name="_Test target Warehouse",
			properties={"parent_warehouse": "All Warehouses - _TC"},
			company="_Test Company",
		)
		mr = make_material_request(material_request_type="Material Transfer",do_not_submit=1)
		mr.items[0].from_warehouse = source_wh
		mr.items[0].warehouse = target_wh
		mr.submit()
		self.assertEqual(mr.status, "Pending")

		se = make_stock_entry(mr.name)
		se.insert()
		se.submit()
		mr.load_from_db()
		self.assertEqual(mr.status, "Transferred")

		from_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':source_wh},['qty_after_transaction'])
		target_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':target_wh},['qty_after_transaction'])
		self.assertEqual(from_warehouse_qty, -10)
		self.assertEqual(target_warehouse_qty, 10)

		se.cancel()
		from_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':source_wh},['qty_after_transaction'])
		target_warehouse_qty = frappe.db.get_value('Stock Ledger Entry',{'voucher_no':se.name, 'voucher_type':'Stock Entry','warehouse':target_wh},['qty_after_transaction'])
		self.assertEqual(from_warehouse_qty, 0)
		self.assertEqual(target_warehouse_qty, 0)

	def test_mr_po_pi_TC_SCK_082(self):
		# MR =>  PO => PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Ordered")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 1000)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_mr_po_2pi_TC_SCK_083(self):
		# MR =>  PO => 2PI
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.items[0].qty = 5
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Ordered")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.items[0].qty = 5
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Ordered")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_2pi_TC_SCK_084(self):
		mr = make_material_request()

		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr.submit()
		pr1 = create_purchase_invoice(po1.name)
		pr1.submit()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			recive_account = frappe.db.get_value("Company",mr.company,"stock_received_but_not_billed")
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 500)
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 500)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 500)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_1pi_TC_SCK_085(self):
		mr = make_material_request()

		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr = create_purchase_invoice(po1.name, target_doc=pr)
		pr.submit()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			recive_account = frappe.db.get_value("Company",mr.company,"stock_received_but_not_billed")
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 1000)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_mr_po_pi_cancel_TC_SCK_086(self):
		# MR =>  PO => PI => PI Cancel
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_pi.reload()
		doc_pi.load_from_db()
		self.assertEqual(doc_pi.status, "Unpaid")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 1000)

		doc_pi.cancel()
		doc_pi.reload()
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_mr_po_2pi_cancel_TC_SCK_087(self):
		# MR =>  PO => 2PI => 2PI cancel
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.items[0].qty = 5
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Ordered")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		doc_pi1 = create_purchase_invoice(doc_po.name)
		doc_pi1.items[0].qty = 5
		doc_pi1.submit()

		self.assertEqual(doc_pi1.docstatus, 1)
		doc_pi1.reload()
		self.assertEqual(doc_pi1.status, "Unpaid")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		#cancel PI's
		doc_pi.reload()
		doc_pi.cancel()
		doc_pi.reload()
		self.assertEqual(doc_pi.status, "Cancelled")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		doc_pi1.cancel()
		doc_pi1.reload()
		self.assertEqual(doc_pi1.status, "Cancelled")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Creditors - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_2pi_cancel_TC_SCK_088(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr.submit()
		pr1 = create_purchase_invoice(po1.name)
		pr1.submit()
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			recive_account = frappe.db.get_value("Company",mr.company,"stock_received_but_not_billed")
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 500)
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 500)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 500)

		#cancel PI's
		pr.reload()
		pr.cancel()
		pr.reload()
		self.assertEqual(pr.status, "Cancelled")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Creditors - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		pr1.reload()
		pr1.cancel()
		pr1.reload()
		self.assertEqual(pr1.status, "Cancelled")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Creditors - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)
	
	def test_create_mr_material_transfer_to_stock_entry_TC_SCK_064(self):
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry as _make_stock_entry
		from erpnext.stock.doctype.stock_entry.test_stock_entry import TestStockEntry as tse

		item = create_item("_Test Item")
		source_warehouse = create_warehouse(
			"_Test Source Warehouse", properties=None, company="_Test Company"
		)
		t_warehouse = create_warehouse(
			warehouse_name="_Test Warehouse 1", properties=None, company="_Test Company"
		)
		_make_stock_entry(
			item_code=item.name,
			qty=10,
			to_warehouse=source_warehouse,
			company="_Test Company",
			rate=120,
		)
		s_bin_qty = (
			frappe.db.get_value("Bin", {"item_code": item.name, "warehouse": source_warehouse}, "actual_qty")
			or 0
		)

		# Create Material Request for Material Transfer
		mr = make_material_request(
			material_request_type="Material Transfer",
			qty=10,
			warehouse=t_warehouse,
			from_warehouse=source_warehouse,
			item_code=item.name,
		)
		self.assertEqual(mr.status, "Pending")

		# Create Stock Entry based on Material Request
		se = make_stock_entry(mr.name)
		se.save()
		se.submit()
		tse.check_stock_ledger_entries(
			self,
			"Stock Entry",
			se.name,
			[
				[item.name, t_warehouse, 10],
				[item.name, source_warehouse, -10],
			],
		)
		mr.load_from_db()
		self.assertEqual(mr.status, "Transferred")

		# Cancel Stock Entry and check qty in source warehouse
		se.cancel()
		mr.load_from_db()
		current_qty = (
			frappe.db.get_value("Bin", {"item_code": item.name, "warehouse": source_warehouse}, "actual_qty")
			or 0
		)
		self.assertEqual(current_qty, s_bin_qty)
		self.assertEqual(mr.status, "Pending")

	def test_create_mr_for_purchase_to_po_TC_SCK_019(self):
		self.create_mr_for_puchase_to_po_to_invoice()
	
	def test_create_mr_for_purchase_to_po_cancel_pr_TC_SCK_066(self):
		pr = self.create_mr_for_puchase_to_po_to_invoice()
		pr.cancel()

		sl_entry_cancelled = frappe.db.get_all(
			"Stock Ledger Entry",
			{"voucher_type": "Purchase Receipt", "voucher_no": pr.name},
			["actual_qty", "warehouse", "serial_and_batch_bundle"],
			order_by="creation",
		)

		warehouse_qty = {
			"_Test Warehouse - _TC": 0
		}

		for sle in sl_entry_cancelled:
			warehouse_qty[sle.get('warehouse')] += sle.get('actual_qty')
		
		self.assertEqual(warehouse_qty["_Test Warehouse - _TC"], 0)
	
	def create_mr_for_puchase_to_po_to_invoice(self):
		from erpnext.stock.doctype.stock_entry.test_stock_entry import TestStockEntry as tse

		# Create Material Request for Purchase
		fields = {
			"has_batch_no": 1,
			"has_serial_no": 1,
			"is_stock_item": 1,
			"create_new_batch": 1,
			"batch_naming_series": "Test-SABBMRP-Bno.#####",
		}

		if frappe.db.has_column("Item", "gst_hsn_code"):
			fields["gst_hsn_code"] = "01011010"

		item = make_item("Test Use Serial and Batch Item SN Item", fields).name
		mr = make_material_request(
			material_request_type="Purchase",
			qty=2,
			item_code=item,
			rate=10000
		)

		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.save()
		po.submit()

		pr = make_purchase_receipt(po.name)
		pr.items[0].use_serial_batch_fields = 1
		pr.items[0].serial_no = "Test-SABBMRP-Sno-001\nTest-SABBMRP-Sno-002"

		if not frappe.db.exists({"doctype": "Batch", "batch_id":"Test-SABBMRP-Bno-001"}):
			b_no = frappe.new_doc("Batch")
			b_no.batch_id = "Test-SABBMRP-Bno-001"
			b_no.item = item
			b_no.save()

		pr.items[0].batch_no = "Test-SABBMRP-Bno-001"
		pr.save()
		pr.submit()

		sl_entry = frappe.db.get_all(
			"Stock Ledger Entry",
			{"voucher_type": "Purchase Receipt", "voucher_no": pr.name},
			["actual_qty", "serial_and_batch_bundle"],
			order_by="creation",
		)

		sabb = frappe.get_doc("Serial and Batch Bundle", sl_entry[0].serial_and_batch_bundle)
		self.assertEqual(sl_entry[0].actual_qty, 2)
		self.assertEqual(sabb.entries[0].serial_no, "Test-SABBMRP-Sno-001")
		self.assertEqual(sabb.entries[1].serial_no, "Test-SABBMRP-Sno-002")
		self.assertEqual(sabb.entries[0].batch_no, "Test-SABBMRP-Bno-001")

		return pr

	def test_create_mr_for_purchase_to_po_2pr_TC_SCK_020(self):
		self.create_mr_for_purchase_to_po_2pr()

	def test_create_mr_for_purchase_to_po__cancel_2pr_TC_SCK_067(self):
		pr1, pr2 = self.create_mr_for_purchase_to_po_2pr()
		pr1.cancel()
		pr2.cancel()

		sl_entry_cancelled = frappe.db.get_all(
			"Stock Ledger Entry",
			{"voucher_type": "Purchase Receipt", "voucher_no": ["in",[pr1.name, pr2.name]]},
			["actual_qty", "warehouse", "serial_and_batch_bundle"],
			order_by="creation",
		)

		warehouse_qty = {
			"_Test Warehouse - _TC": 0
		}

		for sle in sl_entry_cancelled:
			warehouse_qty[sle.get('warehouse')] += sle.get('actual_qty')
		
		self.assertEqual(warehouse_qty["_Test Warehouse - _TC"], 0)
		
	def create_mr_for_purchase_to_po_2pr(self):
		fields = {
			"has_batch_no": 1,
			"has_serial_no": 1,
			"is_stock_item": 1,
			"create_new_batch": 1,
			"batch_naming_series": "Test-SABBMRP-Bno.#####",
		}

		if frappe.db.has_column("Item", "gst_hsn_code"):
			fields["gst_hsn_code"] = "01011010"

		item = make_item("Test Use Serial and Batch Item SN Item", fields).name

		# Create Material Request for Purchase
		mr = make_material_request(
			material_request_type="Purchase",
			qty=5,
			item_code=item,
			rate=10000,
			do_not_submit=True
		)
		mr.transaction_date = "01-08-2024"
		mr.schedule_date = "15-08-2024"
		mr.save()
		mr.submit()

		po = make_purchase_order(mr.name)
		po.posting_date = "05-08-2024"
		po.supplier = "_Test Supplier"
		po.save()
		po.submit()

		pr1 = make_purchase_receipt(po.name)
		pr1.posting_date = "05-08-2024"
		pr1.items[0].use_serial_batch_fields = 1
		pr1.items[0].qty = 3
		pr1.items[0].serial_no = "Test-SABBMRP-Sno-001\nTest-SABBMRP-Sno-002\nTest-SABBMRP-Sno-003"

		if not frappe.db.exists({"doctype": "Batch", "batch_id":"Test-SABBMRP-Bno-001"}):
			b_no = frappe.new_doc("Batch")
			b_no.batch_id = "Test-SABBMRP-Bno-001"
			b_no.item = item
			b_no.save()

		pr1.items[0].batch_no = "Test-SABBMRP-Bno-001"
		pr1.save()
		pr1.submit()

		sl_entry = frappe.db.get_all(
			"Stock Ledger Entry",
			{"voucher_type": "Purchase Receipt", "voucher_no": pr1.name},
			["actual_qty", "serial_and_batch_bundle"],
			order_by="creation",
		)

		sabb = frappe.get_doc("Serial and Batch Bundle", sl_entry[0].serial_and_batch_bundle)
		self.assertEqual(sl_entry[0].actual_qty, 3)
		self.assertEqual(sabb.entries[0].serial_no, "Test-SABBMRP-Sno-001")
		self.assertEqual(sabb.entries[0].batch_no, "Test-SABBMRP-Bno-001")

		pr2 = make_purchase_receipt(po.name)
		pr2.posting_date = "10-08-2024"
		pr2.items[0].use_serial_batch_fields = 1
		pr2.items[0].qty = 2
		pr2.items[0].serial_no = "Test-SABBMRP-Sno-004\nTest-SABBMRP-Sno-005"

		if not frappe.db.exists({"doctype": "Batch", "batch_id":"Test-SABBMRP-Bno-001"}):
			b_no = frappe.new_doc("Batch")
			b_no.batch_id = "Test-SABBMRP-Bno-001"
			b_no.item = item
			b_no.save()

		pr2.items[0].batch_no = "Test-SABBMRP-Bno-001"
		pr2.save()
		pr2.submit()

		sl_entry = frappe.db.get_all(
			"Stock Ledger Entry",
			{"voucher_type": "Purchase Receipt", "voucher_no": pr2.name},
			["actual_qty", "serial_and_batch_bundle"],
			order_by="creation",
		)

		sabb = frappe.get_doc("Serial and Batch Bundle", sl_entry[0].serial_and_batch_bundle)
		self.assertEqual(sl_entry[0].actual_qty, 2)
		self.assertEqual(sabb.entries[1].serial_no, "Test-SABBMRP-Sno-005")
		self.assertEqual(sabb.entries[1].batch_no, "Test-SABBMRP-Bno-001")

		return pr1, pr2
		

	def test_create_material_req_to_2po_to_1pi_cancel_TC_SCK_089(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr = create_purchase_invoice(po1.name, target_doc=pr)
		pr.submit()
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			recive_account = frappe.db.get_value("Company",mr.company,"stock_received_but_not_billed")
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 1000)

		pr.reload()
		pr.cancel()
		pr.reload()
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Creditors - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_mr_po_pi_return_TC_SCK_090(self):
		# MR =>  PO => PI => Return
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Ordered")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 1000)

		doc_pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", doc_pi.name)
		return_pi.submit()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		payable_act = frappe.db.get_value("Company",doc_mr.company,"default_payable_account")
		if payable_act:
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')

	def test_mr_po_2pi_return_TC_SCK_101(self):
		# MR =>  PO => 2PI => 2PI return
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.items[0].qty = 5
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Ordered")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		doc_pi1 = create_purchase_invoice(doc_po.name)
		doc_pi1.items[0].qty = 5
		doc_pi1.submit()

		self.assertEqual(doc_pi1.docstatus, 1)
		doc_pi1.reload()
		self.assertEqual(doc_pi1.status, "Unpaid")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		#Return PI's
		doc_pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", doc_pi.name)
		return_pi.submit()
		return_pi = make_return_doc("Purchase Invoice", doc_pi1.name)
		return_pi.submit()

		doc_pi.reload()
		doc_pi1.reload()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_2pi_return_TC_SCK_102(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr.submit()
		pr1 = create_purchase_invoice(po1.name)
		pr1.submit()
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			recive_account = frappe.db.get_value("Company",mr.company,"stock_received_but_not_billed")
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 500)
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 500)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 500)

		#Return PI's
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", pr.name)
		return_pi.submit()
		return_pi1 = make_return_doc("Purchase Invoice", pr1.name)
		return_pi1.submit()

		pr.reload()
		pr1.reload()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_1pi_return_TC_SCK_103(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr = create_purchase_invoice(po1.name, target_doc=pr)
		pr.submit()
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			recive_account = frappe.db.get_value("Company",mr.company,"stock_received_but_not_billed")
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 1000)

		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", pr.name)
		return_pi.submit()
		pr.reload()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
		if payable_act:
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')

	def test_mr_po_pi_partial_return_TC_SCK_104(self):
		# MR =>  PO => PI => Return
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Ordered")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 1000)

		doc_pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", doc_pi.name)
		return_pi.get("items")[0].qty = -5
		return_pi.submit()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		payable_act = frappe.db.get_value("Company",doc_mr.company,"default_payable_account")
		if payable_act:
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'credit')

	def test_mr_po_2pi_partial_return_TC_SCK_105(self):
		# MR =>  PO => 2PI => 2PI return
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.items[0].qty = 5
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Ordered")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		doc_pi1 = create_purchase_invoice(doc_po.name)
		doc_pi1.items[0].qty = 5
		doc_pi1.submit()

		self.assertEqual(doc_pi1.docstatus, 1)
		doc_pi1.reload()
		self.assertEqual(doc_pi1.status, "Unpaid")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

		#Return PI's
		doc_pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", doc_pi.name)
		return_pi.submit()

		doc_pi.reload()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_material_req_to_2po_to_1pr_return_TC_SCK_036(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = make_purchase_receipt(po.name)
		pr = make_purchase_receipt(po1.name, target_doc=pr)
		pr.submit()
		
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

		#Return PI's
		pr.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Receipt", pr.name)
		return_pi.submit()

		pr.reload()
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': 'Stock In Hand - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_mr_po_pr_partial_return_TC_SCK_038(self):
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "_Test Item",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pr = make_test_pr(doc_po.name)

		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")
		doc_pr.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Receipt", doc_pr.name)
		return_pi.get("items")[0].rejected_qty = -5
		return_pi.submit()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

	def test_mr_po_2pr_partial_return_TC_SCK_041(self):
		# MR =>  PO => 2PR => PR return
		mr_dict_list = [{
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 10,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pr = make_test_pr(doc_po.name,received_qty = 5)
		doc_pr.submit()

		doc_mr.reload()
		self.assertEqual(doc_pr.status, "To Bill")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		doc_pr1 = make_test_pr(doc_po.name)
		doc_pr1.items[0].accepted_qty = 5
		doc_pr1.submit()

		self.assertEqual(doc_pr1.docstatus, 1)
		doc_pr1.reload()
		self.assertEqual(doc_pr1.status, "To Bill")

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pr1.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		#Return PI's
		doc_pr.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pr = make_return_doc("Purchase Receipt", doc_pr.name)
		return_pr.get("items")[0].received_qty = -5
		return_pr.submit()

		doc_pr.reload()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_mr_to_2po_to_1pr_part_return_TC_SCK_042(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = make_purchase_receipt(po.name)
		pr = make_purchase_receipt(po1.name, target_doc=pr)
		pr.submit()
		
		bin_qty = frappe.db.get_value("Bin", {"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

		#Return PI's
		pr.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Receipt", pr.name)
		return_pi.items.pop(0)
		return_pi.items[0].received_qty = -5
		return_pi.submit()

		pr.reload()
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

	def test_create_mr_to_2po_to_2pi_partial_return_TC_SCK_106(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr.submit()
		pr1 = create_purchase_invoice(po1.name)
		pr1.submit()
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			recive_account = frappe.db.get_value("Company",mr.company,"stock_received_but_not_billed")
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 500)
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 500)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 500)

		#Return PI's
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", pr.name)
		return_pi.submit()

		pr.reload()

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'debit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Creditors - _TC'},'credit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_mr_for_purchase_2po_to_1pr_TC_SCK_021(self):
		from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import get_sl_entries, get_gl_entries

		frappe.db.set_value("Company", "_Test Company", "enable_perpetual_inventory", 1)
		frappe.db.set_value("Company", "_Test Company", "stock_adjustment_account", "Stock Adjustment - _TC")
		frappe.db.set_value(
			"Company", "_Test Company", "stock_received_but_not_billed", "Stock Received But Not Billed - _TC"
		)
		mr = make_material_request(
			material_request_type="Purchase",
			qty=10,
			item_code="_Test Item",
			rate=100,
			do_not_submit=True
		)
		mr.transaction_date = "01-08-2024"
		mr.schedule_date = "02-08-2024"
		mr.save()
		mr.submit()

		po1 = make_purchase_order(mr.name)
		po1.transaction_date = "01-08-2024"
		po1.schedule_date = "02-08-2024"
		po1.supplier = "_Test Supplier"
		po1.items[0].qty = 5
		po1.save()
		po1.submit()

		po2 = make_purchase_order(mr.name)
		po2.transaction_date = "01-08-2024"
		po2.schedule_date = "02-08-2024"
		po2.supplier = "_Test Supplier"
		po2.items[0].qty = 5
		po2.save()
		po2.submit()

		pr = make_purchase_receipt(po1.name)
		pr = make_purchase_receipt(po2.name, target_doc=pr)
		pr.submit()

		stock_in_hand_account = get_inventory_account("_Test Company", "_Test Warehouse - _TC")
		
		# Validate sle
		sl_entries = get_sl_entries("Purchase Receipt", pr.name)
		expected_sle = {"_Test Warehouse - _TC": 5}
		for sle in sl_entries:
			self.assertEqual(expected_sle[sle.warehouse], sle.actual_qty)

		# check gl entries
		gl_entries = get_gl_entries("Purchase Receipt", pr.name)
		expected_values = {
			stock_in_hand_account: [1000.0, 0.0],
			"Stock Received But Not Billed - _TC": [0.0, 1000.0],
		}

		for gle in gl_entries:
			self.assertEqual(expected_values[gle.account][0], gle.debit)
			self.assertEqual(expected_values[gle.account][1], gle.credit)
	def test_po_additional_discount_TC_B_079(self):
		# Scenario : MR=> PO => PR => PI [With IGST TAX]

		po_data = {
			"company" : "_Test Company",
			"item_code" : "_Test Item",
			"warehouse" : "Stores - _TC",
			"supplier": "_Test Supplier",
            "schedule_date": "2025-01-13",
			"qty" : 1,
			"rate" : 10000,
			"do_not_submit":1
		}

		acc = frappe.new_doc("Account")
		acc.account_name = "Input Tax IGST"
		acc.parent_account = "Tax Assets - _TC"
		acc.company = "_Test Company"
		account_name = frappe.db.exists("Account", {"account_name" : "Input Tax IGST","company": "_Test Company" })
		if not account_name:
			account_name = acc.insert()

		doc_mr = make_material_request(**po_data)
		doc_mr.append("taxes", {
                    "charge_type": "On Net Total",
                    "account_head": account_name,
                    "rate": 18,
                    "description": "Input GST",
                })
		doc_mr.submit()
		self.assertEqual(doc_mr.discount_amount, 1120)
		self.assertEqual(doc_mr.grand_total, 10080)

		doc_po = make_test_po(doc_mr.name)
		doc_pr = make_test_pr(doc_po.name)
		doc_pi = make_test_pi(doc_pr.name)

		self.assertEqual(doc_pi.discount_amount, 1120)
		self.assertEqual(doc_pi.grand_total, 10080)

		# Accounting Ledger Checks
		pi_gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": doc_pi.name}, fields=["account", "debit", "credit"])

		# PI Ledger Validation
		pi_total = sum(entry["debit"] for entry in pi_gl_entries)
		self.assertEqual(pi_total, 10080) 

	def test_purchase_flow_TC_B_068(self):
		#Scenario : MR=>PO=>PR=>PI [With Shipping Rule]
		
		args = {
					"calculate_based_on" : "Fixed",
					"shipping_amount" : 200
				}
		shipping_rule_name = get_shipping_rule_name(args)
		mr_dict_list = {
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 4,
				"rate" : 3000,
			}

		doc_mr = make_material_request(**mr_dict_list)
		self.assertEqual(doc_mr.docstatus, 1)

		args = {
			"shipping_rule" :shipping_rule_name
		}
		doc_po = make_test_po(doc_mr.name, args = args)
		self.assertEqual(doc_po.base_total_taxes_and_charges, 200)


		doc_pr = make_test_pr(doc_po.name)
		doc_pi = make_test_pi(doc_pr.name, args = args)

		self.assertEqual(doc_pi.docstatus, 1)
		
		doc_po.reload()
		self.assertEqual(doc_po.status, 'Completed')

	def test_purchase_flow_TC_B_069(self):
		#Scenario: MR=>SQ=>PO=>PR=>PI [With SQ and Shipping Rule]
		
		args = {
					"calculate_based_on" : "Fixed",
					"shipping_amount" : 200
				}
		shipping_rule_name = get_shipping_rule_name(args)
		mr_dict_list = {
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 4,
				"rate" : 3000,
			}

		doc_mr = make_material_request(**mr_dict_list)
		self.assertEqual(doc_mr.docstatus, 1)

		args = {
			"shipping_rule" :shipping_rule_name,
			"supplier" : "_Test Supplier"
		}
		doc_sq = make_test_sq(doc_mr.name, type = "Material Request",args = args)
		self.assertEqual(doc_sq.base_total_taxes_and_charges, 200)

		doc_po = make_test_po(doc_sq.name, type="Supplier Quotation")
		self.assertEqual(doc_po.base_total_taxes_and_charges, 200)


		doc_pr = make_test_pr(doc_po.name)
		doc_pi = make_test_pi(doc_pr.name, args = args)

		self.assertEqual(doc_pi.docstatus, 1)
		
		doc_po.reload()
		self.assertEqual(doc_po.status, 'Completed')

	def test_create_mr_to_2po_to_1pi_partial_return_TC_SCK_107(self):
		mr = make_material_request()
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr = create_purchase_invoice(po1.name, target_doc=pr)
		pr.submit()
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			recive_account = frappe.db.get_value("Company",mr.company,"stock_received_but_not_billed")
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': recive_account},'debit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 1000)

		pr.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice",pr.name)
		return_pi.items = return_pi.items[1:]
		return_pi.submit()
		pr.reload()

		#if account setup in company
		credit_account = frappe.db.get_value("Company",return_pi.company,"stock_received_but_not_billed")
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': credit_account},'credit')
		self.assertEqual(gl_temp_credit, 500)
		
		debit_account = frappe.db.get_value("Company",return_pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': debit_account},'debit')
		self.assertEqual(gl_stock_debit, 500)

	def test_mr_po_pi_serial_TC_SCK_092(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")

		mr_dict_list = [{
				"company" : "_Test Company MR",
				"item_code" : item.item_code,
				"warehouse" : warehouse,
				"cost_center" : frappe.db.get_value("Company","_Test Company MR","cost_center"),
				"qty" : 2,
				"rate" : 100,
			},
		]
		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.update_stock = 1
		doc_pi.has_serial_no = 1
		doc_pi.set_warehouse = warehouse
		doc_pi.items[0].serial_no = "011 - MR\n012 - MR\n"
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 200)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 200)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi.name})
		self.assertEqual(serial_cnt, 2)

	def test_mr_po_2pi_serial_TC_SCK_093(self):
		# MR =>  PO => 2PI
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")

		mr_dict_list = [{
				"company" : "_Test Company MR",
				"item_code" : item.item_code,
				"warehouse" : warehouse,
				"cost_center" : frappe.db.get_value("Company","_Test Company MR","cost_center"),
				"qty" : 2,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.update_stock = 1
		doc_pi.has_serial_no = 1
		doc_pi.set_warehouse = warehouse
		doc_pi.items[0].qty = 1
		doc_pi.items[0].serial_no = "013 - MR"
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Partially Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi.name})
		self.assertEqual(serial_cnt, 1)

		doc_pi1 = create_purchase_invoice(doc_po.name)
		doc_pi1.update_stock = 1
		doc_pi1.has_serial_no = 1
		doc_pi1.set_warehouse = warehouse
		doc_pi1.items[0].qty = 1
		doc_pi1.items[0].serial_no = "014 - MR"
		doc_pi1.submit()

		self.assertEqual(doc_pi1.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi1.name})
		self.assertEqual(serial_cnt, 1)

	def test_create_mr_to_2po_to_2pi_TC_SCK_094(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")

		mr = make_material_request(company="_Test Company MR",qty=2,supplier=supplier,warehouse=warehouse,item_code=item.item_code,cost_center=cost_center)
	
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = supplier
		po.get("items")[0].item_code = item.item_code
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 1
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = supplier
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 1
		po1.insert()
		po1.submit()

		pr = create_purchase_invoice(po.name)
		pr.update_stock = 1
		pr.set_warehouse = warehouse
		pr.items[0].qty = 1
		pr.items[0].serial_no = "01 - MR"
		pr.submit()

		pr1 = create_purchase_invoice(po1.name)
		pr1.update_stock = 1
		pr1.set_warehouse = warehouse
		pr1.items[0].qty = 1
		pr1.items[0].serial_no = "013 - MR"
		pr1.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': pr.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': pr.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 100)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pr.name})
		self.assertEqual(serial_cnt, 1)
		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pr1.name})
		self.assertEqual(serial_cnt, 1)
	def test_create_material_req_to_2po_to_pi_TC_SCK_095(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")
		qty = 10
		rate = 100
		mr = make_material_request(
			company="_Test Company MR",
			qty=qty,
			supplier=supplier,
			warehouse=warehouse,
			item_code=item.item_code,
			material_request_type="Purchase",
			cost_center=cost_center)
		self.assertEqual(mr.docstatus, 1)

		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.items[0].qty = 5
		po1.items[0].rate = rate
		po1.insert()
		po1.submit()
		self.assertEqual(po1.docstatus, 1)

		po2 = make_purchase_order(mr.name)
		po2.supplier = "_Test Supplier"
		po2.items[0].qty = 5
		po2.items[0].rate = rate
		po2.insert()
		po2.submit()
		self.assertEqual(po2.docstatus, 1)

		pi = create_purchase_invoice(po1.name)
		pi = create_purchase_invoice(po2.name, target_doc=pi)
		pi.set_warehouse = warehouse
		pi.update_stock = 1
		serial_numbers1 = ["SN001", "SN002","SN003", "SN004","SN005"]
		serial_numbers2 = ["SN006", "SN007","SN008", "SN009","SN010"]
		pi.items[0].serial_no = "\n".join(serial_numbers1)
		pi.items[1].serial_no = "\n".join(serial_numbers2)
		pi.insert()
		pi.submit()
		self.assertEqual(pi.docstatus, 1)
		
		sle_entries = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": pi.name})
		self.assertEqual(len(sle_entries), 2)

		stock_in_hand_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'debit')
		self.assertEqual(stock_in_hand_debit, 1000)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _CM'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			creditors_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': payable_act},'credit')
			self.assertEqual(creditors_credit, 1000)

	def test_create_material_req_to_2po_to_pi_serial_TC_SCK_096(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")
		item = item_create("Noise Smart watch")
		qty = 2
		rate = 10000

		mr = make_material_request(
			company="_Test Company MR",
			qty=qty,
			supplier=supplier,
			warehouse=warehouse,
			item_code=item.item_code,
			material_request_type="Purchase",
			cost_center=cost_center)
		self.assertEqual(mr.docstatus, 1)

		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.items[0].qty = 1
		po1.items[0].rate = rate
		po1.insert()
		po1.submit()
		self.assertEqual(po1.docstatus, 1)

		po2 = make_purchase_order(mr.name)
		po2.supplier = "_Test Supplier"
		po2.items[0].qty = 1
		po2.items[0].rate = rate
		po2.insert()
		po2.submit()
		self.assertEqual(po2.docstatus, 1)

		pi = create_purchase_invoice(po1.name)
		pi = create_purchase_invoice(po2.name, target_doc=pi)
		pi.set_warehouse = warehouse
		pi.update_stock = 1
		pi.items[0].serial_no = "SN-001"
		pi.items[1].serial_no = "SN-002"
		pi.insert()
		pi.submit()
		self.assertEqual(pi.docstatus, 1)

		sle_entries = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": pi.name})
		self.assertEqual(len(sle_entries), 2)
		for sle in sle_entries:
			sle = frappe.db.get_value('Stock Ledger Entry',sle.name,["warehouse", 'actual_qty', 'valuation_rate'],as_dict=1)
			self.assertEqual(sle.warehouse, warehouse)
			self.assertEqual(sle.actual_qty, 1)
			self.assertEqual(sle.valuation_rate, rate)

		serial_nos = frappe.get_all("Serial No", filters={"purchase_document_no": pi.name})
		self.assertEqual(len(serial_nos), qty)

		pi.cancel()
		sle_entries = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": pi.name,"is_cancelled": 0})
		self.assertEqual(len(sle_entries), 0)
		serial_nos = frappe.get_all("Serial No", filters={"purchase_document_no": pi.name,'status': 'Active'})
		self.assertEqual(len(serial_nos), 0)

	def test_mr_po_2pi_serial_cancel_TC_SCK_097(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")

		mr_dict_list = [{
				"company" : "_Test Company MR",
				"item_code" : item.item_code,
				"warehouse" : warehouse,
				"cost_center" : frappe.db.get_value("Company","_Test Company MR","cost_center"),
				"qty" : 2,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.update_stock = 1
		doc_pi.set_warehouse = warehouse
		doc_pi.items[0].qty = 1
		doc_pi.items[0].serial_no = "013 - MR"
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Partially Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi.name})
		self.assertEqual(serial_cnt, 1)

		doc_pi1 = create_purchase_invoice(doc_po.name)
		doc_pi1.update_stock = 1
		doc_pi1.set_warehouse = warehouse
		doc_pi1.items[0].qty = 1
		doc_pi1.items[0].serial_no = "014 - MR"
		doc_pi1.submit()

		self.assertEqual(doc_pi1.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi1.name})
		self.assertEqual(serial_cnt, 1)

		#cancel PI's
		doc_pi.reload()
		doc_pi.cancel()
		doc_pi.reload()
		self.assertEqual(doc_pi.status, "Cancelled")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': doc_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account':credit_account},'debit')
		self.assertEqual(gl_stock_debit, 100)

		doc_pi1.reload()
		doc_pi1.cancel()
		doc_pi1.reload()
		self.assertEqual(doc_pi1.status, "Cancelled")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': doc_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': credit_account},'debit')
		self.assertEqual(gl_stock_debit, 100)

	def test_mr_to_2po_to_2pi_serial_cancel_TC_SCK_098(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")

		mr = make_material_request(company="_Test Company MR",qty=2,supplier=supplier,warehouse=warehouse,item_code=item.item_code,cost_center=cost_center)
	
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = supplier
		po.get("items")[0].item_code = item.item_code
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 1
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = supplier
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 1
		po1.insert()
		po1.submit()

		pi = create_purchase_invoice(po.name)
		pi.update_stock = 1
		pi.set_warehouse = warehouse
		pi.items[0].qty = 1
		pi.items[0].serial_no = "01 - MR"
		pi.submit()

		pi1 = create_purchase_invoice(po1.name)
		pi1.update_stock = 1
		pi1.set_warehouse = warehouse
		pi1.items[0].qty = 1
		pi1.items[0].serial_no = "013 - MR"
		pi1.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi1.name, 'account': pi1.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 100)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi1.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi.name})
		self.assertEqual(serial_cnt, 1)
		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi1.name})
		self.assertEqual(serial_cnt, 1)

		#cancel PI's
		pi.reload()
		pi.cancel()
		pi.reload()
		self.assertEqual(pi.status, "Cancelled")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account':credit_account},'debit')
		self.assertEqual(gl_stock_debit, 100)

		pi1.reload()
		pi1.cancel()
		pi1.reload()
		self.assertEqual(pi1.status, "Cancelled")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi1.name, 'account': pi1.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi1.name, 'account': credit_account},'debit')
		self.assertEqual(gl_stock_debit, 100)

	def test_create_mr_to_2po_to_1pi_serial_cancel_TC_SCK_099(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")

		mr = make_material_request(company="_Test Company MR",qty=2,supplier=supplier,warehouse=warehouse,item_code=item.item_code,cost_center=cost_center)
	
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = supplier
		po.get("items")[0].item_code = item.item_code
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 1
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = supplier
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 1
		po1.insert()
		po1.submit()

		pi = create_purchase_invoice(po.name)
		pi = create_purchase_invoice(po1.name, target_doc=pi)
		pi.update_stock = 1
		pi.has_serial_no = 1
		pi.set_warehouse = warehouse
		pi.items[0].serial_no = "011 - MR"
		pi.items[1].serial_no = "012 - MR"
		pi.submit()
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 200)
		
		payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': payable_act},'credit')
		self.assertEqual(gl_stock_debit, 200)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi.name})
		self.assertEqual(serial_cnt, 2)

		pi.reload()
		pi.cancel()
		pi.reload()
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 200)
		
		payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 200)

	def test_mr_po_pi_serial_return_TC_SCK_108(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")

		mr_dict_list = [{
				"company" : "_Test Company MR",
				"item_code" : item.item_code,
				"warehouse" : warehouse,
				"cost_center" : frappe.db.get_value("Company","_Test Company MR","cost_center"),
				"qty" : 2,
				"rate" : 100,
			},
		]
		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.update_stock = 1
		doc_pi.has_serial_no = 1
		doc_pi.set_warehouse = warehouse
		doc_pi.items[0].serial_no = "011 - MR\n012 - MR\n"
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 200)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 200)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi.name})
		self.assertEqual(serial_cnt, 2)

		doc_pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", doc_pi.name)
		return_pi.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': return_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 200)
		
		payable_act = frappe.db.get_value("Company",doc_pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 200)

	def test_mr_po_2pi_serial_return_TC_SCK_109(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")

		mr_dict_list = [{
				"company" : "_Test Company MR",
				"item_code" : item.item_code,
				"warehouse" : warehouse,
				"cost_center" : frappe.db.get_value("Company","_Test Company MR","cost_center"),
				"qty" : 2,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.update_stock = 1
		doc_pi.has_serial_no = 1
		doc_pi.set_warehouse = warehouse
		doc_pi.items[0].qty = 1
		doc_pi.items[0].serial_no = "013 - MR"
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Partially Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi.name})
		self.assertEqual(serial_cnt, 1)

		doc_pi1 = create_purchase_invoice(doc_po.name)
		doc_pi1.update_stock = 1
		doc_pi1.has_serial_no = 1
		doc_pi1.set_warehouse = warehouse
		doc_pi1.items[0].qty = 1
		doc_pi1.items[0].serial_no = "014 - MR"
		doc_pi1.submit()

		self.assertEqual(doc_pi1.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi1.name})
		self.assertEqual(serial_cnt, 1)

		doc_pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", doc_pi.name)
		return_pi.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': return_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		payable_act = frappe.db.get_value("Company",doc_pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 100)

		doc_pi1.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi1 = make_return_doc("Purchase Invoice", doc_pi1.name)
		return_pi1.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi1.name, 'account': return_pi1.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		payable_act = frappe.db.get_value("Company",doc_pi1.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi1.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 100)

	def test_mr_to_2po_to_2pi_serial_return_TC_SCK_110(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")

		mr = make_material_request(company="_Test Company MR",qty=2,supplier=supplier,warehouse=warehouse,item_code=item.item_code,cost_center=cost_center)
	
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = supplier
		po.get("items")[0].item_code = item.item_code
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 1
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = supplier
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 1
		po1.insert()
		po1.submit()

		pi = create_purchase_invoice(po.name)
		pi.update_stock = 1
		pi.set_warehouse = warehouse
		pi.items[0].qty = 1
		pi.items[0].serial_no = "01 - MR"
		pi.submit()

		pi1 = create_purchase_invoice(po1.name)
		pi1.update_stock = 1
		pi1.set_warehouse = warehouse
		pi1.items[0].qty = 1
		pi1.items[0].serial_no = "013 - MR"
		pi1.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi1.name, 'account': pi1.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 100)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi1.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi.name})
		self.assertEqual(serial_cnt, 1)
		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi1.name})
		self.assertEqual(serial_cnt, 1)

		pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", pi.name)
		return_pi.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': return_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		payable_act = frappe.db.get_value("Company",pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 100)

		pi1.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi1 = make_return_doc("Purchase Invoice", pi1.name)
		return_pi1.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi1.name, 'account': return_pi1.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		payable_act = frappe.db.get_value("Company",pi1.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi1.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 100)

	def test_create_mr_to_2po_to_1pi_serial_return_TC_SCK_111(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")

		mr = make_material_request(company="_Test Company MR",qty=2,supplier=supplier,warehouse=warehouse,item_code=item.item_code,cost_center=cost_center)
	
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = supplier
		po.get("items")[0].item_code = item.item_code
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 1
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = supplier
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 1
		po1.insert()
		po1.submit()

		pi = create_purchase_invoice(po.name)
		pi = create_purchase_invoice(po1.name, target_doc=pi)
		pi.update_stock = 1
		pi.has_serial_no = 1
		pi.set_warehouse = warehouse
		pi.items[0].serial_no = "011 - MR"
		pi.items[1].serial_no = "012 - MR"
		pi.submit()
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 200)
		
		payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': payable_act},'credit')
		self.assertEqual(gl_stock_debit, 200)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi.name})
		self.assertEqual(serial_cnt, 2)

		pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", pi.name)
		return_pi.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': return_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 200)
		
		payable_act = frappe.db.get_value("Company",pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 200)

	def test_mr_po_pi_serial_partial_return_TC_SCK_112(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")

		mr_dict_list = [{
				"company" : "_Test Company MR",
				"item_code" : item.item_code,
				"warehouse" : warehouse,
				"cost_center" : frappe.db.get_value("Company","_Test Company MR","cost_center"),
				"qty" : 2,
				"rate" : 100,
			},
		]
		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.update_stock = 1
		doc_pi.has_serial_no = 1
		doc_pi.set_warehouse = warehouse
		doc_pi.items[0].serial_no = "011 - MR\n012 - MR\n"
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 200)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 200)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi.name})
		self.assertEqual(serial_cnt, 2)

		doc_pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", doc_pi.name)
		return_pi.get("items")[0].received_qty = -1
		return_pi.get("items")[0].qty = -1
		return_pi.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': return_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		payable_act = frappe.db.get_value("Company",doc_pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 100)

	def test_mr_po_2pi_serial_partial_return_TC_SCK_113(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")

		mr_dict_list = [{
				"company" : "_Test Company MR",
				"item_code" : item.item_code,
				"warehouse" : warehouse,
				"cost_center" : frappe.db.get_value("Company","_Test Company MR","cost_center"),
				"qty" : 2,
				"rate" : 100,
			},
		]

		doc_mr = make_material_request(**mr_dict_list[0])
		self.assertEqual(doc_mr.docstatus, 1)

		doc_po = make_test_po(doc_mr.name)
		doc_pi = create_purchase_invoice(doc_po.name)
		doc_pi.update_stock = 1
		doc_pi.has_serial_no = 1
		doc_pi.set_warehouse = warehouse
		doc_pi.items[0].qty = 1
		doc_pi.items[0].serial_no = "013 - MR"
		doc_pi.submit()

		self.assertEqual(doc_pi.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Partially Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi.name})
		self.assertEqual(serial_cnt, 1)

		doc_pi1 = create_purchase_invoice(doc_po.name)
		doc_pi1.update_stock = 1
		doc_pi1.has_serial_no = 1
		doc_pi1.set_warehouse = warehouse
		doc_pi1.items[0].qty = 1
		doc_pi1.items[0].serial_no = "014 - MR"
		doc_pi1.submit()

		self.assertEqual(doc_pi1.docstatus, 1)
		doc_mr.reload()
		self.assertEqual(doc_mr.status, "Received")

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': doc_pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		
		credit_account = frappe.db.get_value("Company","_Test Company MR","default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':doc_pi1.name, 'account': credit_account},'credit')
		self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':doc_pi1.name})
		self.assertEqual(serial_cnt, 1)

		doc_pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", doc_pi.name)
		return_pi.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': return_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		payable_act = frappe.db.get_value("Company",doc_pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 100)

	def test_mr_to_2po_to_2pi_sr_partail_return_TC_SCK_114(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")

		mr = make_material_request(company="_Test Company MR",qty=2,supplier=supplier,warehouse=warehouse,item_code=item.item_code,cost_center=cost_center)
	
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = supplier
		po.get("items")[0].item_code = item.item_code
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 1
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = supplier
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 1
		po1.insert()
		po1.submit()

		pi = create_purchase_invoice(po.name)
		pi.update_stock = 1
		pi.set_warehouse = warehouse
		pi.items[0].qty = 1
		pi.items[0].serial_no = "01 - MR"
		pi.submit()

		pi1 = create_purchase_invoice(po1.name)
		pi1.update_stock = 1
		pi1.set_warehouse = warehouse
		pi1.items[0].qty = 1
		pi1.items[0].serial_no = "013 - MR"
		pi1.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi1.name, 'account': pi1.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 100)

		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Creditors - _TC'}):
			payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 100)
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi1.name, 'account': payable_act},'credit')
			self.assertEqual(gl_stock_debit, 100)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi.name})
		self.assertEqual(serial_cnt, 1)
		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi1.name})
		self.assertEqual(serial_cnt, 1)

		pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", pi.name)
		return_pi.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': return_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		payable_act = frappe.db.get_value("Company",pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 100)

	def test_create_mr_to_2po_to_1pi_sr_prtl_ret_TC_SCK_115(self):
		create_company()
		create_fiscal_year()
		supplier = create_supplier(supplier_name="_Test Supplier MR")
		warehouse = create_warehouse("_Test warehouse PO", company="_Test Company MR")
		item = item_create("_Test MR")
		cost_center = frappe.db.get_value("Company","_Test Company MR","cost_center")

		mr = make_material_request(company="_Test Company MR",qty=2,supplier=supplier,warehouse=warehouse,item_code=item.item_code,cost_center=cost_center)
	
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = supplier
		po.get("items")[0].item_code = item.item_code
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 1
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = supplier
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 1
		po1.insert()
		po1.submit()

		pi = create_purchase_invoice(po.name)
		pi = create_purchase_invoice(po1.name, target_doc=pi)
		pi.update_stock = 1
		pi.has_serial_no = 1
		pi.set_warehouse = warehouse
		pi.items[0].serial_no = "011 - MR"
		pi.items[1].serial_no = "012 - MR"
		pi.submit()
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': pi.items[0].expense_account},'debit')
		self.assertEqual(gl_temp_credit, 200)
		
		payable_act = frappe.db.get_value("Company",mr.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pi.name, 'account': payable_act},'credit')
		self.assertEqual(gl_stock_debit, 200)

		serial_cnt = frappe.db.count('Serial No',{'purchase_document_no':pi.name})
		self.assertEqual(serial_cnt, 2)

		pi.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Invoice", pi.name)
		return_pi.items = return_pi.items[1:]
		return_pi.submit()

		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': return_pi.items[0].expense_account},'credit')
		self.assertEqual(gl_temp_credit, 100)
		
		payable_act = frappe.db.get_value("Company",pi.company,"default_payable_account")
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': payable_act},'debit')
		self.assertEqual(gl_stock_debit, 100)

	def test_mr_to_po_pr_with_serial_no_TC_B_156(self):
		company = "_Test Company"
		warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_code = "_Test Item With Serial No"
		quantity = 2
		gst_hsn_code = "11112222"
		if not frappe.db.exists("GST HSN Code", gst_hsn_code):
			gst_hsn_code = frappe.new_doc("GST HSN Code")
			gst_hsn_code.hsn_code = "11112222"
			gst_hsn_code.save()

		if not frappe.db.exists("Item", item_code):
			item = frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"item_group": "_Test Item Group",
				"default_warehouse": warehouse,
				"company": company,
				"gst_hsn_code": gst_hsn_code,
				"has_serial_no": 1
			})
			item.insert()
		mr = frappe.get_doc({
			"doctype": "Material Request",
			"material_request_type": "Purchase",
			"transaction_date": today(),
			"company": company,
			"items": [{
				"item_code": item_code,
				"qty": quantity,
				"warehouse": warehouse
			}]
		})
		mr.insert()
		mr.submit()

		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": supplier,
			"schedule_date": today(),
			"company": mr.company,
			"set_warehouse": warehouse,
			"items": [{
				"item_code": mr.items[0].item_code,
				"qty": mr.items[0].qty,
				"rate": 1000,
				"material_request": mr.name
			}]
		})
		po.insert()
		po.submit()

		pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"supplier": po.supplier,
			"posting_date": today(),
			"company": company,
			"items": [{
				"item_code": po.items[0].item_code,
				"qty": po.items[0].qty,
				"warehouse": po.items[0].warehouse,
				"rate": po.items[0].rate
			}]
		})
		pr.insert()

		serial_numbers = ["test_item_001", "test_item_002"]
		pr.items[0].serial_no = "\n".join(serial_numbers)
		pr.save()
		pr.submit()
		print("Purchase Receipt submitted with Serial Numbers:", pr.name)
		sle = frappe.db.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": pr.name, "item_code": item_code},
			fields=["actual_qty", "warehouse", "valuation_rate"]
		)

		self.assertEqual(len(sle), 1)
		self.assertEqual(sle[0]["actual_qty"], quantity)
		self.assertEqual(sle[0]["warehouse"], warehouse)
		self.assertEqual(sle[0]["valuation_rate"], 1000)

		for serial_no in serial_numbers:
			sn = frappe.get_doc("Serial No", serial_no)
			self.assertEqual(sn.warehouse, warehouse)
			self.assertEqual(sn.item_code, item_code)

	def test_mr_to_po_pr_with_multiple_serial_nos_TC_B_157(self):
		company = "_Test Company"
		warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_code = "_Test Item With Serial No"
		total_quantity = 5
		first_pr_quantity = 3
		second_pr_quantity = 2
		gst_hsn_code = "11112222"

		if not frappe.db.exists("GST HSN Code", gst_hsn_code):
			gst_hsn = frappe.new_doc("GST HSN Code")
			gst_hsn.hsn_code = gst_hsn_code
			gst_hsn.save()

		if not frappe.db.exists("Item", item_code):
			item = frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"item_group": "_Test Item Group",
				"default_warehouse": warehouse,
				"company": company,
				"gst_hsn_code": gst_hsn_code,
				"has_serial_no": 1
			})
			item.insert()

		mr = frappe.get_doc({
			"doctype": "Material Request",
			"material_request_type": "Purchase",
			"transaction_date": today(),
			"company": company,
			"items": [{
				"item_code": item_code,
				"qty": total_quantity,
				"warehouse": warehouse
			}]
		})
		mr.insert()
		mr.submit()

		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": supplier,
			"schedule_date": today(),
			"company": company,
			"set_warehouse": warehouse,
			"items": [{
				"item_code": mr.items[0].item_code,
				"qty": mr.items[0].qty,
				"rate": 1000,
				"material_request": mr.name
			}]
		})
		po.insert()
		po.submit()

		pr1 = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"supplier": po.supplier,
			"posting_date": today(),
			"company": company,
			"items": [{
				"item_code": po.items[0].item_code,
				"qty": first_pr_quantity,
				"warehouse": po.items[0].warehouse,
				"rate": po.items[0].rate
			}]
		})
		pr1.insert()
		serial_numbers1 = [f"test_item_00{i}" for i in range(1, first_pr_quantity + 1)]
		pr1.items[0].serial_no = "\n".join(serial_numbers1)
		pr1.save()
		pr1.submit()

		sle1 = frappe.db.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": pr1.name, "item_code": item_code},
			fields=["actual_qty", "warehouse", "valuation_rate"]
		)
		self.assertEqual(len(sle1), 1)
		self.assertEqual(sle1[0]["actual_qty"], first_pr_quantity)
		self.assertEqual(sle1[0]["warehouse"], warehouse)
		self.assertEqual(sle1[0]["valuation_rate"], 1000)

		for serial_no in serial_numbers1:
			sn = frappe.get_doc("Serial No", serial_no)
			self.assertEqual(sn.warehouse, warehouse)
			self.assertEqual(sn.item_code, item_code)

		second_date = add_days(today(), 1)
		pr2 = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"supplier": po.supplier,
			"posting_date": second_date,
			"company": company,
			"items": [{
				"item_code": po.items[0].item_code,
				"qty": second_pr_quantity,
				"warehouse": po.items[0].warehouse,
				"rate": po.items[0].rate
			}]
		})
		pr2.insert()
		serial_numbers2 = [f"test_item_00{i}" for i in range(first_pr_quantity + 1, total_quantity + 1)]
		pr2.items[0].serial_no = "\n".join(serial_numbers2)
		pr2.save()
		pr2.submit()

		sle2 = frappe.db.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": pr2.name, "item_code": item_code},
			fields=["actual_qty", "warehouse", "valuation_rate"]
		)
		self.assertEqual(len(sle2), 1)
		self.assertEqual(sle2[0]["actual_qty"], second_pr_quantity)
		self.assertEqual(sle2[0]["warehouse"], warehouse)
		self.assertEqual(sle2[0]["valuation_rate"], 1000)

		for serial_no in serial_numbers2:
			sn = frappe.get_doc("Serial No", serial_no)
			self.assertEqual(sn.warehouse, warehouse)
			self.assertEqual(sn.item_code, item_code)

	def test_mr_to_po_pi_with_serial_nos_TC_B_158(self):
		company = "_Test Company"
		warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_code = "_Test Item With Serial No"
		quantity = 3
		gst_hsn_code = "11112222"

		if not frappe.db.exists("GST HSN Code", gst_hsn_code):
			gst_hsn = frappe.new_doc("GST HSN Code")
			gst_hsn.hsn_code = gst_hsn_code
			gst_hsn.save()

		if not frappe.db.exists("Item", item_code):
			item = frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"item_group": "_Test Item Group",
				"default_warehouse": warehouse,
				"company": company,
				"gst_hsn_code": gst_hsn_code,
				"has_serial_no": 1
			})
			item.insert()

		mr = frappe.get_doc({
			"doctype": "Material Request",
			"material_request_type": "Purchase",
			"transaction_date": today(),
			"company": company,
			"items": [{
				"item_code": item_code,
				"qty": quantity,
				"warehouse": warehouse
			}]
		})
		mr.insert()
		mr.submit()

		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": supplier,
			"schedule_date": today(),
			"company": company,
			"set_warehouse": warehouse,
			"items": [{
				"item_code": mr.items[0].item_code,
				"qty": mr.items[0].qty,
				"rate": 1000,
				"material_request": mr.name
			}]
		})
		po.insert()
		po.submit()

		pi = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"supplier": po.supplier,
			"posting_date": today(),
			"company": company,
			"update_stock": 1,
			"items": [{
				"item_code": po.items[0].item_code,
				"qty": po.items[0].qty,
				"warehouse": po.items[0].warehouse,
				"rate": po.items[0].rate
			}]
		})
		pi.insert()
		serial_numbers = [f"test_item_00{i}" for i in range(1, quantity + 1)]
		pi.items[0].serial_no = "\n".join(serial_numbers)
		pi.save()
		pi.submit()

		sle = frappe.db.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": pi.name, "item_code": item_code},
			fields=["actual_qty", "warehouse", "valuation_rate", "posting_date"]
		)
		self.assertEqual(len(sle), 1)
		self.assertEqual(sle[0]["actual_qty"], quantity)
		self.assertEqual(sle[0]["warehouse"], warehouse)
		self.assertEqual(sle[0]["valuation_rate"], 1000)
		self.assertEqual(sle[0]["posting_date"], getdate(today()))

		for serial_no in serial_numbers:
			sn = frappe.get_doc("Serial No", serial_no)
			self.assertEqual(sn.warehouse, warehouse)
			self.assertEqual(sn.item_code, item_code)

	def test_mr_to_pi_with_PE_TC_B_076(self):
		# MR =>  PO => PE => PR => PI
		mr_dict_list = {
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 1,
				"rate" : 3000,
			}

		doc_mr = make_material_request(**mr_dict_list)
		self.assertEqual(doc_mr.docstatus, 1)

		
		doc_po = make_test_po(doc_mr.name)
		args = {
			"mode_of_payment" : "Cash",
			"reference_no" : "For Testing"
		}

		doc_pe = make_payment_entry(doc_po.doctype, doc_po.name, doc_po.grand_total, args)

		doc_pr = make_test_pr(doc_po.name)

		args = {
			"is_paid" : 1,
			"mode_of_payment" : 'Cash',
			"cash_bank_account" : doc_pe.paid_from,
			"paid_amount" : doc_pe.base_received_amount
		}
		doc_pi = make_test_pi(doc_pr.name, args = args)
		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.items[0].qty, doc_po.items[0].qty)
		self.assertEqual(doc_pi.grand_total, doc_po.grand_total)
		
		doc_po.reload()
		self.assertEqual(doc_po.status, 'Completed')
		self.assertEqual(doc_pi.status, 'Paid')

	def test_mr_to_pi_with_partial_PE_TC_B_077(self):
		# MR =>  PO => [Partial]PE => PR => PI [PE with oustanding amount]
		mr_dict_list = {
				"company" : "_Test Company",
				"item_code" : "Testing-31",
				"warehouse" : "Stores - _TC",
				"qty" : 4,
				"rate" : 3000,
			}

		doc_mr = make_material_request(**mr_dict_list)
		self.assertEqual(doc_mr.docstatus, 1)

		
		doc_po = make_test_po(doc_mr.name)
		args = {
			"mode_of_payment" : "Cash",
			"reference_no" : "For Testing"
		}

		doc_pe = make_payment_entry(doc_po.doctype, doc_po.name, 6000, args)

		doc_pr = make_test_pr(doc_po.name)

		args = {
			"is_paid" : 1,
			"mode_of_payment" : 'Cash',
			"cash_bank_account" : doc_pe.paid_from,
			"paid_amount" : doc_pe.base_received_amount
		}

		doc_pi = make_test_pi(doc_pr.name, args = args)

		args = {
			"mode_of_payment" : "Cash",
			"reference_no" : "For Testing"
		}
		make_payment_entry(doc_pi.doctype, doc_pi.name, doc_pi.outstanding_amount, args)

		self.assertEqual(doc_pi.docstatus, 1)
		self.assertEqual(doc_pi.items[0].qty, doc_po.items[0].qty)
		self.assertEqual(doc_pi.grand_total, doc_po.grand_total)
		
		doc_po.reload()
		doc_pi.reload()
		self.assertEqual(doc_po.status, 'Completed')
		self.assertEqual(doc_pi.status, 'Paid')

	def test_create_material_req_serial_to_2po_to_2pr_TC_SCK_192(self):
		company = "_Test Company"
		warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_code = "_Test Item With Serial No"
		quantity = 3

		if not frappe.db.exists("Item", item_code):
			item = frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"item_group": "_Test Item Group",
				"default_warehouse": warehouse,
				"company": company,
				"has_serial_no": 1
			})
			if 'india_compliance' in frappe.get_installed_apps():
				gst_hsn_code = "11112222"
				if not frappe.db.exists("GST HSN Code", gst_hsn_code):
					gst_hsn_code = frappe.new_doc("GST HSN Code")
					gst_hsn_code.hsn_code = "11112222"
					gst_hsn_code.save()
				item.gst_hsn_code = gst_hsn_code
			item.insert()
		mr = make_material_request(item_code=item_code)
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		serial_numbers = [f"test_item_00{i}" for i in range(1, int(po.get("items")[0].qty) + 1)]
		pr.items[0].serial_no = "\n".join(serial_numbers)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr1 = make_purchase_receipt(po1.name)
		serial_numbers = [f"test_item1_00{i}" for i in range(1, int(po1.get("items")[0].qty) + 1)]
		pr1.items[0].serial_no = "\n".join(serial_numbers)
		pr1.insert()
		pr1.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

	def test_create_mr_to_2po_to_2pr_serial_return_TC_SCK_193(self):
		company = "_Test Company"
		warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_code = "_Test Item With Serial No"
		quantity = 3

		if not frappe.db.exists("Item", item_code):
			item = frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"item_group": "_Test Item Group",
				"default_warehouse": warehouse,
				"company": company,
				"has_serial_no": 1
			})
			if 'india_compliance' in frappe.get_installed_apps():
				gst_hsn_code = "11112222"
				if not frappe.db.exists("GST HSN Code", gst_hsn_code):
					gst_hsn_code = frappe.new_doc("GST HSN Code")
					gst_hsn_code.hsn_code = "11112222"
					gst_hsn_code.save()
				item.gst_hsn_code = gst_hsn_code
			item.insert()
		mr = make_material_request(item_code=item_code)
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr = make_purchase_receipt(po.name)
		serial_numbers = [f"test_item_00{i}" for i in range(1, int(po.get("items")[0].qty) + 1)]
		pr.items[0].serial_no = "\n".join(serial_numbers)
		pr.insert()
		pr.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		pr.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi = make_return_doc("Purchase Receipt", pr.name)
		return_pi.submit()
		
		debit_act = frappe.db.get_value("Company",return_pi.company,"stock_received_but_not_billed")
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': debit_act},'debit')
		self.assertEqual(gl_temp_credit, 500)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi.name, 'account': 'Stock In Hand - _TC'},'credit')
		self.assertEqual(gl_stock_debit, 500)

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr1 = make_purchase_receipt(po1.name)
		serial_numbers = [f"test_item1_00{i}" for i in range(1, int(po1.get("items")[0].qty) + 1)]
		pr1.items[0].serial_no = "\n".join(serial_numbers)
		pr1.insert()
		pr1.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 5)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 500)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 500)

		pr1.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi1 = make_return_doc("Purchase Receipt", pr1.name)
		return_pi1.submit()
		
		debit_act = frappe.db.get_value("Company",return_pi1.company,"stock_received_but_not_billed")
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi1.name, 'account': debit_act},'debit')
		self.assertEqual(gl_temp_credit, 500)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi1.name, 'account': 'Stock In Hand - _TC'},'credit')
		self.assertEqual(gl_stock_debit, 500)

	def test_create_mr_to_2po_to_1pr_serial_return_TC_SCK_194(self):
		company = "_Test Company"
		warehouse = "Stores - _TC"
		supplier = "_Test Supplier 1"
		item_code = "_Test Item With Serial No"

		if not frappe.db.exists("Item", item_code):
			item = frappe.get_doc({
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"item_group": "_Test Item Group",
				"default_warehouse": warehouse,
				"company": company,
				"has_serial_no": 1
			})
			if 'india_compliance' in frappe.get_installed_apps():
				gst_hsn_code = "11112222"
				if not frappe.db.exists("GST HSN Code", gst_hsn_code):
					gst_hsn_code = frappe.new_doc("GST HSN Code")
					gst_hsn_code.hsn_code = "11112222"
					gst_hsn_code.save()
				item.gst_hsn_code = gst_hsn_code
			item.insert()
		mr = make_material_request(item_code=item_code)
		
		#partially qty
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.get("items")[0].rate = 100
		po.get("items")[0].qty = 5
		po.insert()
		po.submit()

		#remaining qty
		po1 = make_purchase_order(mr.name)
		po1.supplier = "_Test Supplier"
		po1.get("items")[0].rate = 100
		po1.get("items")[0].qty = 5
		po1.insert()
		po1.submit()

		bin_qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": "_Test Warehouse - _TC"}, "actual_qty")
		pr1 = make_purchase_receipt(po.name)
		pr1 = make_purchase_receipt(po1.name, target_doc=pr1)
		serial_numbers = [f"test_item11_00{i}" for i in range(1, 5 + 1)]
		pr1.items[0].serial_no = "\n".join(serial_numbers)
		serial_numbers1 = [f"test_item12_00{i}" for i in range(1, 5 + 1)]
		pr1.items[1].serial_no = "\n".join(serial_numbers1)
		pr1.insert()
		pr1.submit()
		
		sle = frappe.get_doc('Stock Ledger Entry',{'voucher_no':pr1.name})
		self.assertEqual(sle.qty_after_transaction, bin_qty + 10)
		self.assertEqual(sle.warehouse, mr.get("items")[0].warehouse)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock Received But Not Billed - _TC'}):
			gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
			self.assertEqual(gl_temp_credit, 1000)
		
		#if account setup in company
		if frappe.db.exists('GL Entry',{'account': 'Stock In Hand - _TC'}):
			gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':pr1.name, 'account': 'Stock In Hand - _TC'},'debit')
			self.assertEqual(gl_stock_debit, 1000)

		pr1.load_from_db()
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		return_pi1 = make_return_doc("Purchase Receipt", pr1.name)

		serial_numbers = [f"test_item13_00{i}" for i in range(1, 5 + 1)]
		return_pi1.items[0].serial_no = "\n".join(serial_numbers)
		serial_numbers1 = [f"test_item14_00{i}" for i in range(1, 5 + 1)]
		return_pi1.items[1].serial_no = "\n".join(serial_numbers1)
		return_pi1.submit()
		
		debit_act = frappe.db.get_value("Company",return_pi1.company,"stock_received_but_not_billed")
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi1.name, 'account': debit_act},'debit')
		self.assertEqual(gl_temp_credit, 1000)
		
		gl_stock_debit = frappe.db.get_value('GL Entry',{'voucher_no':return_pi1.name, 'account': 'Stock In Hand - _TC'},'credit')
		self.assertEqual(gl_stock_debit, 1000)

def get_in_transit_warehouse(company):
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc(
			{
				"doctype": "Warehouse Type",
				"name": "Transit",
			}
		).insert()

	in_transit_warehouse = frappe.db.exists("Warehouse", {"warehouse_type": "Transit", "company": company})

	if not in_transit_warehouse:
		in_transit_warehouse = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "Transit",
					"warehouse_type": "Transit",
					"company": company,
				}
			)
			.insert()
			.name
		)

	return in_transit_warehouse


def get_gle(company, voucher_no, account):
	return(
			frappe.db.get_value(
				"GL Entry",
				{
					"company": company,
					"voucher_no": voucher_no,
					'account': account
				},
				["sum(debit)", "sum(credit)"],
				order_by=None
			)
			or 0.0
		)


def make_material_request(**args):
	args = frappe._dict(args)
	mr = frappe.new_doc("Material Request")
	mr.material_request_type = args.material_request_type or "Purchase"
	mr.company = args.company or "_Test Company"
	mr.customer = args.customer or "_Test Customer"
	mr.shipping_rule = args.shipping_rule or None
	mr.append(
		"items",
		{
			"item_code": args.item_code or "_Test Item",
			"qty": args.qty or 10,
			"uom": args.uom or "_Test UOM",
			"conversion_factor": args.conversion_factor or 1,
			"schedule_date": args.schedule_date or today(),
			"warehouse": args.warehouse or "_Test Warehouse - _TC",
			"cost_center": args.cost_center or "_Test Cost Center - _TC",
			"from_warehouse": args.from_warehouse or "",
			"rate" : args.rate or 0
		},
	)
	mr.insert()
	if not args.do_not_submit:
		mr.submit()
	return mr


test_dependencies = ["Currency Exchange", "BOM"]
test_records = frappe.get_test_records("Material Request")



def make_test_rfq(source_name, received_qty=0):
	doc_rfq = make_request_for_quotation(source_name)

	supplier_data=[
				{
					"supplier": "_Test Supplier",
					"email_id": "123_testrfquser@example.com",
				}
			]
	doc_rfq.append("suppliers", supplier_data[0])
	doc_rfq.message_for_supplier = "Please supply the specified items at the best possible rates."
		
	if received_qty:
		doc_rfq.items[0].qty = received_qty

	doc_rfq.insert()
	doc_rfq.submit()
	return doc_rfq


def make_test_sq(source_name, rate = 0, received_qty=0, item_dict = None, type = "RFQ", args = None):
	if type == "RFQ" : 
		doc_sq = make_supplier_quotation_from_rfq(source_name, for_supplier = "_Test Supplier")
	
	elif type == "Material Request" :
		from erpnext.stock.doctype.material_request.material_request import  make_supplier_quotation
		doc_sq = make_supplier_quotation(source_name)

	if received_qty:
		doc_sq.items[0].qty = received_qty

	doc_sq.items[0].rate = rate
		
	if item_dict is not None:
		doc_sq.append("items", item_dict)

	if args is not None:
		args = frappe._dict(args)
		doc_sq.update(args)

	doc_sq.insert()
	doc_sq.submit()
	return doc_sq


def make_test_po(source_name, type = "Material Request", received_qty = 0, item_dict = None, args = None):
	if type == "Material Request":
		doc_po = make_purchase_order(source_name)

	elif type == 'Supplier Quotation':
		doc_po = create_po_aganist_sq(source_name)

	if doc_po.supplier is None:
		doc_po.supplier = "_Test Supplier"

	if received_qty:
		doc_po.items[0].qty = received_qty
		
	if item_dict is not None:
		doc_po.append("items", item_dict)

	if args is not None:
		args = frappe._dict(args)
		doc_po.update(args)

	doc_po.insert()
	doc_po.submit()
	return doc_po


def make_test_pr(source_name, received_qty = None, item_dict = None, remove_items = False):
	doc_pr = make_purchase_receipt_aganist_mr(source_name)

	if received_qty is not None:
		doc_pr.items[0].qty = received_qty

	if remove_items:
		doc_pr.items = []

	if item_dict is not None:
		doc_pr.append("items", item_dict)

	doc_pr.insert()
	doc_pr.submit()
	return doc_pr


def make_test_pi(source_name, received_qty = None, item_dict = None, args = None):
	doc_pi = make_purchase_invoice(source_name)
	if received_qty is not None:
		doc_pi.items[0].qty = received_qty
		
	if item_dict is not None:
		doc_pi.append("items", item_dict)

	if args is not None:
		args = frappe._dict(args)
		doc_pi.update(args)

	doc_pi.insert()
	doc_pi.submit()
	return doc_pi


def create_mr_to_pi(**args):
	args = frappe._dict(args)
	for arg in args['mr']:
		doc_mr = make_material_request(**arg)
		source_name_rfq = make_test_rfq(doc_mr.name)
		source_name_sq= make_test_sq(source_name_rfq)
		source_name_po = make_test_po(source_name_sq)
		source_name_pr = make_test_pr(source_name_po)
		source_name_pi = make_test_pi(source_name_pr)
		return source_name_pi

def create_company():
	company_name = "_Test Company MR"
	if not frappe.db.exists("Company", company_name):
		company = frappe.new_doc("Company")
		company.company_name = company_name
		company.country="India",
		company.default_currency= "INR",
		company.create_chart_of_accounts_based_on= "Standard Template",
		company.chart_of_accounts= "Standard",
		company = company.save()
		company.load_from_db()
	return company_name
		
def create_fiscal_year():
	today = date.today()
	if today.month >= 4:  # Fiscal year starts in April
		start_date = date(today.year, 4, 1)
		end_date = date(today.year + 1, 3, 31)
	else:
		start_date = date(today.year - 1, 4, 1)
		end_date = date(today.year, 3, 31)

	company="_Test Company MR", 
	fy_doc = frappe.new_doc("Fiscal Year")
	fy_doc.year = "2025 PO"
	fy_doc.year_start_date = start_date
	fy_doc.year_end_date = end_date
	fy_doc.append("companies", {"company": company})
	fy_doc.submit()
	
def item_create(
	item_code,
	is_stock_item=1,
	valuation_rate=0,
	stock_uom="Nos",
	warehouse="_Test warehouse PO - _CM",
	is_customer_provided_item=None,
	customer=None,
	is_purchase_item=None,
	opening_stock=0,
	is_fixed_asset=0,
	asset_category=None,
	buying_cost_center=None,
	selling_cost_center=None,
	company="_Test Company MR",
	has_serial_no=1
):
	if not frappe.db.exists("Item", item_code):
		item = frappe.new_doc("Item")
		item.item_code = item_code
		item.item_name = item_code
		item.description = item_code
		item.item_group = "All Item Groups"
		item.stock_uom = stock_uom
		item.is_stock_item = is_stock_item
		item.is_fixed_asset = is_fixed_asset
		item.asset_category = asset_category
		item.opening_stock = opening_stock
		item.valuation_rate = valuation_rate
		item.is_purchase_item = is_purchase_item
		item.is_customer_provided_item = is_customer_provided_item
		item.customer = customer or ""
		item.has_serial_no = has_serial_no
		item.append(
			"item_defaults",
			{
				"default_warehouse": warehouse,
				"company": company,
				"selling_cost_center": selling_cost_center,
				"buying_cost_center": buying_cost_center,
			},
		)
		if 'india_compliance' in frappe.get_installed_apps():
			gst_hsn_code = "11112222"
			if not frappe.db.exists("GST HSN Code", gst_hsn_code):
				gst_hsn_code = frappe.new_doc("GST HSN Code")
				gst_hsn_code.hsn_code = "11112222"
				gst_hsn_code.save()
			item.gst_hsn_code = gst_hsn_code
		item.save()
	else:
		item = frappe.get_doc("Item", item_code)
	return item


def make_payment_entry(dt, dn, paid_amount, args = None):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	doc_pe = get_payment_entry(dt, dn, paid_amount)
	
	args =  frappe._dict() if args is None else frappe._dict(args)
	doc_pe.mode_of_payment = args.mode_of_payment or None
	doc_pe.reference_no =  args.reference_no or "Test Reference"
	
	doc_pe.submit()
	return doc_pe


def get_shipping_rule_name(args = None):
	from erpnext.accounts.doctype.shipping_rule.test_shipping_rule import create_shipping_rule
	doc_shipping_rule = create_shipping_rule("Buying", "_Test Shipping Rule -TC", args)
	return doc_shipping_rule.name

