import csv, io, json
import pytest
from app.pipeline import calculate, execute, load_sample
from app import store
from app.archive import build_archive

BOUNDARY=load_sample("boundary.csv")


def test_boundary_sample_ruling_counts():
    r=calculate(BOUNDARY)
    m=r["stages"][2]["metrics"]
    assert m["boundary_accesses"]==6
    assert m["pending_review"]==2
    assert m["adopted"]==6
    statuses={row["event_id"]:row["time_status"] for row in r["stages"][2]["rows"]}
    assert statuses["B0001"]=="source_verified"
    assert statuses["B0006"]=="source_unverified"
    assert statuses["B0010"]=="source_only"
    pending={p["event_id"] for p in r["stages"][2]["pending"]}
    assert pending=={"B0002","B0004"}


def test_pending_never_enters_grant_partition_audit():
    """留待核行不进入授权候选、分区裁决和对账结论。"""
    r=calculate(BOUNDARY)
    for index in (2,3,4,5):
        ids={row["event_id"] for row in r["stages"][index]["rows"]}
        assert "B0002" not in ids and "B0004" not in ids


def test_pending_conserved_in_lineage():
    m=calculate(BOUNDARY)["stages"][5]["metrics"]
    assert m["pending_inputs"]==2
    assert m["accepted_inputs"]+m["quarantine_inputs"]+m["pending_inputs"]+m["excluded"]==m["input"]
    assert m["balanced"] is True


def test_invalid_source_is_quarantined_not_held():
    """来源时间非法必须隔离 INVALID_TIME，不能被留待核吞掉。"""
    r=calculate(BOUNDARY)
    reasons={q.get("event_id"):q["reason"] for q in r["stages"][2]["cumulative_quarantine"]}
    assert reasons["B0005"]=="INVALID_TIME"
    assert reasons["B0008"]=="INVALID_TIME"


def test_retry_does_not_add_conclusion():
    """同一访问重试：只保留首条结论，来源行合并且双端原始时间都在。"""
    r=calculate(BOUNDARY)
    m1=r["stages"][0]["metrics"]
    assert m1["retry"]==1 and m1["accepted"]==10
    b1=next(row for row in r["stages"][2]["rows"] if row["event_id"]=="B0001")
    assert b1["_sources"]==[2,12]
    assert b1["_retry_lines"]==[12]
    assert b1["_retry_received"]==["2026-11-20T00:01:00Z","2026-11-20T00:01:30Z"]
    # 全流水线只有一条 B0001 结论
    assert sum(1 for row in r["stages"][6]["rows"] if row["event_id"]=="B0001")==1


def test_retry_rerun_is_idempotent_conclusion():
    a=execute(BOUNDARY); b=execute(BOUNDARY)
    assert a["run_id"]==b["run_id"] and len(store.history())==1


def test_archive_contains_three_kinds_with_timepoint():
    run=execute(BOUNDARY)
    rows=list(csv.reader(io.StringIO(build_archive(run).lstrip("﻿"))))
    header=rows[0]
    assert header[:9]==["run_id","input_sha256","rule_version","kind","source_lines","reason","time_status","effective_at","evidence"]
    kinds={}
    for line in rows[1:]: kinds[line[3]]=kinds.get(line[3],0)+1
    assert kinds=={"accepted":6,"pending":2,"quarantine":2}
    pending_line=next(line for line in rows[1:] if line[3]=="pending")
    assert pending_line[6]=="pending_review" and pending_line[7]==""
    accepted=next(line for line in rows[1:] if line[3]=="accepted")
    assert accepted[7]  # 有效时点非空


def test_replacement_interruption_restores_old_version(client):
    """替换中断：事务回滚，旧版完整恢复，双端原始时间保留。"""
    p=client.post("/api/runs",json={"sample":"boundary.csv"}).get_json()
    run_id=p["run_id"]
    before=store.get(run_id)
    tampered=json.loads(json.dumps(before))
    tampered["stages"][2]["rows"][0]["received_at"]="TAMPERED"
    with pytest.raises(RuntimeError):
        store.replace_payload(run_id, tampered, fail=True)
    after=store.get(run_id)
    assert after["version"]==before["version"]
    assert after["stages"][2]["rows"][0]["received_at"]!="TAMPERED"
    # 成功替换后新 payload 仍保留双端原始时间
    store.replace_payload(run_id, tampered)
    assert store.get(run_id)["stages"][2]["rows"][0]["received_at"]=="TAMPERED"


def test_effective_point_propagates_to_every_stage(client):
    """唯一有效时点被授权、分区、对账、证据沿用。"""
    p=client.post("/api/runs",json={"sample":"boundary.csv"}).get_json()
    run=store.get(p["run_id"])
    for index in (2,3,4,5,6):
        row=next(x for x in run["stages"][index]["rows"] if x["event_id"]=="B0001")
        assert row["effective_at"].startswith("2026-11-19T23:58:00")
        assert row["time_basis"]=="source"
        assert row["source_time"]=="2026-11-19T23:58:00Z"
        assert row["received_at"]=="2026-11-20T00:01:00Z"


def test_extended_header_accepted_legacy_header_still_works():
    r=calculate(BOUNDARY)
    assert r["stages"][0]["metrics"]["extended_header"] is True
    legacy=calculate(load_sample("dirty.csv"))
    assert legacy["stages"][0]["metrics"]["extended_header"] is False
    assert all(row.get("received_at","")=="" for row in legacy["stages"][0]["rows"])


def test_grant_candidates_use_effective_time():
    """授权生效窗按有效时点（来源）匹配，到期后互证访问候选为空。"""
    r=calculate(BOUNDARY)
    b7=next(row for row in r["stages"][2]["rows"] if row["event_id"]=="B0007")
    assert b7["candidate_count"]==0
    b1=next(row for row in r["stages"][2]["rows"] if row["event_id"]=="B0001")
    assert b1["candidate_count"]>=1
