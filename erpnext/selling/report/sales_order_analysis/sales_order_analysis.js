// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Sales Order Analysis"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			width: "80",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_default("company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			width: "80",
			reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			on_change: (report) => {
				report.set_filter_value("sales_order", []);
				report.refresh();
			},
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			width: "80",
			reqd: 1,
			default: frappe.datetime.get_today(),
			on_change: (report) => {
				report.set_filter_value("sales_order", []);
				report.refresh();
			},
		},
		{
			fieldname: "sales_order",
			label: __("Sales Order"),
			fieldtype: "MultiSelectList",
			width: "80",
			options: "Sales Order",
			get_data: function (txt) {
				let filters = { docstatus: 1 };

				const from_date = frappe.query_report.get_filter_value("from_date");
				const to_date = frappe.query_report.get_filter_value("to_date");
				if (from_date && to_date) filters["transaction_date"] = ["between", [from_date, to_date]];

				return frappe.db.get_link_options("Sales Order", txt, filters);
			},
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
		},
		{
			fieldname: "status",
			label: __("Include Status"),
			fieldtype: "MultiSelectList",
			options: ["To Pay", "To Bill", "To Deliver", "To Deliver and Bill", "Completed", "Closed"],
			width: "120",
			get_data: function(txt) {
				let status = ["To Pay", "To Bill", "To Deliver", "To Deliver and Bill", "Completed", "Closed"];
				let excluded_statuses = frappe.query_report.get_filter_value('exclude_status') || [];
				let options = [];
				for (let option of status) {
					if (!excluded_statuses.includes(option)) {
						options.push({
							value: option,
							label: __(option),
							description: ""
						});
					}
				}
				return options;
			},
			on_change: function() {
				frappe.query_report.refresh();
			}
		},
		
		{
			fieldname: "exclude_status",
			label: __("Exclude Status"),
			fieldtype: "MultiSelectList",
			options: ["To Pay", "To Bill", "To Deliver", "To Deliver and Bill", "Completed", "Closed", "Stopped", "On Hold"],
			width: "120",
			get_data: function(txt) {
				let status = ["To Pay", "To Bill", "To Deliver", "To Deliver and Bill", "Completed", "Closed", "Stopped", "On Hold"];
				let included_statuses = frappe.query_report.get_filter_value('status') || [];
				let options = [];
				for (let option of status) {
					if (!included_statuses.includes(option)) {
						options.push({
							value: option,
							label: __(option),
							description: ""
						});
					}
				}
				return options;
			},
			on_change: function() {
				frappe.query_report.refresh();
			}
		},
		{
			fieldname: "group_by_so",
			label: __("Group by Sales Order"),
			fieldtype: "Check",
			default: 0,
		}	
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		let format_fields = ["delivered_qty", "billed_amount"];

		if (in_list(format_fields, column.fieldname) && data && data[column.fieldname] > 0) {
			value = "<span style='color:green;'>" + value + "</span>";
		}

		if (column.fieldname == "delay" && data && data[column.fieldname] > 0) {
			value = "<span style='color:red;'>" + value + "</span>";
		}
		return value;
	},
	onload: function(report) {
		setTimeout(function() {
			report.set_filter_value("exclude_status", ["Stopped", "On Hold"]);
		}, 500);
	}
};
