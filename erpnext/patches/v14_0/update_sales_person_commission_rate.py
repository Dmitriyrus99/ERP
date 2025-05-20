import frappe
import re

def execute():
	sales_persons = frappe.get_all("Sales Person",
		fields=["commission_rate", "name"]
	)

	for sp in sales_persons:
		commission_rate = str(sp.commission_rate).replace(",", ".")
		if not re.fullmatch(r'^[0-9]+(\.[0-9]+)?$', str(commission_rate)):
			commission_rate = None
		frappe.db.set_value("Sales Person", sp.name, "commission_rate", commission_rate)
