# cl5x_qos_profiles.py — semantic QoS wrappers for CL5XTransportV5
QOS = {
    'SUMMARY': {'topic':101, 'priority':3, 'ttl_ms': 800},
    'RESIDUAL': {'topic':102, 'priority':1, 'ttl_ms': 4000},
    'CKB': {'topic':100, 'priority':3, 'ttl_ms': 1200},
    'PLAN': {'topic':111, 'priority':3, 'ttl_ms': 1200},
    'OBS': {'topic':112, 'priority':2, 'ttl_ms': 2000},
    'ACT': {'topic':113, 'priority':3, 'ttl_ms': 1200},
    'REFLECT': {'topic':114, 'priority':2, 'ttl_ms': 2500},
}
def publish_semantic(tx, kind:str, data:bytes, chid:int=1):
    p = QOS[kind]
    tx.publish(topic=p['topic'], data=data, priority=p['priority'], ttl_ms=p['ttl_ms'], chid=chid)