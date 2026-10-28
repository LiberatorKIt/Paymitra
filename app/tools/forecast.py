"""13-week cash forecast. Pure arithmetic over expected inflows and known outflows."""
from datetime import date, timedelta

HORIZON_DAYS = 91  # 13 weeks


def build_forecast(today: date, opening_cash: float, inflows: list[dict],
                   payroll_amount: float, payroll_next_date: date,
                   monthly_bills: float, monthly_sales: float) -> dict:
    """inflows: [{"date": date, "amount": float, "invoice_id": str}]

    Outflows: payroll every 30 days from payroll_next_date; supplier bills and
    overheads spread evenly over working days (Mon-Fri). New sales raised from today are assumed to be collected from
    day 46 onward at the monthly run-rate (they are not invoices yet).
    """
    days = [today + timedelta(days=i) for i in range(HORIZON_DAYS)]
    in_by_day = {d: 0.0 for d in days}
    out_by_day = {d: 0.0 for d in days}
    events = []

    for f in inflows:
        d = f["date"]
        if d < today:
            d = today
        if d in in_by_day:
            in_by_day[d] += f["amount"]

    pay_day = payroll_next_date
    while pay_day < today + timedelta(days=HORIZON_DAYS):
        if pay_day >= today:
            out_by_day[pay_day] += payroll_amount
            events.append({"date": pay_day, "label": "Payroll", "amount": payroll_amount})
        pay_day += timedelta(days=30)

    daily_bills = monthly_bills * 12 / 260          # ~260 working days a year
    for d in days:
        if d.weekday() < 5:
            out_by_day[d] += daily_bills
        if (d - today).days >= 46:
            in_by_day[d] += monthly_sales / 30

    balance = opening_cash
    daily = []
    for d in days:
        balance += in_by_day[d] - out_by_day[d]
        daily.append({"date": d, "inflow": round(in_by_day[d], 2),
                      "outflow": round(out_by_day[d], 2), "balance": round(balance, 2)})

    weeks = []
    for w in range(13):
        chunk = daily[w * 7:(w + 1) * 7]
        weeks.append({
            "week": w + 1,
            "start": chunk[0]["date"],
            "end": chunk[-1]["date"],
            "inflow": round(sum(r["inflow"] for r in chunk), 2),
            "outflow": round(sum(r["outflow"] for r in chunk), 2),
            "closing": chunk[-1]["balance"],
            "low": min(r["balance"] for r in chunk),
        })

    # A 13-week forecast is read week by week: the first week that closes below
    # zero is the gap to cover. Its date is the payroll in that week, if any.
    first_gap = None
    for i, wk in enumerate(weeks):
        if wk["closing"] < 0:
            payroll = next((e["date"] for e in events if wk["start"] <= e["date"] <= wk["end"]), None)
            recover = next((w2["start"] for w2 in weeks[i + 1:] if w2["closing"] >= 0), None)
            first_gap = {"date": payroll or wk["end"], "week_start": wk["start"],
                         "shortfall": round(-wk["closing"], 2), "recovers_on": recover,
                         "cause": "payroll" if payroll else "bills"}
            break
    return {"daily": daily, "weeks": weeks, "first_gap": first_gap, "events": events}
