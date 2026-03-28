from decimal import Decimal

class SmartSizer:
    @staticmethod
    def calculate_qty(balance: Decimal, price: Decimal, win_rate: float = 0.6) -> Decimal:
        # Simplified Kelly: half kelly
        risk_pct = 0.02 # 2% risk
        if price == 0: return Decimal("0")
        qty = (balance * Decimal(str(risk_pct))) / price
        return round(qty, 4)
