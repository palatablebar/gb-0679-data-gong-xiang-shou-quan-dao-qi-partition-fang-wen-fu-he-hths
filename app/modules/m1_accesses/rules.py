import csv,io
from app.config import COLUMNS,EXTENDED_COLUMNS,RECEIVED_COL,RETRY_IGNORED
from app.errors import DomainError
from app.reasons import reject
def decode(raw):
    for encoding in ("utf-8-sig","gb18030"):
        try: return raw.decode(encoding),encoding
        except UnicodeDecodeError: continue
    raise DomainError("ENCODING","无法识别文件编码")
def _retry_only(previous_cells,cells,header):
    """同键再次出现且仅重试字段（接收时间/备注）不同：视为重试，沿用首条。"""
    if len(previous_cells)!=len(cells): return False
    for index,(old,new) in enumerate(zip(previous_cells,cells)):
        if old==new: continue
        if header[index] in RETRY_IGNORED: continue
        return False
    return True
def evaluate(raw,context=None):
    text,encoding=decode(raw)
    if not text: raise DomainError("EMPTY_FILE","文件为空")
    if not text.strip(): raise DomainError("BLANK_ONLY","全部为空行")
    stream=csv.reader(io.StringIO(text,newline=""));header=next(stream,None)
    if header not in (COLUMNS,EXTENDED_COLUMNS): raise DomainError("BAD_HEADER","表头不匹配")
    width=len(header)
    rows=[];bad=[];seen={};duplicate=blank=repeated=retry=count=0
    try:
        for cells in stream:
            count+=1;line=stream.line_num
            if not cells or not any(c.strip() for c in cells): blank+=1;continue
            if cells==header: repeated+=1;continue
            row={"_line":line,"_sources":[line],"_raw":cells}
            if len(cells)!=width: bad.append(reject(row,"BAD_COLUMNS","列数不匹配"));continue
            row.update(dict(zip(header,[x.strip() for x in cells])))
            if width==len(COLUMNS): row[RECEIVED_COL]=""
            if not row[header[0]]: bad.append(reject(row,"EMPTY_VALUE","业务键为空"));continue
            key=row[header[0]]
            if key in seen:
                previous=seen[key]
                if cells==previous["_raw"]: duplicate+=1
                elif _retry_only(previous["_raw"],cells,header):
                    # 同一访问重试：不新增结论，仅把新来源行并入首条并保留双端原始时间
                    retry+=1
                    previous["_sources"].append(line)
                    previous.setdefault("_retry_lines",[]).append(line)
                    previous["_retry_received"]=[x for x in (previous.get(RECEIVED_COL,""),row.get(RECEIVED_COL,"")) if x]
                else: bad.append(reject(row,"DUPLICATE_CONFLICT","同键不同值"))
                continue
            seen[key]=row;rows.append(row)
    except csv.Error: raise DomainError("BAD_CSV","引号未闭合或文件损坏")
    if count==0: raise DomainError("HEADER_ONLY","仅有表头")
    if not rows and not bad: raise DomainError("BLANK_ONLY","全部为空行")
    return {"rows":rows,"quarantine":bad,"metrics":{"input":count,"accepted":len(rows),"quarantine":len(bad),"duplicate":duplicate,"retry":retry,"blank":blank,"repeated_headers":repeated,"encoding":encoding,"extended_header":width==len(EXTENDED_COLUMNS)}}
