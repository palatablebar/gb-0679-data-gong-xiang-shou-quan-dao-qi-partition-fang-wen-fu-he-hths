from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError
def evaluate(rows,context):
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    pending=context.get("pending",[])
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    held=set(x for row in pending for x in sources(row))
    if accepted & rejected or accepted & held or rejected & held: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"pending_inputs":len(held),"output_records":len(rows)}
    if intake:
        # 重试来源行已并入首条 _sources（在采纳集合内），excluded 只统计未并入任何来源集合的行
        excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"]
        m.update(input=intake["input"],excluded=excluded,balanced=intake["input"]==len(accepted)+len(rejected)+len(held)+excluded)
    else:m.update(input=len(accepted)+len(rejected)+len(held),excluded=0,balanced=True)
    output=[]
    for row in rows:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        output.append({**row,"difference":str(expected-reported),"status":"通过" if expected==reported else "差异"})
    m.update(expected_total=str(sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))),reported_total=str(sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))),differences=sum(r["status"]=="差异" for r in output))
    return {"rows":output,"quarantine":[],"metrics":m}
