"""边界访问唯一有效时点裁决（纯函数，无异常副作用）。

来源时间 access_time 为生产端时钟，接收时间 received_at 为接收端时钟。
两端在时钟容差内互证时采来源时间；无法互证的边界访问留待核，不产生授权结论。
双端原始时间始终原样保留，裁决只派生新字段。
"""
from datetime import datetime, timezone
from app.config import DEFAULT_CLOCK_SKEW_SECONDS
from app.errors import DomainError
from app.values import instant

# 裁决状态
SOURCE_VERIFIED="source_verified"        # 双端互证，采来源时间
SOURCE_UNVERIFIED="source_unverified"    # 时差超容差但非边界，采来源并留痕
SOURCE_ONLY="source_only"                # 无接收佐证且非边界，采来源
PENDING_REVIEW="pending_review"          # 无法互证的边界访问或双端皆失效，留待核

# 有效时点来源
BASIS_SOURCE="source"
BASIS_NONE=""

STATUS_LABELS={
    SOURCE_VERIFIED:"双端互证·采来源",
    SOURCE_UNVERIFIED:"时差未证·采来源",
    SOURCE_ONLY:"无接收佐证·采来源",
    PENDING_REVIEW:"留待核",
}


def parse_clock(value):
    """宽松解析单端时间：返回 UTC datetime 或 None，绝不抛异常。"""
    if value is None:
        return None
    text=str(value).strip()
    if not text or text.upper() in {"-","N/A","NULL","未知"}:
        return None
    try:
        return instant(text)
    except Exception:
        return None


def parse_pair(source_raw, receiver_raw):
    """解析双端原始时间，返回 (source_dt, receiver_dt)，原始文本不动。"""
    return parse_clock(source_raw), parse_clock(receiver_raw)


def clock_skew_seconds(params):
    """时钟容差参数，缺省 300 秒，必须为非负整数秒。"""
    value=(params or {}).get("clock_skew_seconds", DEFAULT_CLOCK_SKEW_SECONDS)
    try:
        seconds=int(value)
    except (TypeError, ValueError):
        raise DomainError("BAD_SKEW","时钟容差必须为非负整数秒")
    if seconds < 0:
        raise DomainError("BAD_SKEW","时钟容差必须为非负整数秒")
    return seconds


def is_boundary(source_dt, receiver_dt, grants, principal, resource, skew_seconds):
    """是否为授权到期边界访问。

    边界定义（任一成立）：
    1. 双端都合法时，两端对任一同主体/资源授权生效窗的内/外归属发生翻转；
    2. 任一合法端落在任一相关授权生效窗端点的 ±容差 邻域内（半开间边界本身算翻转）。
    无任何相关授权窗时不存在到期边界，返回 False。
    """
    instants=[dt for dt in (source_dt, receiver_dt) if isinstance(dt, datetime)]
    if not instants:
        return False
    windows=[]
    for grant in grants or []:
        if grant.get("principal") != principal or grant.get("resource") != resource:
            continue
        start=parse_clock(grant.get("start"))
        end=parse_clock(grant.get("end"))
        if start is not None and end is not None and start < end:
            windows.append((start, end))
    if not windows:
        return False
    for dt in instants:
        for start, end in windows:
            if abs((dt-start).total_seconds()) <= skew_seconds or abs((dt-end).total_seconds()) <= skew_seconds:
                return True
    if source_dt is not None and receiver_dt is not None:
        for start, end in windows:
            inside_source=start <= source_dt < end
            inside_receiver=start <= receiver_dt < end
            if inside_source != inside_receiver:
                return True
    return False


def adjudicate(source_raw, receiver_raw, grants, principal, resource, params):
    """形成唯一有效时点。

    返回 dict：status / basis / effective_at / source_time / received_at /
    clock_delta_seconds / boundary / reason。
    留待核时 effective_at 为空，调用方必须将该行撤出正常裁决流。
    """
    skew_seconds=clock_skew_seconds(params)
    source_dt, receiver_dt = parse_pair(source_raw, receiver_raw)
    source_text="" if source_raw is None else str(source_raw)
    receiver_text="" if receiver_raw is None else str(receiver_raw)
    base={
        "source_time": source_text,
        "received_at": receiver_text,
        "clock_delta_seconds": None,
        "boundary": False,
        "effective_at": "",
        "time_basis": BASIS_NONE,
        "time_status": "",
        "time_reason": "",
    }
    if source_dt is None:
        # 来源时间是授权窗判定的第一证据：来源失效不得进入正常裁决，
        # 由调用方按 INVALID_TIME 隔离；接收端合法也只作证据留痕，不兜底授权。
        base.update(time_status=PENDING_REVIEW,
                    time_reason="来源时间失效，接收端无法替代第一证据，留待核/隔离")
        return base
    boundary=is_boundary(source_dt, receiver_dt, grants, principal, resource, skew_seconds)
    base["boundary"]=boundary
    if receiver_dt is not None:
        delta=(receiver_dt-source_dt).total_seconds()
        base["clock_delta_seconds"]=int(delta)
        if abs(delta) <= skew_seconds:
            base.update(time_status=SOURCE_VERIFIED, time_basis=BASIS_SOURCE,
                        effective_at=source_dt.astimezone(timezone.utc).isoformat(),
                        time_reason="双端钟差在容差内互证，采来源时间")
        elif boundary:
            base.update(time_status=PENDING_REVIEW,
                        time_reason="边界访问且双端钟差超出容差，无法互证，留待核")
        else:
            base.update(time_status=SOURCE_UNVERIFIED, time_basis=BASIS_SOURCE,
                        effective_at=source_dt.astimezone(timezone.utc).isoformat(),
                        time_reason="非边界访问，钟差超容差未获接收佐证，采来源时间并留痕")
        return base
    if boundary:
        base.update(time_status=PENDING_REVIEW,
                    time_reason="边界访问缺少接收端时间，无法排除到期后伪造，留待核")
    else:
        base.update(time_status=SOURCE_ONLY, time_basis=BASIS_SOURCE,
                    effective_at=source_dt.astimezone(timezone.utc).isoformat(),
                    time_reason="非边界访问无接收佐证，采来源时间")
    return base
