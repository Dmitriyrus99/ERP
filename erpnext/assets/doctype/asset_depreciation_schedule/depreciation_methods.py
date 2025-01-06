import frappe
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	add_years,
	cint,
	date_diff,
	flt,
	month_diff,
	nowdate,
)

import erpnext
from erpnext.accounts.utils import get_fiscal_year

# from erpnext.assets.doctype.asset_depreciation_schedule.deppreciation_schedule_controller import (
#     _get_total_days,
# )


class StraightLineMethod(Document):
	def get_straight_line_depr_amount(self, row_idx):
		self.depreciable_value = flt(self.fb_row.value_after_depreciation) - flt(
			self.fb_row.expected_value_after_useful_life
		)

		if self.fb_row.shift_based:
			self.get_shift_depr_amount(row_idx)

		if self.fb_row.daily_prorata_based:
			return self.get_daily_prorata_based_depr_amount(row_idx)
		else:
			return self.get_fixed_depr_amount()

	def get_fixed_depr_amount(self):
		pending_periods = flt(self.pending_months) / flt(self.fb_row.frequency_of_depreciation)
		return self.depreciable_value / pending_periods

	def get_daily_prorata_based_depr_amount(self, row_idx):
		daily_depr_amount = self.get_daily_depr_amount()

		from_date, total_depreciable_days = self._get_total_days(self.fb_row.depreciation_start_date, row_idx)
		return daily_depr_amount * total_depreciable_days

	def get_daily_depr_amount(self):
		if cint(frappe.db.get_single_value("Accounts Settings", "calculate_depr_using_total_days")):
			return self.depreciable_value / self.total_pending_days
		else:
			yearly_depr_amount = self.depreciable_value / self.total_pending_years
			total_days_in_current_depr_year = self.get_total_days_in_current_depr_year()
			return yearly_depr_amount / total_days_in_current_depr_year

	def get_shift_depr_amount(self, row_idx):
		depreciable_value = (
			flt(self.asset_doc.gross_purchase_amount)
			- flt(self.asset_doc.opening_accumulated_depreciation)
			- flt(self.fb_row.expected_value_after_useful_life)
		)
		if self.get("__islocal") and not self.asset_doc.flags.shift_allocation:
			pending_depreciations = flt(
				self.fb_row.total_number_of_depreciations
				- self.asset_doc.opening_number_of_booked_depreciations
			)
			return depreciable_value / pending_depreciations

		asset_shift_factors_map = self.get_asset_shift_factors_map()
		shift = (
			self.schedules_before_clearing[row_idx].shift
			if len(self.schedules_before_clearing) > row_idx
			else None
		)
		shift_factor = asset_shift_factors_map.get(shift, 0)

		shift_factors_sum = sum(
			[flt(asset_shift_factors_map.get(d.shift)) for d in self.schedules_before_clearing]
		)

		return (depreciable_value / shift_factors_sum) * shift_factor

	def get_asset_shift_factors_map(self):
		return dict(frappe.db.get_all("Asset Shift Factor", ["shift_name", "shift_factor"], as_list=True))


class WDVMethod(Document):
	def get_wdv_or_dd_depr_amount(self, row_idx):
		if self.fb_row.daily_prorata_based:
			return self.get_daily_prorata_based_wdv_depr_amount(row_idx)
		else:
			return self.get_wdv_depr_amount()

	def get_wdv_depr_amount(self):
		if self.is_fiscal_year_changed():
			yearly_amount = (
				flt(self.pending_depreciation_amount) * flt(self.fb_row.rate_of_depreciation) / 100
			)
			return (yearly_amount * self.fb_row.frequency_of_depreciation) / 12
		else:
			return self.prev_depreciation_amount

	def is_fiscal_year_changed(self):
		fy_start_date, fy_end_date = self.get_fiscal_year(self.schedule_date)
		if fy_start_date != self.get("prev_fy_start_date"):
			self.prev_fy_start_date = fy_start_date
			return True

	def get_daily_prorata_based_wdv_depr_amount(self, row_idx):
		daily_depr_amount = self.get_daily_wdv_depr_amount()

		from_date, total_depreciable_days = self._get_total_days(self.fb_row.depreciation_start_date, row_idx)
		return daily_depr_amount * total_depreciable_days

	def get_daily_wdv_depr_amount(self):
		if self.is_fiscal_year_changed():
			self.yearly_wdv_depr_amount = (
				self.pending_depreciation_amount * self.fb_row.rate_of_depreciation / 100
			)

		total_days_in_current_depr_year = self.get_total_days_in_current_depr_year()
		return self.yearly_wdv_depr_amount / total_days_in_current_depr_year
