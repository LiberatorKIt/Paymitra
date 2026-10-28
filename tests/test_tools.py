"""The maths must match a spreadsheet 100%. Expected values were computed by hand:

sec16 (1,00,000, 60 days, bank rate 5.75%): monthly rate = 3 x 5.75 / 12 = 1.4375%
    100000 x 1.014375^2 - 100000 = 2,895.66
sec16 (1,00,000, 45 days): 100000 x 1.014375 x (1 + 0.014375 x 15/30) - 100000 = 2,166.58
OD (6,80,000 for 26 days at 14%): 680000 x 0.14 x 26/365 = 6,781.37
TReDS (6,80,000, 26 days, 7.5% + 0.10% fee): 680000 x 0.075 x 26/365 + 680 = 4,312.88
"""
from datetime import date

import pytest

from app.tools.finance import (ageing_bucket, cheapest_option, inr, invoice_age, od_cost, sec16_interest,
                               treds_cost)
from app.tools.forecast import build_forecast


def test_sec16_full_months():
    assert sec16_interest(100000, 60, 5.75) == 2895.66


def test_sec16_part_month():
    assert sec16_interest(100000, 45, 5.75) == 2166.58


def test_sec16_not_late():
    assert sec16_interest(100000, 0, 5.75) == 0
    assert sec16_interest(100000, -5, 5.75) == 0


def test_od_cost():
    assert od_cost(680000, 26, 14) == 6781.37


def test_treds_cost():
    assert treds_cost(680000, 26, 7.5, 0.10) == 4312.88


def test_cheapest_option_prefers_treds_when_buyer_on_treds():
    best, costs = cheapest_option(680000, 26, buyer_on_treds=True, cost_of_missing=50000)
    assert best == "TREDS"
    assert set(costs) == {"WAIT", "OD", "TREDS"}


def test_cheapest_option_without_treds():
    best, costs = cheapest_option(680000, 26, buyer_on_treds=False, cost_of_missing=50000)
    assert best == "OD" and "TREDS" not in costs


def test_wait_wins_when_gap_is_cheap():
    best, _ = cheapest_option(680000, 26, buyer_on_treds=True, cost_of_missing=1000)
    assert best == "WAIT"


@pytest.mark.parametrize("age,bucket", [(0, "0-30"), (30, "0-30"), (31, "31-45"), (45, "31-45"),
                                        (46, "46-60"), (60, "46-60"), (61, "60+")])
def test_ageing_buckets(age, bucket):
    assert ageing_bucket(age) == bucket


def test_invoice_age():
    assert invoice_age(date(2026, 9, 20), date(2026, 10, 28)) == 38


def test_inr_format():
    assert inr(680000) == "₹6.80 L"
    assert inr(21000000) == "₹2.10 Cr"
    assert inr(4313) == "₹4,313"


def test_forecast_detects_payroll_gap():
    today = date(2026, 10, 28)
    fc = build_forecast(today, opening_cash=500000,
                        inflows=[{"date": date(2026, 11, 20), "amount": 1000000, "invoice_id": "x"}],
                        payroll_amount=900000, payroll_next_date=date(2026, 11, 6),
                        monthly_bills=0, monthly_sales=0)
    assert fc["first_gap"]["date"] == date(2026, 11, 6)
    assert fc["first_gap"]["shortfall"] == 400000
    assert fc["first_gap"]["recovers_on"] == date(2026, 11, 18)  # week starting 18 Nov
    assert len(fc["weeks"]) == 13


def test_forecast_inflow_closes_gap():
    today = date(2026, 10, 28)
    fc = build_forecast(today, opening_cash=500000,
                        inflows=[{"date": date(2026, 11, 2), "amount": 2300000, "invoice_id": "x"}],  # 3 payrolls in 13 weeks
                        payroll_amount=900000, payroll_next_date=date(2026, 11, 6),
                        monthly_bills=0, monthly_sales=0)
    assert fc["first_gap"] is None
