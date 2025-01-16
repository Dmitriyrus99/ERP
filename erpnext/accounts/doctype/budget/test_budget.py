# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe
from frappe.utils import now_datetime, nowdate

from erpnext.accounts.doctype.budget.budget import BudgetError, get_actual_expense
from erpnext.accounts.doctype.journal_entry.test_journal_entry import make_journal_entry
from erpnext.accounts.utils import get_fiscal_year
from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order

test_dependencies = ["Monthly Distribution"]


class TestBudget(unittest.TestCase):
	def test_monthly_budget_crossed_ignore(self):
		set_total_expense_zero(nowdate(), "cost_center")

		budget = make_budget(budget_against="Cost Center")

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			40000,
			"_Test Cost Center - _TC",
			posting_date=nowdate(),
			submit=True,
		)

		self.assertTrue(
			frappe.db.get_value("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": jv.name})
		)

		budget.cancel()
		jv.cancel()

	def test_monthly_budget_crossed_stop1(self):
		set_total_expense_zero(nowdate(), "cost_center")

		budget = make_budget(budget_against="Cost Center")

		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			40000,
			"_Test Cost Center - _TC",
			posting_date=nowdate(),
		)

		self.assertRaises(BudgetError, jv.submit)

		budget.load_from_db()
		budget.cancel()

	def test_exception_approver_role(self):
		set_total_expense_zero(nowdate(), "cost_center")

		budget = make_budget(budget_against="Cost Center")

		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			40000,
			"_Test Cost Center - _TC",
			posting_date=nowdate(),
		)

		self.assertRaises(BudgetError, jv.submit)

		frappe.db.set_value("Company", budget.company, "exception_budget_approver_role", "Accounts User")

		jv.submit()
		self.assertEqual(frappe.db.get_value("Journal Entry", jv.name, "docstatus"), 1)
		jv.cancel()

		frappe.db.set_value("Company", budget.company, "exception_budget_approver_role", "")

		budget.load_from_db()
		budget.cancel()

	def test_monthly_budget_crossed_for_mr(self):
		budget = make_budget(
			applicable_on_material_request=1,
			applicable_on_purchase_order=1,
			action_if_accumulated_monthly_budget_exceeded_on_mr="Stop",
			budget_against="Cost Center",
		)

		fiscal_year = get_fiscal_year(nowdate())[0]
		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")
		frappe.db.set_value("Budget", budget.name, "fiscal_year", fiscal_year)

		mr = frappe.get_doc(
			{
				"doctype": "Material Request",
				"material_request_type": "Purchase",
				"transaction_date": nowdate(),
				"company": budget.company,
				"items": [
					{
						"item_code": "_Test Item",
						"qty": 1,
						"uom": "_Test UOM",
						"warehouse": "_Test Warehouse - _TC",
						"schedule_date": nowdate(),
						"rate": 100000,
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"cost_center": "_Test Cost Center - _TC",
					}
				],
			}
		)

		mr.set_missing_values()

		self.assertRaises(BudgetError, mr.submit)

		budget.load_from_db()
		budget.cancel()

	def test_monthly_budget_crossed_for_po(self):
		budget = make_budget(
			applicable_on_purchase_order=1,
			action_if_accumulated_monthly_budget_exceeded_on_po="Stop",
			budget_against="Cost Center",
		)

		fiscal_year = get_fiscal_year(nowdate())[0]
		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")
		frappe.db.set_value("Budget", budget.name, "fiscal_year", fiscal_year)

		po = create_purchase_order(transaction_date=nowdate(), do_not_submit=True)

		po.set_missing_values()

		self.assertRaises(BudgetError, po.submit)

		budget.load_from_db()
		budget.cancel()
		po.cancel()

	def test_monthly_budget_crossed_stop2(self):
		set_total_expense_zero(nowdate(), "project")

		budget = make_budget(budget_against="Project")

		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")

		project = frappe.get_value("Project", {"project_name": "_Test Project"})

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			40000,
			"_Test Cost Center - _TC",
			project=project,
			posting_date=nowdate(),
		)

		self.assertRaises(BudgetError, jv.submit)

		budget.load_from_db()
		budget.cancel()

	def test_yearly_budget_crossed_stop1(self):
		set_total_expense_zero(nowdate(), "cost_center")

		budget = make_budget(budget_against="Cost Center")

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			250000,
			"_Test Cost Center - _TC",
			posting_date=nowdate(),
		)

		self.assertRaises(BudgetError, jv.submit)

		budget.cancel()

	def test_yearly_budget_crossed_stop2(self):
		set_total_expense_zero(nowdate(), "project")

		budget = make_budget(budget_against="Project")

		project = frappe.get_value("Project", {"project_name": "_Test Project"})

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			250000,
			"_Test Cost Center - _TC",
			project=project,
			posting_date=nowdate(),
		)

		self.assertRaises(BudgetError, jv.submit)

		budget.cancel()

	def test_monthly_budget_on_cancellation1(self):
		set_total_expense_zero(nowdate(), "cost_center")

		budget = make_budget(budget_against="Cost Center")
		month = now_datetime().month
		if month > 9:
			month = 9

		for _i in range(month + 1):
			jv = make_journal_entry(
				"_Test Account Cost for Goods Sold - _TC",
				"_Test Bank - _TC",
				20000,
				"_Test Cost Center - _TC",
				posting_date=nowdate(),
				submit=True,
			)

			self.assertTrue(
				frappe.db.get_value("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": jv.name})
			)

		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")

		self.assertRaises(BudgetError, jv.cancel)

		budget.load_from_db()
		budget.cancel()

	def test_monthly_budget_on_cancellation2(self):
		set_total_expense_zero(nowdate(), "project")

		budget = make_budget(budget_against="Project")
		month = now_datetime().month
		if month > 9:
			month = 9

		project = frappe.get_value("Project", {"project_name": "_Test Project"})
		for _i in range(month + 1):
			jv = make_journal_entry(
				"_Test Account Cost for Goods Sold - _TC",
				"_Test Bank - _TC",
				20000,
				"_Test Cost Center - _TC",
				posting_date=nowdate(),
				submit=True,
				project=project,
			)

			self.assertTrue(
				frappe.db.get_value("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": jv.name})
			)

		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")

		self.assertRaises(BudgetError, jv.cancel)

		budget.load_from_db()
		budget.cancel()

	def test_monthly_budget_against_group_cost_center(self):
		set_total_expense_zero(nowdate(), "cost_center")
		set_total_expense_zero(nowdate(), "cost_center", "_Test Cost Center 2 - _TC")

		budget = make_budget(budget_against="Cost Center", cost_center="_Test Company - _TC")
		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			40000,
			"_Test Cost Center 2 - _TC",
			posting_date=nowdate(),
		)

		self.assertRaises(BudgetError, jv.submit)

		budget.load_from_db()
		budget.cancel()

	def test_monthly_budget_against_parent_group_cost_center(self):
		cost_center = "_Test Cost Center 3 - _TC"

		if not frappe.db.exists("Cost Center", cost_center):
			frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": "_Test Cost Center 3",
					"parent_cost_center": "_Test Company - _TC",
					"company": "_Test Company",
					"is_group": 0,
				}
			).insert(ignore_permissions=True)

		budget = make_budget(budget_against="Cost Center", cost_center=cost_center)
		frappe.db.set_value("Budget", budget.name, "action_if_accumulated_monthly_budget_exceeded", "Stop")

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			40000,
			cost_center,
			posting_date=nowdate(),
		)

		self.assertRaises(BudgetError, jv.submit)

		budget.load_from_db()
		budget.cancel()
		jv.cancel()

	def test_monthly_budget_against_main_cost_center(self):
		from erpnext.accounts.doctype.cost_center.test_cost_center import create_cost_center
		from erpnext.accounts.doctype.cost_center_allocation.test_cost_center_allocation import (
			create_cost_center_allocation,
		)

		cost_centers = [
			"Main Budget Cost Center 1",
			"Sub Budget Cost Center 1",
			"Sub Budget Cost Center 2",
		]

		for cc in cost_centers:
			create_cost_center(cost_center_name=cc, company="_Test Company")

		create_cost_center_allocation(
			"_Test Company",
			"Main Budget Cost Center 1 - _TC",
			{"Sub Budget Cost Center 1 - _TC": 60, "Sub Budget Cost Center 2 - _TC": 40},
		)

		make_budget(budget_against="Cost Center", cost_center="Main Budget Cost Center 1 - _TC")

		jv = make_journal_entry(
			"_Test Account Cost for Goods Sold - _TC",
			"_Test Bank - _TC",
			400000,
			"Main Budget Cost Center 1 - _TC",
			posting_date=nowdate(),
		)

		self.assertRaises(BudgetError, jv.submit)

	def test_provisional_entry_for_service_items_TC_ACC_064(self):
		# Step 1: Enable Provisional Accounting in Company Master
		company = "_Test Company"
		frappe.db.set_value("Company", company, "enable_provisional_accounting_for_non_stock_items", 1)
		# Set _Test Cash - _TC as the Provisional Account
		frappe.db.set_value("Company", company, "default_provisional_account", "_Test Cash - _TC")

		# Step 3: Create a Service Item
		service_item = frappe.get_doc({
			"doctype": "Item",
			"item_code": "_Test Non Stock Item",
			"item_group": "Services",
			"is_stock_item": 0
		})
		if not frappe.db.exists("Item", service_item.item_code):
			service_item.insert(ignore_permissions=True)

		pr = None  # Initialize 'pr' to avoid UnboundLocalError
		try:
			# Step 4: Create a Purchase Receipt with the Service Item
			from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import make_purchase_receipt
			pr = make_purchase_receipt(
				company=company,
				item=service_item.item_code,
				rate=1000,
				qty=1,
				expense_account="_Test Account Cost for Goods Sold - _TC"
			)

			# Step 5: Validate GL Entries
			gl_entries = frappe.get_all("GL Entry", filters={"voucher_no": pr.name}, fields=["account", "debit", "credit"])

			# Check GL Entries
			expected_entries = [
				{"account": "_Test Account Cost for Goods Sold - _TC", "debit": 1000.0, "credit": 0.0},
				{"account": "_Test Cash - _TC", "debit": 0.0, "credit": 1000.0}
			]
			for entry in expected_entries:
				self.assertIn(entry, gl_entries, msg=f"Expected GL Entry {entry} not found in {gl_entries}")

			print(f"Provisional Accounting validated for {pr.name}")

		finally:
			# Step 6: Cleanup
			if pr and pr.docstatus == 1:
				pr.cancel()
			if pr:
				frappe.delete_doc("Purchase Receipt", pr.name, force=True)
			frappe.delete_doc("Item", service_item.name, force=True)

			# Reset Company Settings
			frappe.db.set_value("Company", company, "enable_provisional_accounting_for_non_stock_items", 0)
			frappe.db.set_value("Company", company, "default_provisional_account", "")

def set_total_expense_zero(posting_date, budget_against_field=None, budget_against_CC=None):
	if budget_against_field == "project":
		budget_against = frappe.db.get_value("Project", {"project_name": "_Test Project"})
	else:
		budget_against = budget_against_CC or "_Test Cost Center - _TC"

	fiscal_year = get_fiscal_year(nowdate())[0]

	args = frappe._dict(
		{
			"account": "_Test Account Cost for Goods Sold - _TC",
			"cost_center": "_Test Cost Center - _TC",
			"monthly_end_date": posting_date,
			"company": "_Test Company",
			"fiscal_year": fiscal_year,
			"budget_against_field": budget_against_field,
		}
	)

	if not args.get(budget_against_field):
		args[budget_against_field] = budget_against

	existing_expense = get_actual_expense(args)

	if existing_expense:
		if budget_against_field == "cost_center":
			make_journal_entry(
				"_Test Account Cost for Goods Sold - _TC",
				"_Test Bank - _TC",
				-existing_expense,
				"_Test Cost Center - _TC",
				posting_date=nowdate(),
				submit=True,
			)
		elif budget_against_field == "project":
			make_journal_entry(
				"_Test Account Cost for Goods Sold - _TC",
				"_Test Bank - _TC",
				-existing_expense,
				"_Test Cost Center - _TC",
				submit=True,
				project=budget_against,
				posting_date=nowdate(),
			)


def make_budget(**args):
	args = frappe._dict(args)

	budget_against = args.budget_against
	cost_center = args.cost_center

	fiscal_year = get_fiscal_year(nowdate())[0]

	if budget_against == "Project":
		project_name = "{}%".format("_Test Project/" + fiscal_year)
		budget_list = frappe.get_all("Budget", fields=["name"], filters={"name": ("like", project_name)})
	else:
		cost_center_name = "{}%".format(cost_center or "_Test Cost Center - _TC/" + fiscal_year)
		budget_list = frappe.get_all("Budget", fields=["name"], filters={"name": ("like", cost_center_name)})
	for d in budget_list:
		frappe.db.sql("delete from `tabBudget` where name = %(name)s", d)
		frappe.db.sql("delete from `tabBudget Account` where parent = %(name)s", d)

	budget = frappe.new_doc("Budget")

	if budget_against == "Project":
		budget.project = frappe.get_value("Project", {"project_name": "_Test Project"})
	else:
		budget.cost_center = cost_center or "_Test Cost Center - _TC"

	monthly_distribution = frappe.get_doc("Monthly Distribution", "_Test Distribution")
	monthly_distribution.fiscal_year = fiscal_year

	budget.fiscal_year = fiscal_year
	budget.monthly_distribution = "_Test Distribution"
	budget.company = "_Test Company"
	budget.applicable_on_booking_actual_expenses = 1
	budget.action_if_annual_budget_exceeded = "Stop"
	budget.action_if_accumulated_monthly_budget_exceeded = "Ignore"
	budget.budget_against = budget_against
	wbs_name = setup_test_wbs()
	budget.append("accounts", {"account": "_Test Account Cost for Goods Sold - _TC", "budget_amount": 200000,"child_wbs":wbs_name})

	if args.applicable_on_material_request:
		budget.applicable_on_material_request = 1
		budget.action_if_annual_budget_exceeded_on_mr = args.action_if_annual_budget_exceeded_on_mr or "Warn"
		budget.action_if_accumulated_monthly_budget_exceeded_on_mr = (
			args.action_if_accumulated_monthly_budget_exceeded_on_mr or "Warn"
		)

	if args.applicable_on_purchase_order:
		budget.applicable_on_purchase_order = 1
		budget.action_if_annual_budget_exceeded_on_po = args.action_if_annual_budget_exceeded_on_po or "Warn"
		budget.action_if_accumulated_monthly_budget_exceeded_on_po = (
			args.action_if_accumulated_monthly_budget_exceeded_on_po or "Warn"
		)

	budget.insert()
	budget.submit()

	return budget

# Setup test project
def setup_test_project():
	desired_company = "_Test Company"
	# Check if a project with the same name exists for the desired company
	existing_project = frappe.get_all("Project", filters={"project_name": "_Test Company Project", "company": desired_company})
	if not existing_project:
		# Create a new project for the desired company
		project = frappe.new_doc("Project")
		project.project_name = "_Test Company Project"
		project.company = desired_company
		project.status = "Open"
		project.is_active = 'Yes'
		project.is_wbs = 1
		project.start_date = nowdate()
		project.save().submit()
		return project.name
	else:
		return existing_project

# Setup test WBS
def setup_test_wbs():
	setup_test_project()
	return frappe.get_last_doc("Work Breakdown Structure")
