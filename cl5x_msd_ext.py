# cl5x_msd_ext.py — Extended schemas on top of cl5x_msd.REG
from cl5x_msd import REG
# Reasoning/Agent
SCHEMA_PLAN = REG.register(['id','goal','steps','deadline','priority'])
SCHEMA_OBS  = REG.register(['id','text','ts','source'])
SCHEMA_ACT  = REG.register(['id','action','params','ts'])
# HTTP / JSON-RPC
SCHEMA_HTTP_REQ = REG.register(['method','url','headers','body','id'])
SCHEMA_HTTP_RES = REG.register(['id','status','headers','body','time_ms'])
SCHEMA_JSONRPC_REQ = REG.register(['jsonrpc','method','params','id'])
SCHEMA_JSONRPC_RES = REG.register(['jsonrpc','result','error','id'])