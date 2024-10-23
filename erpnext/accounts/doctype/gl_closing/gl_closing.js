// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Gl Closing", {
// 	refresh(frm) {

// 	},
// });

frappe.ui.form.on("GL Closing", {
    refresh: function(frm) {
        if(frm.is_new()) {
            fetch_accounts(frm); 
            console.log("hellooooooooooooo")

        }
    },
    before_save:function(frm) {
    }
});

function fetch_accounts(frm) {
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Account",
            filters: {
                'is_group': 0,
                'company': frm.doc.company
            },
            fields: ["name"],
        },
        callback: function(r) {
            if (r.message) {
                frm.clear_table("gl_closing_details");
                r.message.forEach(function(account) {
                    var row = frm.add_child("gl_closing_details");
                    row.account = account.name;
                    row.closed = 1; 
                });
                frm.refresh_field("gl_closing_details");
            }
        }
    });
}
