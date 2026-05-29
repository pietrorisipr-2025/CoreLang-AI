
def to_prometheus_text(prefix:str, metrics:dict)->str:
    return "\n".join(f"{prefix}_{k} {v}" for k,v in metrics.items() if isinstance(v,(int,float)))+"\n"
