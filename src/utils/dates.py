from datetime import date, timedelta


def today() -> date:
    return date.today()


def trading_days_ago(n: int) -> date:
    current = date.today()
    days_back = 0
    while days_back < n:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            days_back += 1
    return current


def is_market_open() -> bool:
    now = date.today()
    return now.weekday() < 5


def format_currency(value: float) -> str:
    return f"${value:,.2f}"


def format_pct(value: float) -> str:
    return f"{value:.2%}"
