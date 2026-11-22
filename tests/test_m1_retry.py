from app.modules.m1_accesses.rules import evaluate
from app.config import COLUMNS, EXTENDED_COLUMNS
from app.errors import DomainError
import pytest

HEADER9=",".join(EXTENDED_COLUMNS)


def test_extended_header_accepted():
    raw=(HEADER9+"\nE1,a,orders,2026-09,2026-11-16T00:00:00Z,2026-11-16T00:01:00Z,allowed,1,n\n").encode()
    r=evaluate(raw)
    assert r["metrics"]["extended_header"] is True
    assert r["rows"][0]["received_at"]=="2026-11-16T00:01:00Z"


def test_legacy_header_defaults_blank_received():
    raw=(",".join(COLUMNS)+"\nE1,a,orders,2026-09,2026-11-16T00:00:00Z,allowed,1,n\n").encode()
    r=evaluate(raw)
    assert r["metrics"]["extended_header"] is False
    assert r["rows"][0]["received_at"]==""


def test_unknown_header_rejected():
    with pytest.raises(DomainError) as e:
        evaluate((HEADER9+",extra\n").encode())
    assert e.value.code=="BAD_HEADER"


def test_retry_same_key_merges_instead_of_new_conclusion():
    raw=(HEADER9+"\n"
         "E1,a,orders,2026-09,2026-11-19T23:58:00Z,2026-11-20T00:01:00Z,blocked,0,first\n"
         "E1,a,orders,2026-09,2026-11-19T23:58:00Z,2026-11-20T00:01:30Z,blocked,0,retry\n").encode()
    r=evaluate(raw)
    assert r["metrics"]["retry"]==1 and len(r["rows"])==1
    row=r["rows"][0]
    assert row["_sources"]==[2,3] and row["_retry_lines"]==[3]
    assert row["_retry_received"]==["2026-11-20T00:01:00Z","2026-11-20T00:01:30Z"]
    # 首条结论保持不变
    assert row["note"]=="first" and row["received_at"]=="2026-11-20T00:01:00Z"


def test_retry_with_business_value_change_is_conflict():
    raw=(HEADER9+"\n"
         "E1,a,orders,2026-09,2026-11-19T23:58:00Z,2026-11-20T00:01:00Z,blocked,0,first\n"
         "E1,a,orders,2026-08,2026-11-19T23:58:00Z,2026-11-20T00:01:30Z,blocked,0,retry\n").encode()
    r=evaluate(raw)
    assert any(q["reason"]=="DUPLICATE_CONFLICT" for q in r["quarantine"])
    assert r["metrics"]["retry"]==0


def test_exact_duplicate_still_counted_duplicate():
    line="E1,a,orders,2026-09,2026-11-19T23:58:00Z,2026-11-20T00:01:00Z,blocked,0,n\n"
    r=evaluate((HEADER9+"\n"+line+line).encode())
    assert r["metrics"]["duplicate"]==1 and r["metrics"]["retry"]==0
