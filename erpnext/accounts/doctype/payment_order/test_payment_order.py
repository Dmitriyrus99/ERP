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
		from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import check_gl_entries
		from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_records
		create_records("_Test Supplier")
		# Step 1: Create a Purchase Invoice
		purchase_invoice = make_purchase_invoice()
		# Step 2: Create a Payment Request
		payment_request=make_payment_request( 
			dn=purchase_invoice.name,
			dt="Purchase Invoice",
			return_doc=1,
		)
		payment_request.is_payment_order_required=1
		payment_request.save()
		payment_request.submit()

		# Step 3: Create a Payment Order
		payment_order = frappe.get_doc({
			"doctype": "Payment Order",
			"company": "_Test Company",
			"payment_order_type": "Payment Entry",
			"company_bank_account": self.bank_account,
			"references": [
				{
					"reference_doctype": "Purchase Invoice",
					"reference_name": purchase_invoice.name,
					"supplier": "_Test Supplier",
					"amount": payment_request.grand_total,
					"payment_request": payment_request.name,
					"bank_account": self.bank_account
				}
			]
		}).insert().save().submit()
		make_journal_entry(payment_order, "_Test Supplier", is_multicurrency=True)
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
				[self.gl_account, 0.0, jv_doc.total_credit,jv_doc.posting_date],
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
def make_journal_entry(doc, supplier, mode_of_payment=None, is_multicurrency=False):
	from erpnext.accounts.party import get_party_account
	je = frappe.new_doc("Journal Entry")
	je.payment_order = doc.name
	je.posting_date = frappe.utils.nowdate()
	mode_of_payment_type = frappe._dict(frappe.get_all("Mode of Payment", fields=["name", "type"], as_list=1))

	je.voucher_type = "Bank Entry"
	if mode_of_payment and mode_of_payment_type.get(mode_of_payment) == "Cash":
		je.voucher_type = "Cash Entry"
	if is_multicurrency:
		je.multi_currency = True
	paid_amt = 0
	party_account = get_party_account("Supplier", supplier, doc.company)
	for d in doc.references:
		if d.supplier == supplier and (not mode_of_payment or mode_of_payment == d.mode_of_payment):
			je.append(
				"accounts",
				{
					"account": party_account,
					"debit_in_account_currency": d.amount,
					"party_type": "Supplier",
					"party": supplier,
					"reference_type": d.reference_doctype,
					"reference_name": d.reference_name,
				},
			)

			paid_amt += d.amount
	je.append("accounts", {"account": doc.account, "credit_in_account_currency": paid_amt})

	je.flags.ignore_mandatory = True
	je.save()
