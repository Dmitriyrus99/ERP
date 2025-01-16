// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt
frappe.ui.form.on("Project", {
	setup(frm) {
		frm.make_methods = {
			'Timesheet': () => {
				open_form(frm, "Timesheet", "Timesheet Detail", "time_logs");
			},
			'Purchase Order': () => {
				open_form(frm, "Purchase Order", "Purchase Order Item", "items");
			},
			'Purchase Receipt': () => {
				open_form(frm, "Purchase Receipt", "Purchase Receipt Item", "items");
			},
			'Purchase Invoice': () => {
				open_form(frm, "Purchase Invoice", "Purchase Invoice Item", "items");
			},
		};
	},
	onload: function (frm) {
		const so = frm.get_docfield("sales_order");
		so.get_route_options_for_new_doc = () => {
			if (frm.is_new()) return {};
			return {
				"customer": frm.doc.customer,
				"project_name": frm.doc.name
			};
		};

		frm.set_query('customer', 'erpnext.controllers.queries.customer_query');

		frm.set_query("user", "users", function () {
			return {
				query: "erpnext.projects.doctype.project.project.get_users_for_project"
			};
		});

		// sales order
		frm.set_query('sales_order', function () {
			var filters = {
				'project': ["in", frm.doc.__islocal ? [""] : [frm.doc.name, ""]]
			};

			if (frm.doc.customer) {
				filters["customer"] = frm.doc.customer;
			}

			return {
				filters: filters
			};
		});

		frm.set_query('quotations', function () {
			var filters = [
				['status', '=', 'Draft']
			]

			return {
				filters,
			}
		})

		frm.set_query('sales_invoice', function () {
			const filters = [
				['status', '=', 'Unpaid']
			]
			return { filters }
		})

		frappe.realtime.off("docinfo_update");
		frappe.realtime.on('docinfo_update', (data) => {
			if (data.key === "attachment_logs") {
				insertCarousel(frm)
			}
		})

		const sidebar = $(".layout-side-section");

		if (sidebar.is(':visible')) {
			sidebar.hide();
		}
	},

	refresh: async function (frm) {
		if (frm.doc.__islocal) {
			frm.web_link && frm.web_link.remove();
		} else {
			frm.add_web_link("/projects?project=" + encodeURIComponent(frm.doc.name));
			frm.trigger('show_dashboard');
		}

		if (!frm.is_new()) {
			frm.add_custom_button(__("Create quotation"), async () => {
				const doc = await frappe.model.get_new_doc('Quotation');
				doc.party_name = frm.doc.customer;
				frappe.new_doc('Quotation', {
					project_name: frm.doc.name,
					party_name: frm.doc.customer,
					quotation_to: 'Customer'
				});
			})
			frm.add_custom_button(__("Customer info"), async () => {
				const customer = await frappe.db.get_doc('Customer', frm.doc.customer)
				const linked_contacts_and_addresses = await frappe.db.get_list(
					"Address",
					{
						filters: [
							["disabled", "=", 0],
							["address_type", "in", ["Billing", "Shipping"]],
							["Dynamic Link", "link_doctype", "=", "Customer"],
							["Dynamic Link", "link_name", "=", `${frm.doc.customer}`],
							["Dynamic Link", "parenttype", "=", "Address"]
						],
						fields: ["address_line1", "address_line2", "country", "city", "pincode", "state", "address_type"]
					}
				);


				let billingAddress = null;
				let shippingAddress = null;

				// Find the first Billing and Shipping address
				for (let address of linked_contacts_and_addresses) {
					if (address.address_type === 'Billing' && !billingAddress) {
						billingAddress = address;
					} else if (address.address_type === 'Shipping' && !shippingAddress) {
						shippingAddress = address;
					}

					// Exit the loop if both addresses are found
					if (billingAddress && shippingAddress) {
						break;
					}
				}

				let addresses_info = '';
				if (billingAddress) {
					addresses_info += `
						<br><b>Address Type: Billing</b><br>
						Address Line 1: ${billingAddress.address_line1}<br>
						Address Line 2: ${billingAddress.address_line2 || 'N/A'}<br>
						Country: ${billingAddress.country}<br>
						City: ${billingAddress.city}<br>
						Postal Code: ${billingAddress.pincode || 'N/A'}<br>
						State/Province: ${billingAddress.state}<br>
					`;
				}

				if (shippingAddress) {
					addresses_info += `
						<br><b>Address Type: Shipping</b><br>
						Address Line 1: ${shippingAddress.address_line1}<br>
						Address Line 2: ${shippingAddress.address_line2 || 'N/A'}<br>
						Country: ${shippingAddress.country}<br>
						City: ${shippingAddress.city}<br>
						Postal Code: ${shippingAddress.pincode || 'N/A'}<br>
						State/Province: ${shippingAddress.state}<br>
					`;
				}

				frappe.msgprint({
					title: __('Customer Information'),
					indicator: 'green',
					message: __(
						`Name: ${customer.name || 'No name provided'}<br>` +
						`Phone: ${customer.phone_number || customer.mobile_no || 'No phone number provided'}<br>` +
						`Email: ${customer.email_id || 'No email provided'}<br><br>` +
						`Addresses: ${addresses_info || 'No addresses found'}`
					)
				});
			})
		}

		installChat(frm);
		installQuotationItems(frm)
		insertCarousel(frm);
		insertVinSearchButton(frm)
		insertResendPaymentLink(frm);
		frm.trigger("set_custom_buttons");
	},
	create_duplicate: function (frm) {
		return new Promise(resolve => {
			frappe.prompt('Project Name', (data) => {
				frappe.xcall('erpnext.projects.doctype.project.project.create_duplicate_project',
					{
						prev_doc: frm.doc,
						project_name: data.value
					}).then(() => {
						frappe.set_route('Form', "Project", data.value);
						frappe.show_alert(__("Duplicate project has been created"));
					});
				resolve();
			});
		});
	},

	set_status: function (frm, status) {
		frappe.confirm(__('Set Project and all Tasks to status {0}?', [status.bold()]), () => {
			frappe.xcall('erpnext.projects.doctype.project.project.set_project_status',
				{ project: frm.doc.name, status: status }).then(() => {
					frm.reload_doc();
				});
		});
	},
	status: async function (frm) {
		let new_value = frm.doc.status;

		if (new_value !== "Quality check approved") return

		const incomplete_requirements = frm.doc.requirements.filter(requirement => !requirement.completed)

		const quotations = await frappe.db.get_list("Quotation", {
			filters: [
				['project_name', '=', frm.docname],
				['status', "!=", "Approved"]
			],
			fields: ["name", "status"]
		})

		if (!quotations?.length && !incomplete_requirements.length) return

		showConfirmationDialog(frm, quotations, incomplete_requirements)
	}
});

function showConfirmationDialog(frm, quotations, incomplete_requirements) {
	const dialog = new frappe.ui.Dialog({
		title: 'Confirm',
		fields: buildFields(frm, quotations, incomplete_requirements),
		primary_action_label: 'Confirm',
		primary_action: function () {
			dialog.hide();
		},
		secondary_action_label: 'Cancel',
		secondary_action: function () {
			frm.undo_manager.undo();
			dialog.hide();
		}
	});

	dialog.$wrapper.find('.modal-header .modal-actions').hide();
	dialog.$wrapper.modal({ backdrop: 'static', keyboard: false })

	dialog.show();
}

function buildFields(frm, quotations, incomplete_requirements) {
	const quotation_fields = [
		{
			fieldtype: 'HTML',
			options: `<h3>Pending Quotations</h3> `
		},
		{
			fieldtype: 'HTML',
			options: `<p>Client <a href="/app/customer/${frm.doc.customer}"><strong>${frm.doc.customer}</strong></a> with project <strong>${frm.docname}</strong> has the following quotation pending approval:</p> `
		},
		{
			fieldtype: 'HTML',
			options: `
				<ul style="border-bottom: 1px solid black;padding-bottom:1rem;">
				${quotations.map(quotation => `<li><strong>Quotation:</strong> <a href="/app/quotation/${quotation.name}" target="__blank">${quotation.name}</a>, <strong>Status:</strong> ${quotation.status}.</li>\n`)}
				</ul> 
			`
		}
	]
	const requirements_fields = [
		{
			fieldtype: 'HTML',
			options: `<h3>Incomplete Client Requirements</h3> `
		},
		{
			fieldtype: 'HTML',
			options: `
				<ul>
				${incomplete_requirements.map(item => `<li><strong>Requirement:</strong> ${item.requirement}</li>\n`)}
				</ul> 
			`
		},
	]
	const question_field = {
		fieldtype: 'HTML',
		options: `
			<p>Are you sure you want to proceed? ${quotations.length ? "The quotations listed will not be included in the invoice" : ""}</p>
		`
	}

	let fields = []

	if (quotations.length) {
		fields.push(...quotation_fields)
	}

	if (incomplete_requirements.length) {
		fields.push(...requirements_fields)
	}

	fields.push(question_field)

	return fields
}

let instaling = false;
async function installChat(frm) {
	if (document.querySelector('#chat-container')) {
		document.querySelector('#chat-container').remove();
	}
	frm.page.container.removeClass("full-width");
	if (instaling) return;
	instaling = true;
	if (!frm.is_new()) {
		const { 0: conversation } = await frappe.db.get_list('Conversation', {
			filters: [['from', '=', frm.doc.custom_customers_phone_number]],
			fields: ["*"]
		});

		if (!conversation) {
			instaling = false;
			return;
		};
		const chatContainer = document.createElement('div')

		const button = document.createElement('button')
		button.classList.add('btn', 'btn-default', 'ellipsis')
		button.textContent = 'Toggle WhatsApp'
		button.addEventListener('click', () => {
			if (chatContainer.style.display === 'none') {
				chatContainer.style.display = 'block';
			} else {
				chatContainer.style.display = 'none';
			}
		})

		document.querySelector('#custom_actions')
			.innerHTML = '';
		document.querySelector('#custom_actions')
			.appendChild(button)

		chatContainer.id = 'chat-container'
		const chat = document.createElement('erp-chat')
		const section = document.querySelector('#page-Project > div.container.page-body > div.page-wrapper > div > div.row.layout-main')

		const { aws_url } = await frappe.db.get_doc('Whatsapp Config')
		chat.setAttribute('url', aws_url)
		chat.setAttribute('user-name', frappe.user_info().fullname)

		frappe.realtime.on(`msg-${conversation.name}`, (data) => {
			chat._instance.exposed.addMessage(data);
		})
		frappe.realtime.on(`translation-${frm.doc.name}`, (data) => {
			console.log('on Translate')
			chat._instance.exposed.onTranslate(data);
		})
		frappe.require('erp-whatsapp-chat.bundle.js')
			.then(() => {
				chatContainer.appendChild(chat)
				section.appendChild(chatContainer)
				setTimeout(() => {
					chat._instance.exposed.setFrappe(frappe)
					chat._instance.exposed.setConversation(conversation)
				}, 100);
			})


		frm.page.container.addClass("full-width");
	}
	instaling = false;
}

let is_quotation_installed = false;
function installQuotationItems(frm) {
	if (frm.is_new()) return;
	if (is_quotation_installed) return;

	const container = document.querySelector('div[data-fieldname="customer_details"] .section-body');
	if (!container) {
		return;
	}

	// Eliminar el componente existente si está presente
	const existingComponent = container.querySelector("erp-quotation-items");
	if (existingComponent) {
		existingComponent.remove();
	}

	is_quotation_installed = true;

	// Crear un contenedor adicional para manejar el desbordamiento
	const wrapper = document.createElement("div");
	wrapper.style.width = '100%';  // Ajusta al tamaño del contenedor
	wrapper.style.overflow = 'auto';  // Permite el scroll si es necesario

	frappe.require("erp-quotation-items.bundle.js").then(() => {
		const element = document.createElement("erp-quotation-items");
		element.style.width = '100%';  // Asegura que el componente no exceda el contenedor
		element.style.maxWidth = '100%';  // Evita que el componente se expanda más allá del contenedor
		element.style.boxSizing = 'border-box';  // Incluye padding y border en el ancho total
		element.style.display = 'block';  // Asegura que el componente se comporte como un bloque

		// Añadir el componente al contenedor wrapper
		wrapper.appendChild(element);
		container.appendChild(wrapper);

		// Forzar un redibujado del contenedor
		container.style.overflow = 'hidden';  // Establecer overflow a hidden
		container.offsetHeight;  // Forzar un reflujo
		container.style.overflow = 'auto';  // Restaurar overflow a auto

		setTimeout(() => {
			element._instance.exposed.setFrappe(frappe);
			element._instance.exposed.setProjectName(frm.doc.name);
			element._instance.exposed.setUserSession(frappe.session)
			is_quotation_installed = false;
		}, 100);
	}).catch((err) => {
		console.error("Error loading erp-quotation-items", err);
		is_quotation_installed = false;
	});
}

function open_form(frm, doctype, child_doctype, parentfield) {
	frappe.model.with_doctype(doctype, () => {
		let new_doc = frappe.model.get_new_doc(doctype);

		// add a new row and set the project
		let new_child_doc = frappe.model.get_new_doc(child_doctype);
		new_child_doc.project = frm.doc.name;
		new_child_doc.parent = new_doc.name;
		new_child_doc.parentfield = parentfield;
		new_child_doc.parenttype = doctype;
		new_doc[parentfield] = [new_child_doc];
		new_doc.project = frm.doc.name;

		frappe.ui.form.make_quick_entry(doctype, null, null, new_doc);
	});

}

let touchTimeout;
async function insertCarousel(frm) {
	frappe.require('glider.bundle.js', () => {
		setTimeout(() => {
			frappe.db.get_list("File", {
				filters: [
					['attached_to_name', 'in', frm.doc.name],
					['attached_to_doctype', '=', "Project"]
				],
				fields: ["file_url", "file_type"],
				limit: 10
			}).then((attachments) => {
				const tracker = document.querySelector('.glider-track')
				const container = document.querySelector('.glider-contain')
				const gliderEl = document.querySelector('.glider')

				if (!gliderEl) return null

				const glider = new Glider(gliderEl, {
					slidesToShow: 1,
					draggable: true,
					dots: '.dots',
					arrows: {
						prev: '.glider-prev',
						next: '.glider-next'
					},
					responsive: [
						{
							breakpoint: 600,
							settings: {
								slidesToShow: 2,
								slidesToScroll: 2,
								duration: 0.25
							}
						}, {
							breakpoint: 1024,
							settings: {
								slidesToShow: 5,
								slidesToScroll: 5,
								duration: 0.25
							}
						}
					]
				})

				//remove all items
				if (tracker && glider) {
					for (let index = 0; index < tracker.childElementCount; index++) {
						glider.removeItem(index)
					}
				}

				if (attachments && attachments.length > 0 && glider) {
					container.style = 'height: auto;overflow:hidden;'

					for (const attachment of attachments) {
						const el = createAttachmentElement(attachment)
						if (el) {
							setListeners(el, attachment)
							glider.addItem(el)
						}
					}

				} else {
					container.style = 'height: 0;overflow:hidden;'
					console.log('No attachments found for this project.');
				}
			})
		}, 3000)// if this time is less than 3 sec it'll be render a wrong carousel
	})
}

function setListeners(el, attachment) {
	let element = el

	if (attachment.file_type === "MOV" || attachment.file_type === "MP4") return null
	if (attachment.file_type === 'PDF' || attachment.file_url === 'TXT') {
		element = el.querySelector('#touch-overlay')
	}
	element.addEventListener('touchstart', (e) => handleTouchStart(e, attachment))
	element.addEventListener('touchend', handleTouchEnd)

}

function createAttachmentElement(attachment) {
	let el;

	switch (attachment.file_type) {
		case "PDF":
		case "TXT":
			el = document.createElement('div')
			el.style = `width: 100%;overflow: hidden; position: relative;`
			el.innerHTML = `<iframe src="${attachment.file_url}" frameborder="0" class="glider-iframe"></iframe> <div id="touch-overlay"></div>`
			break;
		case "MOV":
		case "MP4":
			el = document.createElement('video')
			el.className = 'video-container'
			el.setAttribute('controls', 'true')
			el.setAttribute('src', attachment.file_url)
			break;
		default:
			el = document.createElement('img')
			el.setAttribute('src', attachment.file_url)
	}

	return el
}


function handleTouchStart(e, attachment) {
	touchTimeout = setTimeout(() => {
		const attachmentContainer = document.querySelector('#selected-attachment')
		const el = createAttachmentElement(attachment)
		attachmentContainer.addEventListener('touchend', handleTouchEnd)
		attachmentContainer.appendChild(el)
		attachmentContainer.removeAttribute('hidden')
	}, 1000)
}

function handleTouchEnd(e) {
	clearTimeout(touchTimeout)
	const attachmentContainer = document.querySelector('#selected-attachment')
	if (attachmentContainer) {
		attachmentContainer.innerHTML = ``
		attachmentContainer.setAttribute('hidden', "true")
	}
}

async function insertVinSearchButton(frm) {
	const container = document.querySelector('div[data-fieldname="vin"] .form-group .clearfix');

	if (!container || document.getElementById('vinSearch')) {
		return;
	}

	const button = document.createElement('button');
	button.id = 'vinSearch';
	button.style = 'border:none;background:black;padding:2px;color:white;border-radius:5px;position:relative;'

	const tooltip = document.createElement('span');
	tooltip.textContent = "Vin Search";
	tooltip.style = 'font-size:12px;background:#171717;color:white;padding:4px;border-radius:4px;opacity:0;transition:opacity 0.3s;position:absolute;margin-left:4px;'

	const spinner = document.createElement('div')
	spinner.setAttribute('hidden', 'true')
	spinner.classList = 'vin-search-spinner'

	const iconSpan = document.createElement('span');
	iconSpan.innerHTML = `
	<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none" fill-rule="evenodd">
		<path d="m12.593 23.258l-.011.002l-.071.035l-.02.004l-.014-.004l-.071-.035q-.016-.005-.024.005l-.004.01l-.017.428l.005.02l.01.013l.104.074l.015.004l.012-.004l.104-.074l.012-.016l.004-.017l-.017-.427q-.004-.016-.017-.018m.265-.113l-.013.002l-.185.093l-.01.01l-.003.011l.018.43l.005.012l.008.007l.201.093q.019.005.029-.008l.004-.014l-.034-.614q-.005-.018-.02-.022m-.715.002a.02.02 0 0 0-.027.006l-.006.014l-.034.614q.001.018.017.024l.015-.002l.201-.093l.01-.008l.004-.011l.017-.43l-.003-.012l-.01-.01z"/><path fill="currentColor" d="M10.5 4a6.5 6.5 0 1 0 0 13a6.5 6.5 0 0 0 0-13M2 10.5a8.5 8.5 0 1 1 15.176 5.262l3.652 3.652a1 1 0 0 1-1.414 1.414l-3.652-3.652A8.5 8.5 0 0 1 2 10.5M9.5 7a1 1 0 0 1 1-1a4.5 4.5 0 0 1 4.5 4.5a1 1 0 1 1-2 0A2.5 2.5 0 0 0 10.5 8a1 1 0 0 1-1-1"/></g>
	</svg>
	`;

	button.addEventListener('mouseover', () => {
		tooltip.style.visibility = 'visible';
		tooltip.style.opacity = '1';
	});

	button.addEventListener('mouseout', () => {
		tooltip.style.visibility = 'hidden';
		tooltip.style.opacity = '0';
	});

	button.addEventListener('click', async function () {
		button.setAttribute('hidden', 'true')
		spinner.removeAttribute('hidden')
		const { vin_search_url } = await frappe.db.get_doc('Vin Search')

		const data = await fetch(`${vin_search_url}/${frm.doc.vin}`).then(response => response.json()).catch(error => {
			frappe.throw(__('Error', error));
		})
			.finally(() => {
				button.removeAttribute('hidden')
				spinner.setAttribute('hidden', 'true')
			});

		if (data.errors) {
			frappe.show_alert({
				message: __(`${data.errors}`),
				indicator: 'red'
			}, 5);

			if (!data.vehicle_identification_no) {
				return
			}
		}

		const partsObject = {};

		data.parts?.forEach(part => {
			partsObject[part.name] = part.partNumber;
		});

		frm.set_value({
			vin: data.vehicle_identification_no,
			model: data.model,
			model_year: data.year,
			brand: data.make,
			engine_liters: data.engine_liters,
			engine_code: data.engine_code,
			dsg_model: data.dsg_family || data.dsg ? data.dsg[0] : '',
			dsg_code: data.dsg_code,
			ecu_number: data.ecu_code,
			dsg_gearbox: partsObject["gearbox"] ?? partsObject["speed dual clutch gearbox"] ?? "",
			mechatronic: partsObject["mechatronic"] ?? partsObject["mechatronic with software"] ?? "",
			flywheel: partsObject["flywheel"] ?? "",
			clutch: partsObject["clutch"] ?? partsObject["repair set for multi-coupling"] ?? "",
		}).then(() => {
			frm.save();
		})
	});

	button.appendChild(iconSpan);
	container.appendChild(button);
	container.appendChild(tooltip);
	container.appendChild(spinner);

}

async function insertResendPaymentLink(frm) {
	if (!["Completed", "Cancelled"].includes(frm.doc.status)) {
		frm.add_custom_button(__('Resend Payment Link'), () => {
			var d = new frappe.ui.Dialog({
				title: __("The message and payment Link will be sent to the client"),
				fields: [],
				primary_action_label: __("Send"),
				primary_action: function () {
					const url = "https://40smjbggcl.execute-api.us-east-1.amazonaws.com/project/quality-approved";
					const obj = {
					"name": frm.doc.name,
					};

					console.log("Sending payload:", obj);

					fetch(url, {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
					},
					body: JSON.stringify(obj),
					})
					.then(async (response) => {
						if (!response.ok) {
						// Manejo de error basado en el estado de la respuesta
						const errorMessage = await response.text();
						throw new Error(`HTTP error ${response.status}: ${errorMessage}`);
						}
						return response.json(); // Si la respuesta tiene datos JSON
					})
					.then((data) => {
						console.log("Response data:", data);
						frappe.show_alert({
						message: __('Message sent successfully'),
						indicator: 'green'
						}, 10);
					})
					.catch((error) => {
						frappe.show_alert({
						message: __('An error occurred while sending the message'),
						indicator: 'red'
						}, 10);
						console.error('Error:', error);
					});


					d.hide();
				},
				secondary_action_label: __("Cancel"),
				secondary_action: function () {
					d.hide();
				}
			});

			d.show();
		});
	}
}

