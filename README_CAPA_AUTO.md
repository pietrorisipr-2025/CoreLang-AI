
# CAPA Auto — orchestratore automatico per CorelangAI

## Installazione (drop-in)
Copia questi file nella tua distro CoreLangAI:
- `tools/capa_auto.py`
- `tools/capa_config.json`
- (opz.) `tools/capa_auto_example.py`

## Uso
Nel punto in cui apri la connessione (on_connect), fai:
```python
from tools.capa_auto import CapaAuto

class IOAdapter:
    def __init__(self, send_control, recv_control, publish_ckb):
        self.send_control = send_control
        self.recv_control = recv_control
        self.publish_ckb = publish_ckb

capa = CapaAuto(IOAdapter(send_control, recv_control, publish_ckb), config_path="tools/capa_config.json")
ok = capa.ensure_ready(my_peer_id=MY_ID, peer_id=REMOTE_ID)
assert ok, "CAPA failed"
```

- `send_control(b: bytes)` invia frame sul canale di controllo (JSON o CBOR).
- `recv_control(timeout: float)` legge un frame dal canale di controllo (deve tornare `bytes`).
- `publish_ckb(kind, blob, **meta)` pubblica D0/D1/D3 sul canale semantico `'CKB'` (come fai già).

## Cosa fa
- Tenta un `CAPA_RESUME` usando gli hash salvati.
- Se non possibile, esegue `CAPA_INIT/ACK` con negoziazione.
- Pubblica automaticamente i layer **richiesti** (D0/D1/D3 + **D1 supplement** se presente).
- Effettua lo scambio `READY ↔ READY` e salva il profilo del peer.
