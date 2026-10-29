import pytest

from tagging.lines import parse_amount, select_lines


@pytest.mark.parametrize("raw,expected", [
    ("1,234.5", 1234.5), ("1.234,5", 1234.5), ("1 234 567,89", 1234567.89), ("12 345", 12345.0), ("1200", 1200.0),
    (1200, 1200.0), ("(500)", -500.0), ("-12", -12.0), ("€ 4,000", 4000.0), ("1,234,567", 1234567.0), ("0.0", 0.0),
    ("n/a", None), ("", None), ("abc", None), (None, None), (True, None), (float("nan"), None), ("-", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def rec(title, amount="", kind="programme", **kw):
    return {"title": title, "amount": amount, "kind": kind, "page": kw.pop("page", 1), "code": kw.pop("code", ""),
            "ministry": kw.pop("ministry", ""), "description": kw.pop("description", ""), "function_code": kw.pop("function_code", "")}


def titles(sel):
    return [ln.title for ln in sel.lines]


def test_totals_and_categories_never_become_lines():
    sel = select_lines([rec("Solar", "100"), rec("Roads", "50"), rec("Schools", "50"),
                        rec("Total budget", "200", "total"), rec("Salaries", "30", "category")])
    assert titles(sel) == ["Solar", "Roads", "Schools"] and sel.stats["totals_and_categories"] == 2


def test_one_view_is_kept_so_money_is_not_counted_twice():
    programmes = [rec("P%d" % i, "100") for i in range(3)]
    functions = [rec("Health", "300", "function"), rec("Energy", "300", "function"), rec("Defence", "300", "function")]
    ministries = [rec("Ministry of Health", "900", "ministry")]
    sel = select_lines(programmes + functions + ministries)
    assert titles(sel) == ["P0", "P1", "P2"] and any("more than one way" in i["message"] for i in sel.issues)
    assert titles(select_lines(functions + ministries)) == ["Health", "Energy", "Defence"]
    assert titles(select_lines(ministries)) == ["Ministry of Health"]


def test_the_same_code_on_two_pages_is_one_line():
    sel = select_lines([rec("Solar", "300", code="01 02 03 04", page=1),
                        rec("Solar power programme", "300", code="01 02 03 04", page=4, description="Two plants"),
                        rec("Roads", "700", code="01 03 00 01"), rec("Schools", "10"), rec("Health", "10")])
    assert len(sel.lines) == 4
    merged = [ln for ln in sel.lines if ln.code == "01 02 03 04"][0]
    assert merged.title == "Solar power programme" and merged.amount == 300 and merged.page == 1 and "Two plants" in merged.description


def test_parent_lines_that_sum_their_children_are_dropped():
    sel = select_lines([rec("Energy", "500", code="05 01 00 00"), rec("Solar", "300", code="05 01 01 00"),
                        rec("Wind", "200", code="05 01 02 00"), rec("Roads", "100", code="06 01 00 00")])
    assert titles(sel) == ["Solar", "Wind", "Roads"] and sel.stats["subtotals"] == 1


def test_children_without_amount_are_folded_into_their_parent():
    sel = select_lines([rec("Energy", "500", code="05 01 00 00"),
                        rec("Solar plants", "", code="05 01 00 01", description="Two 40 MW plants"),
                        rec("Roads", "100", code="06 01 00 00"), rec("Schools", "10"), rec("Health", "20")])
    energy = [ln for ln in sel.lines if ln.title == "Energy"][0]
    assert "Solar plants" in energy.description and "Two 40 MW plants" in energy.description
    assert "Solar plants" not in titles(sel)


def test_exact_duplicates_are_removed():
    sel = select_lines([rec("Roads", "100", ministry="Works"), rec("roads", "100", ministry="works"), rec("Schools", "5"), rec("Health", "5")])
    assert titles(sel) == ["Roads", "Schools", "Health"] and sel.stats["duplicates"] == 1


def test_negative_and_missing_amounts_stay_as_lines_without_an_amount():
    sel = select_lines([rec("Refund", "(50)"), rec("Pilot", ""), rec("Roads", "100"), rec("Schools", "5")])
    by = {ln.title: ln.amount for ln in sel.lines}
    assert by == {"Refund": None, "Pilot": None, "Roads": 100.0, "Schools": 5.0}
    assert any("negative" in i["message"] for i in sel.issues)


def test_rows_without_a_name_are_ignored_and_a_description_can_stand_in():
    sel = select_lines([rec("", "10"), {"title": "", "description": "Rural water supply works", "amount": "5", "kind": "programme"},
                        rec("Roads", "100"), rec("Schools", "5")])
    assert "Rural water supply works" in titles(sel) and len(sel.lines) == 3


def test_empty_and_unknown_input():
    assert select_lines([]).lines == []
    sel = select_lines([{"title": "Roads", "amount": "5", "kind": "something odd"}])
    assert sel.lines[0].kind == "programme"


def test_lines_come_back_in_document_order():
    sel = select_lines([rec("B", "1", page=2), rec("A", "1", page=1), rec("C", "1", page=2)])
    assert titles(sel) == ["A", "B", "C"]
