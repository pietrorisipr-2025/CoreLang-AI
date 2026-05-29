# CL5XLink v6.6 — PQ defaults + Residual policy auto

## QPROFILE (PQ pronti)
```python
from cl5x_qprofile_defaults import get as qp_get, best_for_dim as qp_best
qp = qp_get('pq-768')              # profilo pronto
# oppure:
qp = qp_best(1536)                 # calcolo automatico per dimensione
link = CL5XLink(tx, on_object=..., qprofile=qp)
```

## Residual policy dinamico
```python
# auto-byte-min (default): sceglie tra DLT1 e MSD2 quello con meno byte
link = CL5XLink(tx, on_object=..., residual_policy='auto-byte-min')

# forzare uno dei due
link = CL5XLink(tx, on_object=..., residual_policy='delta-only')
link = CL5XLink(tx, on_object=..., residual_policy='msd2-only')

# metriche
print(link.stats())  # include 'auto_choice', 'bytes_chosen', 'bytes_other'
```