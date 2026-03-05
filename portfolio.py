import robin_stocks.robinhood as rh
from datetime import datetime

from credentials import RH_USERNAME, RH_PASSWORD

rh.login(RH_USERNAME, RH_PASSWORD)

lines = []
lines.append("Robinhood Portfolio Report")
lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
lines.append("=" * 60)

# --- Account Summary ---
profile = rh.profiles.load_account_profile()
portfolio = rh.profiles.load_portfolio_profile()
lines.append("\n[Account Summary]")
lines.append(f"  Buying power:        ${float(profile.get('buying_power', 0) or 0):,.2f}")
lines.append(f"  Cash:                ${float(profile.get('cash', 0) or 0):,.2f}")
lines.append(f"  Market value:        ${float(portfolio.get('market_value', 0) or 0):,.2f}")
lines.append(f"  Equity:              ${float(portfolio.get('equity', 0) or 0):,.2f}")
lines.append(f"  Withdrawable amount: ${float(portfolio.get('withdrawable_amount', 0) or 0):,.2f}")
lines.append(f"  Total dividends:     ${float(rh.account.get_total_dividends() or 0):,.2f}")

# --- Stock Holdings with Cost Basis ---
lines.append("\n[Stock Holdings]")
holdings = rh.account.build_holdings()
open_positions = rh.account.get_open_stock_positions()

cost_basis_map = {}
for pos in open_positions:
    instrument_url = pos.get("instrument", "")
    avg_cost = float(pos.get("average_buy_price", 0) or 0)
    cost_basis_map[instrument_url] = avg_cost

if holdings:
    for ticker, data in holdings.items():
        name = data.get("name", "")
        quantity = float(data.get("quantity", 0))
        price = float(data.get("price", 0))
        equity = float(data.get("equity", 0))
        avg_buy = float(data.get("average_buy_price", 0))
        pct_change = float(data.get("percent_change", 0))
        equity_change = float(data.get("equity_change", 0))
        pe_ratio = data.get("pe_ratio", "N/A")
        lines.append(f"\n  {ticker} - {name}")
        lines.append(f"    Shares:          {quantity:.4f}")
        lines.append(f"    Current price:   ${price:,.2f}")
        lines.append(f"    Avg buy price:   ${avg_buy:,.2f}")
        lines.append(f"    Total equity:    ${equity:,.2f}")
        lines.append(f"    Gain/Loss:       ${equity_change:,.2f} ({pct_change:+.2f}%)")
        lines.append(f"    P/E ratio:       {pe_ratio}")
else:
    lines.append("  No stock positions found.")

# --- Crypto Holdings ---
lines.append("\n[Crypto Holdings]")
crypto = rh.crypto.get_crypto_positions()
if crypto:
    for position in crypto:
        currency = position.get("currency", {})
        code = currency.get("code", "?")
        name = currency.get("name", "")
        quantity = float(position.get("quantity", 0))
        cost_bases = position.get("cost_bases", [{}])
        cost = float(cost_bases[0].get("direct_cost_basis", 0)) if cost_bases else 0
        avg_cost = float(cost_bases[0].get("direct_quantity", 1) or 1)
        lines.append(f"\n  {code} - {name}")
        lines.append(f"    Quantity:        {quantity:.6f}")
        lines.append(f"    Cost basis:      ${cost:,.2f}")
else:
    lines.append("  No crypto positions found.")

# --- Stock Order History ---
lines.append("\n[Stock Order History]")
orders = rh.orders.get_all_stock_orders()
if orders:
    for order in orders:
        side = order.get("side", "").upper()
        state = order.get("state", "")
        qty = float(order.get("quantity", 0) or 0)
        filled_qty = float(order.get("cumulative_quantity", 0) or 0)
        price = float(order.get("average_price", 0) or 0)
        order_type = order.get("type", "")
        created = order.get("created_at", "")[:10]
        symbol = order.get("instrument_id", "")

        # Get ticker from executions or instrument
        executions = order.get("executions", [])
        ticker = ""
        try:
            instrument_url = order.get("instrument", "")
            if instrument_url:
                instrument_data = rh.stocks.get_instrument_by_url(instrument_url)
                ticker = instrument_data.get("symbol", "")
        except Exception:
            pass

        if state in ("filled", "partially_filled"):
            lines.append(
                f"  {created}  {side:<4} {ticker:<6}  qty={filled_qty:.4f}"
                f"  avg_price=${price:,.2f}  type={order_type}  state={state}"
            )
else:
    lines.append("  No order history found.")

# --- Dividend History ---
lines.append("\n[Dividend History]")
dividends = rh.account.get_dividends()
if dividends:
    for div in dividends:
        amount = float(div.get("amount", 0) or 0)
        paid_at = (div.get("paid_at") or div.get("payable_date") or "")[:10]
        state = div.get("state", "")
        rate = float(div.get("rate", 0) or 0)
        position = float(div.get("position", 0) or 0)
        lines.append(
            f"  {paid_at}  amount=${amount:,.4f}  rate=${rate:.4f}"
            f"  shares={position:.4f}  state={state}"
        )
else:
    lines.append("  No dividend history found.")

# --- Write output ---
output_path = "portfolio.txt"
with open(output_path, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Portfolio written to {output_path}")

rh.logout()
