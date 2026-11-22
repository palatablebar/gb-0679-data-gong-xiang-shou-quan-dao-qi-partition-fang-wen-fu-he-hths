from app.config import RECEIVED_COL
from app.values import instant,number
from app.reasons import reject
from app.errors import DomainError
from app import timing
GRANTS=[{"id":"G-01","principal":"analyst","resource":"orders","start":"2026-11-01T00:00:00Z","end":"2026-12-01T00:00:00Z","from_partition":"2026-01","to_partition":"2026-12","effect":"allow"},{"id":"G-02","principal":"analyst","resource":"orders","start":"2026-11-10T00:00:00Z","end":"2026-11-20T00:00:00Z","from_partition":"2026-10","to_partition":"2026-11","effect":"deny"},{"id":"G-03","principal":"auditor","resource":"customers","start":"2026-11-01T00:00:00Z","end":"2026-12-01T00:00:00Z","from_partition":"2026-01","to_partition":"2026-12","effect":"allow"}]
def validate_grants(grants):
    ids=set()
    for g in grants:
        if g["id"] in ids or instant(g["start"])>=instant(g["end"]) or g["effect"] not in {"allow","deny"} or g["from_partition"]>=g["to_partition"]:raise DomainError("BAD_GRANT","授权版本无效")
        ids.add(g["id"])
    return grants
def evaluate(rows,context):
    params=context.get("parameters",{})
    grants=validate_grants(params.get("grants",GRANTS));good=[];bad=[];pending=[]
    boundary_hits=0;pending_hits=0
    for row in rows:
        try:
            reported=number(row["reported"])
            if reported not in {0,1}:raise DomainError("BAD_OBSERVED","报送判定必须为0或1")
        except (DomainError,KeyError) as e:
            bad.append(reject(row,getattr(e,"code","MISSING_FIELD"),str(e)));continue
        # 双端原始时间原样保留，裁决只派生字段
        verdict=timing.adjudicate(row.get("access_time"),row.get(RECEIVED_COL,""),grants,row.get("principal",""),row.get("resource",""),params)
        enriched={**row,**verdict,"reported":str(reported)}
        if verdict["boundary"]: boundary_hits+=1
        # 来源时间失效：第一证据不可信，隔离 INVALID_TIME，不产生授权结论
        if timing.parse_clock(row.get("access_time")) is None:
            bad.append(reject(enriched,"INVALID_TIME","来源时间缺少偏移或格式错误"));continue
        if verdict["time_status"]==timing.PENDING_REVIEW:
            pending_hits+=1
            pending.append(reject(enriched,"PENDING_REVIEW",verdict["time_reason"]));continue
        try:
            at=instant(verdict["effective_at"])
        except DomainError as e:
            bad.append(reject(enriched,e.code,str(e)));continue
        active=[g for g in grants if g["principal"]==row["principal"] and g["resource"]==row["resource"] and instant(g["start"])<=at<instant(g["end"])]
        good.append({**enriched,"at":at.isoformat(),"candidates":active,"candidate_count":len(active)})
    return {"rows":good,"quarantine":bad,"pending":pending,"metrics":{"active_hits":sum(r["candidate_count"] for r in good),"grant_versions":len(grants),"boundary_accesses":boundary_hits,"pending_review":pending_hits,"adopted":len(good)}}
