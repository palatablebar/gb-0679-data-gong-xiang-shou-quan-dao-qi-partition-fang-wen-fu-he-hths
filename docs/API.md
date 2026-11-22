# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；M3起额外返回pending（留待核）与累计隔离/留待核。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV，kind分accepted/pending/quarantine三类，含time_status与effective_at列。

参数`clock_skew_seconds`（非负整数秒，缺省300）随/api/runs提交，参与边界时点裁决并计入批次摘要，不同参数产生不同run_id。样例boundary.csv覆盖到期边界互证、钟差超容差留待核、缺接收端、来源失效隔离与同访问重试。
