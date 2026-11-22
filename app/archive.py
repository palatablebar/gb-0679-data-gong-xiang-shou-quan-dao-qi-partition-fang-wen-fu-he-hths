import csv,io,json
from app import timing
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","time_status","effective_at","evidence"])
    meta=run["manifest"]
    def prefix(kind,source_lines,reason,time_status,effective_at,row):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],kind,json.dumps(source_lines),reason,time_status,effective_at,json.dumps(row,ensure_ascii=False)])
    final=run["stages"][-1]
    for row in final["rows"]:
        prefix("accepted",row.get("_sources",[]),row.get("status",""),row.get("time_status",""),row.get("effective_at",""),row)
    for row in final.get("cumulative_pending",[]):
        prefix("pending",row.get("_sources",[]),row.get("reason","PENDING_REVIEW"),row.get("time_status",timing.PENDING_REVIEW),row.get("effective_at",""),row)
    for row in final.get("cumulative_quarantine",[]):
        prefix("quarantine",row.get("_sources",[]),row.get("reason",""),row.get("time_status",""),row.get("effective_at",""),row)
    return "﻿"+stream.getvalue()
