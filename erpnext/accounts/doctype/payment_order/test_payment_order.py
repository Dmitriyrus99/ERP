# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from erpnext.accounts.doctype.bank_transaction.test_bank_transaction import (
	create_bank_account,
	create_gl_account,
)
from erpnext.accounts.doctype.payment_entry.payment_entry import (
	get_payment_entry,
	make_payment_order,
)
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
import frappe.utils


class TestPaymentOrder(FrappeTestCase):
	def setUp(self):
		# generate and use a uniq hash identifier for 'Bank Account' and it's linked GL 'Account' to avoid validation error
		uniq_identifier = frappe.generate_hash(length=10)
		self.gl_account = create_gl_account("_Test Bank " + uniq_identifier)
		self.bank_account = create_bank_account(
			gl_account=self.gl_account, bank_account_name="Checking Account " + uniq_identifier
		)

	def tearDown(self):
		frappe.db.rollback()

	def test_payment_order_creation_against_payment_entry(self):
		purchase_invoice = make_purchase_invoice()
		payment_entry = get_payment_entry(
			"Purchase Invoice", purchase_invoice.name, bank_account=self.gl_account
		)
		payment_entry.reference_no = "_Test_Payment_Order"
		payment_entry.reference_date = getdate()
		payment_entry.party_bank_account = self.bank_account
		payment_entry.insert()
		payment_entry.submit()

		doc = create_payment_order_against_payment_entry(payment_entry, "Payment Entry", self.bank_account)
		reference_doc = doc.get("references")[0]
		self.assertEqual(reference_doc.reference_name, payment_entry.name)
		self.assertEqual(reference_doc.reference_doctype, "Payment Entry")
		self.assertEqual(reference_doc.supplier, "_Test Supplier")
		self.assertEqual(reference_doc.amount, 250)

	def test_payment_order_for_purchase_invoice_TC_ACC_121(self):
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import (
			create_purchase_invoice,
			make_test_item,
		)
		from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import check_gl_entries
		from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request
		from erpnext.accounts.doctype.payment_order.payment_order import make_payment_records

		if not frappe.db.exists("Account", "_Test Bank1 - _TC"):
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_type": "Bank",
					"account_name": "_Test Bank1",
					"company": "_Test Company",
					"parent_account": "Bank Accounts - _TC",
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Bank", "_Test Bank ICIC"):
			bank=frappe.get_doc({
				"doctype": "Bank",
				"bank_name": "_Test Bank ICIC",
				"swift_number": "SWIFT12356",
			}).insert(ignore_permissions=True)
		
		if not frappe.db.exists("Bank Account", "_Test Account - _Test Bank ICIC"):
			bank = frappe.get_doc("Bank", "_Test Bank ICIC")
			bank_account=frappe.get_doc({
				"doctype": "Bank Account",
				"bank": bank.name,
				"account_name": "_Test Account",
				"is_company_account":1,
				"company": "_Test Company"
			}).insert(ignore_permissions=True)
		bank_account=frappe.get_doc("Bank Account", "_Test Account - _Test Bank ICIC")
		if not bank_account.is_company_account and bank_account.company != "_Test Company":
			bank_account.is_company_account=1
			bank_account.company="_Test Company"
			bank_account.save()
		if not bank_account.account:
			bank_account.account = "_Test Bank1 - _TC"
			bank_account.save()
		item = make_test_item("_Test Item")

		purchase_invoice = create_purchase_invoice(
			company="_Test Company",
			supplier="_Test Supplier",
			item_code=item.name,
			qty=1,
			rate=1000,
		)
		purchase_invoice.submit()
		pe=pe=make_payment_request(
			dt="Purchase Invoice",
			dn=purchase_invoice.name,
			return_doc=1,
		)
		pe.is_payment_order_required=1
		pe.bank_account=bank_account.name
		pe.save()
		pe.submit()

		doc = frappe.get_doc({
			"doctype": "Payment Order",
			"company": "_Test Company",
			"payment_order_type": "Payment Entry",
			"company_bank_account": bank_account.name,
			"references": [
				{
					"reference_doctype": "Purchase Invoice",
					"reference_name": purchase_invoice.name,
					"supplier": "_Test Supplier",
					"amount": pe.grand_total,
					"payment_request": pe.name,
					"bank_account": bank_account.name
				}
			]
		}).insert()
		doc.save().submit()
		make_payment_records(doc.name, "_Test Supplier")
		jv_name=frappe.get_value('Journal Entry Account', {'reference_type': "Purchase Invoice", 'reference_name': purchase_invoice.name}, 'parent')
		if jv_name:
			jv_doc=frappe.get_doc("Journal Entry", jv_name)
			jv_doc.company="_Test Company"
			jv_doc.cheque_no="12334"
			jv_doc.cheque_date=frappe.utils.nowdate()
			for accounts in jv_doc.accounts:
				accounts.cost_center="Main - _TC"
			jv_doc.save()	
			jv_doc.submit()
		expected_accounts = [
				['Creditors - _TC', jv_doc.total_debit, 0.0,jv_doc.posting_date],
				['_Test Bank1 - _TC', 0.0, jv_doc.total_credit,jv_doc.posting_date],
			]
		check_gl_entries(self,jv_doc.name,expected_accounts,jv_doc.posting_date,"Journal Entry")

	
def create_payment_order_against_payment_entry(ref_doc, order_type, bank_account):
	payment_order = frappe.get_doc(
		dict(
			doctype="Payment Order",
			company="_Test Company",
			payment_order_type=order_type,
			company_bank_account=bank_account,
		)
	)
	doc = make_payment_order(ref_doc.name, payment_order)
	doc.save()
	doc.submit()
	return doc
