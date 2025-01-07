# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# ERPNext - web based ERP (http://erpnext.com)
# For license information, please see license.txt


import frappe
import json
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from erpnext.stock.doctype.item.test_item import create_item
from erpnext.stock.doctype.material_request.material_request import (
	make_in_transit_stock_entry,
	make_purchase_order,
	make_stock_entry,
	make_supplier_quotation,
	raise_work_orders,
)
from erpnext.stock.doctype.warehouse.test_warehouse import create_warehouse
from erpnext.stock.doctype.pick_list.pick_list import create_stock_entry as pl_stock_entry
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.stock.doctype.warehouse.test_warehouse import create_warehouse
from erpnext.accounts.doctype.account.test_account import get_inventory_account

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
		self.assertEqual(mr.status, "Partially Ordered")

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
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
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
		
		gl_temp_credit = frappe.db.get_value('GL Entry',{'voucher_no':pr.name, 'account': 'Stock Received But Not Billed - _TC'},'credit')
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
	
	def test_create_material_issue_and_check_status(self):
		company = "_Test Company"
		qty = 10
		target_warehouse = create_warehouse("_Test Warehouse", properties=None, company=company)
		
		mr = make_material_request(material_request_type="Material Issue", qty=qty, warehouse=target_warehouse, item="_Test Item")
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
	
	def test_create_material_req_issue_to_2stock_entry(self):
		from erpnext.stock.doctype.stock_entry.test_stock_entry import TestStockEntry as tse

		company = "_Test Company"
		target_warehouse = create_warehouse("_Test Warehouse", properties=None, company=company)
		mr = make_material_request(material_request_type="Material Issue", qty=10, warehouse=target_warehouse, item="_Test Item")
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
			"from_warehouse": args.from_warehouse or ""
		},
	)
	mr.insert()
	if not args.do_not_submit:
		mr.submit()
	return mr


test_dependencies = ["Currency Exchange", "BOM"]
test_records = frappe.get_test_records("Material Request")
