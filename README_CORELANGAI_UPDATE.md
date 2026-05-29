# CoreLangAI — Aggiornamento con D1 completi, D3 packs e Profiler

Questa guida ti spiega **dove mettere i file** e **come usarli** su **Windows** (vale anche su macOS/Linux cambiando i percorsi).

---

## Cosa ti ho preparato
- **Bundle base (tuo)**: `BUNDLE_corelangAI_FULL_1_0_ZSTD_INTEGRATED_WITH_D1_20250902-234504.zip`
  - contiene D0, **16×D1**, `d1.dict`/`d3.dict`, `ckb_layers_manifest.json`
- **D3 packs specializzati** (tutti i settori): `corelangAI_D3_packs_*.zip`
  - `dict/d3_packs/ckb_D3_<sector>.json` (10 file) + `ckb_D3_phrases_ALL_PACKS.json`
- **Profiler**: `tools/d3_profiler.py` e `tools/clai_d3_profiler_hook.py`
  - per **generare D3** da log reali e tenere vivo il vocabolario

---

## Struttura consigliata delle cartelle
```text
corelangAI\
  dict\
    ckb_D0_control.bin
    ckb_D1_*.bin              # 16 blocchi
    ckb_D3_phrases.json       # default (puoi sostituirlo con ALL_PACKS o un pack)
    d3_packs\                 # (opzionale) tutti i pack specializzati
      ckb_D3_logic.json
      ...
      ckb_D3_domain_adapters.json
      index.json
  src\clai\dicts\
    d1.dict
    d3.dict
  tools\
    d3_profiler.py
    clai_d3_profiler_hook.py
  ckb_layers_manifest.json
```

---

## Procedura di aggiornamento (copia/incolla)
1. **Scompatta** il tuo bundle WITH_D1 in `C:\path\to\corelangAI\` (o dove tieni il progetto).
2. **Copia i D3 packs**:
   - da `corelangAI_D3_packs_*.zip` copia la cartella `dict/d3_packs/` dentro `corelangAI\dict\`.
   - scegli cosa usare come default:
     - **Tutto**: copia `ckb_D3_phrases_ALL_PACKS.json` in `corelangAI\dict\ckb_D3_phrases.json`
     - **Solo un settore**: copia/limita `dict/d3_packs/ckb_D3_<sector>.json` come `corelangAI\dict\ckb_D3_phrases.json`
3. **Copia il Profiler** in `corelangAI\tools\`:
   - `d3_profiler.py`, `clai_d3_profiler_hook.py`
4. (Facoltativo) Verifica zstd dict:
   - se mancano `src\clai\dicts\d1.dict` e `d3.dict`, copiali dal bundle in `corelangAI\src\clai\dicts\`.

---

## Come pubblicare i dizionari a runtime (bootstrap)
Dopo l’**handshake CAPA** del link, pubblica i layer dal manifest:
```python
import json, os
MANIFEST = "ckb_layers_manifest.json"
base_bins = os.path.join(os.path.dirname(MANIFEST), "dict")
man = json.load(open(MANIFEST, "r", encoding="utf-8"))

# D0
for f in man["layers"]["D0"]["files"]:
    blob = open(os.path.join(base_bins, f["file"]), "rb").read()
    link.publish_semantic('CKB', blob, chid=1)

# D1
for b in man["layers"]["D1"]["blocks"]:
    blob = open(os.path.join(base_bins, b["file"]), "rb").read()
    link.publish_semantic('CKB', blob, chid=1)

# D3 (default o pack scelto)
d3_default = os.path.join(base_bins, "ckb_D3_phrases.json")
if os.path.exists(d3_default):
    link.publish_semantic('CKB', open(d3_default, "rb").read(), chid=1)
```

Per usare **solo un pack** in aggiunta o al posto del default:
```python
link.publish_semantic('CKB', open('dict/d3_packs/ckb_D3_systems.json','rb').read(), chid=1)
```

---

## Profiler: come raccogliere log e generare un nuovo D3
1) **Integra l’hook** nel tuo codice (poche righe):
```python
from tools.clai_d3_profiler_hook import D3Profiler
profiler = D3Profiler(log_path="logs/corelang_d3_profile.log")
# quando spedisci o ricevi testo semantico:
profiler.observe("dictionary block D1 loaded")
profiler.observe(user_message_text)
profiler.observe(peer_message_text)
```

2) **Genera un D3 incrementale** dai log raccolti:
```powershell
# Esempio Windows PowerShell
cd C:\path\to\corelangAI
python .\tools\d3_profiler.py --packs .\dict\d3_packs --txt .\logs\corelang_d3_profile.log --merge .\dict\ckb_D3_phrases.json --out .\dict\ckb_D3_phrases.json
```
- `--packs` usa i pack per misurare la copertura attuale
- `--txt` è il tuo **log**
- `--merge` parte dal D3 attuale e aggiunge i **nuovi OOV** (filtrati/deduplicati)
- `--out` sovrascrive il D3

3) **Ricarica** il D3 in runtime (pubblicalo di nuovo) o al prossimo avvio.

---

## Parametri consigliati
- `residual_policy: "auto-byte-min"`
- `anchor_every: 8`
- `ttl_summary_sec: 5.0`, `ttl_residual_sec: 7.0`
- **FEC**: OFF (`fec_group: 0`) finché non abiliti la riparazione RX
- **zstd**: abilitato per il residuo (usa `d1.dict`/`d3.dict` già inclusi)

---

## Rollback
- Se vuoi tornare indietro, rimetti il vecchio `ckb_D3_phrases.json` (o rinomina un pack).

---

## FAQ rapide
- **I `.dict` zstd contengono token D3/D1?** No. Sono solo dizionari di **compressione** byte-level.
- **Posso avere solo “systems + io”?** Sì: pubblica quei due pack e non l’unione.
- **D3 cresce troppo?** Usa il profiler con `--min_freq` più alto (es. 3-5) e limita `--top_k`.