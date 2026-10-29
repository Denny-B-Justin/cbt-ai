from utils.formatting import fmt_amount, fmt_int, fmt_money, fmt_pct, is_missing, plural, short_text


def test_missing_values_show_a_dash():
    assert is_missing(None) and is_missing(float("nan"))
    assert fmt_int(None) == "-" and fmt_pct(float("nan")) == "-" and fmt_amount(None) == "-"


def test_numbers():
    assert fmt_int(1234567.4) == "1,234,567"
    assert fmt_pct(0.1234) == "12.3%" and fmt_pct(0.5, 0) == "50%"
    assert fmt_amount(12_345_678) == "12.3M" and fmt_amount(950) == "950" and fmt_amount(2.5e9, "GEL") == "2.5B GEL"


def test_money_follows_the_unit_of_the_document():
    assert fmt_money(12345, "GEL", "millions") == "12,345 million GEL"
    assert fmt_money(7.25, "USD", "millions") == "7.2 million USD" or fmt_money(7.25, "USD", "millions") == "7.3 million USD"
    assert fmt_money(5_000_000, "GEL", "units") == "5.0M GEL"
    assert fmt_money(None, "GEL", "units") == "-"


def test_text_helpers():
    assert plural(1, "line") == "1 line" and plural(2, "line") == "2 lines" and plural(2, "city", "cities") == "2 cities"
    assert short_text("a  b   c", 10) == "a b c" and short_text("x" * 30, 10).endswith("…") and len(short_text("x" * 30, 10)) == 10
