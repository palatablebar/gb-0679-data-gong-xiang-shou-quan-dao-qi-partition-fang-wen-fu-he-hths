from datetime import datetime
from app import timing
from app.modules.m3_grants.rules import GRANTS
from app.errors import DomainError
import pytest

ORDERS_END="2026-11-20T00:00:00Z"
ORDERS_START="2026-11-10T00:00:00Z"


def rule(principal="analyst", resource="orders", **over):
    base={"event_id":"E1","principal":principal,"resource":resource,"partition":"2026-09",
          "access_time":"2026-11-19T23:58:00Z","received_at":"2026-11-20T00:01:00Z",
          "observed":"blocked","reported":"0"}
    base.update(over);return base


def test_verified_within_skew_adopts_source():
    """双端互证：钟差 180s ≤ 300s，采来源时间，临近到期不被接收慢钟误拦。"""
    v=timing.adjudicate(rule()["access_time"],rule()["received_at"],GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.SOURCE_VERIFIED
    assert v["time_basis"]==timing.BASIS_SOURCE
    assert v["effective_at"].startswith("2026-11-19T23:58:00")
    assert v["boundary"] is True and v["clock_delta_seconds"]==180


def test_boundary_skew_exceeded_is_held():
    """到期翻转且钟差超容差：无法互证，留待核，无有效时点。"""
    v=timing.adjudicate("2026-11-19T23:57:00Z","2026-11-20T00:06:00Z",GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.PENDING_REVIEW
    assert v["effective_at"]=="" and v["time_basis"]==timing.BASIS_NONE
    assert v["boundary"] is True


def test_non_boundary_large_skew_still_adopts_source():
    """非边界访问钟差超容差：窗结论对时差不敏感，采来源并标记时差未证。"""
    v=timing.adjudicate("2026-11-10T12:00:00Z","2026-11-10T12:20:00Z",GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.SOURCE_UNVERIFIED
    assert v["effective_at"].startswith("2026-11-10T12:00:00")
    assert v["boundary"] is False


def test_boundary_missing_receiver_is_held():
    """边界访问缺接收端：无法排除到期后伪造，留待核。"""
    v=timing.adjudicate("2026-11-19T23:59:00Z","",GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.PENDING_REVIEW and v["effective_at"]==""
    assert v["boundary"] is True


def test_non_boundary_missing_receiver_uses_source():
    """非边界缺接收端：采来源，标记无接收佐证。"""
    v=timing.adjudicate("2026-11-11T00:00:00Z","",GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.SOURCE_ONLY
    assert v["time_basis"]==timing.BASIS_SOURCE and v["boundary"] is False


def test_invalid_source_held_for_quarantine():
    """来源失效：不产生有效时点，由 M3 按 INVALID_TIME 隔离；接收端仅留痕。"""
    v=timing.adjudicate("2026-11-20T00:00:00","2026-11-20T00:01:00Z",GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.PENDING_REVIEW
    assert v["effective_at"]=="" and v["time_basis"]==timing.BASIS_NONE
    assert v["received_at"]=="2026-11-20T00:01:00Z"


def test_both_invalid_has_no_effective_point():
    v=timing.adjudicate("not-a-time","garbage",GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.PENDING_REVIEW and v["effective_at"]==""


def test_post_expiry_forgery_cannot_pass():
    """到期后伪造：来源写在到期前、真实接收在到期后，钟差超容差 → 留待核，不放过。"""
    v=timing.adjudicate("2026-11-19T23:50:00Z","2026-11-20T00:10:00Z",GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.PENDING_REVIEW and v["boundary"] is True


def test_post_expiry_both_agree_denies_naturally():
    """双端互证但都在到期后：采来源，授权窗自然拒绝（在 M3 候选为空体现）。"""
    v=timing.adjudicate("2026-12-01T00:02:00Z","2026-12-01T00:04:00Z",GRANTS,"analyst","orders",{})
    assert v["time_status"]==timing.SOURCE_VERIFIED
    at=datetime.fromisoformat(v["effective_at"])
    assert at>=datetime.fromisoformat(ORDERS_END.replace("Z","+00:00"))


def test_grant_start_is_also_boundary():
    v=timing.adjudicate("2026-11-10T00:01:00Z","2026-11-10T00:03:00Z",GRANTS,"analyst","orders",{})
    assert v["boundary"] is True and v["time_status"]==timing.SOURCE_VERIFIED


def test_unrelated_principal_has_no_boundary():
    v=timing.adjudicate("2026-11-19T23:59:00Z","2026-11-20T00:01:00Z",GRANTS,"ghost","orders",{})
    assert v["boundary"] is False


def test_skew_parameter_changes_verdict():
    """收紧容差到 120s 后，180s 钟差的边界访问转为留待核。"""
    loose=timing.adjudicate(rule()["access_time"],rule()["received_at"],GRANTS,"analyst","orders",{})
    tight=timing.adjudicate(rule()["access_time"],rule()["received_at"],GRANTS,"analyst","orders",{"clock_skew_seconds":120})
    assert loose["time_status"]==timing.SOURCE_VERIFIED
    assert tight["time_status"]==timing.PENDING_REVIEW


def test_bad_skew_rejected():
    with pytest.raises(DomainError):
        timing.clock_skew_seconds({"clock_skew_seconds":-1})
    with pytest.raises(DomainError):
        timing.clock_skew_seconds({"clock_skew_seconds":"x"})


def test_raw_timestamps_are_preserved_textually():
    """裁决只派生字段，双端原始文本原样保留。"""
    v=timing.adjudicate("2026-11-19T23:58:00Z","2026-11-20T00:01:00Z",GRANTS,"analyst","orders",{})
    assert v["source_time"]=="2026-11-19T23:58:00Z"
    assert v["received_at"]=="2026-11-20T00:01:00Z"
