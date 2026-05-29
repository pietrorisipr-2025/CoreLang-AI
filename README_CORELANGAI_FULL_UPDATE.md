# CoreLangAI — Pacchetto FULL UPDATE

Questo pacchetto aggiorna CoreLangAI con tutto il necessario:
- **D3 aggiornato** (ALL_PACKS) e i **pack tematici**
- **D1 supplementare** (CL5B-ref v1) costruito dalle note
- **Overlay D1** (alias a livello utente) — opzionale
- **Profiler D3** (script + hook)
- **Builder D1 di riferimento** (con bin già generati) — opzionale
- **clean_libs** (liste token per blocco) — per futuri rebuild D1

> Funziona su Windows; su macOS/Linux cambia solo la sintassi dei percorsi.

---

## 1) Backup (consigliato)
Fai una copia della tua distro CoreLangAI prima di aggiornare (cartella `corelangAI\` intera).

---

## 2) Copia file (minimo indispensabile)
Se vuoi solo aggiornare e partire subito, copia questi due file nella tua distro:
- `dict\ckb_D3_phrases.json`  → sostituisce il tuo file esistente
- `dict\ckb_D1_supplement_notes.bin`  → nuovo (si pubblica dopo i tuoi 16×D1 standard)

> Il resto è **opzionale** ma utile (pack tematici, profiler, overlay, builder, clean_libs).

---

## 3) Pubblicazione layer (bootstrap)
Dopo handshake **CAPA**, pubblica in quest'ordine:

```python
# D0
link.publish_semantic('CKB', open('dict/ckb_D0_control.bin','rb').read(), chid=1)

# D1 standard (16 blocchi)
for fname in sorted(os.listdir('dict')):
    if fname.lower().startswith('ckb_d1_') and fname.lower().endswith('.bin') and 'supplement' not in fname.lower():
        link.publish_semantic('CKB', open(f'dict/{fname}','rb').read(), chid=1)

# D1 supplementare (nuovo)
link.publish_semantic('CKB', open('dict/ckb_D1_supplement_notes.bin','rb').read(), chid=1)

# D3 aggiornato (ALL_PACKS)
link.publish_semantic('CKB', open('dict/ckb_D3_phrases.json','rb').read(), chid=1)
```

### Usare i **pack D3** specifici
Puoi (in aggiunta o alternativa al default) caricare pack tematici:
```python
link.publish_semantic('CKB', open('dict/d3_packs/ckb_D3_systems.json','rb').read(), chid=1)
link.publish_semantic('CKB', open('dict/d3_packs/ckb_D3_io.json','rb').read(), chid=1)
```
Puoi anche impostare un pack come **default** rinominandolo in `dict\ckb_D3_phrases.json`.

---

## 4) Profiler D3 (per crescere in modo mirato)
1. Integra l'hook per salvare un log (2 righe):
```python
from tools.clai_d3_profiler_hook import D3Profiler
profiler = D3Profiler(log_path="logs/corelang_d3_profile.log")
# osserva testi chiave in invio/ricezione
profiler.observe("dictionary block D1 loaded")
profiler.observe(user_message_text)
profiler.observe(peer_message_text)
```
2. Genera un D3 incrementale **dal log** (sovrascrivi il D3):
```powershell
python .\tools\d3_profiler.py --packs .\dict\d3_packs --txt .\logs\corelang_d3_profile.log --merge .\dict\ckb_D3_phrases.json --out .\dict\ckb_D3_phrases.json
```

---

## 5) Overlay D1 (senza builder, opzionale)
Per normalizzare/accorciare token frequenti lato utente (alias `~kxx`):
```python
from overlay.d1_overlay_codec import encode_text, decode_text
payload = encode_text(payload)    # prima di inviare
original = decode_text(payload)   # dopo aver ricevuto
```
Le mappe si trovano in `overlay\d1_overlay_map.json` (token→alias) e `d1_overlay_reverse.json` (alias→token).
> L'overlay è indipendente dai binari D1: non rompe la compatibilità.

---

## 6) Builder D1 di riferimento (opzionale)
Se vuoi rigenerare binari D1 dal contenuto di `clean_libs\*.clean.json`:
```powershell
python .\builder\build_d1.py .\clean_libs\logic.clean.json .\builder\bins\ckb_D1_logic.bin
```
A runtime puoi leggere i bin così:
```python
from builder.d1_loader_ref import parse_ref_bin
tokens = parse_ref_bin(open('builder/bins/ckb_D1_logic.bin','rb').read())["tokens"]
```
> Il formato è **CL5B-ref v1** (documentato nel README del builder). Se ti serve la compatibilità byte-per-byte col *legacy*, posso provare a retroingegnerizzare con esempi aggiuntivi.

---

## 7) Rollback
- Rimetti il vecchio `dict\ckb_D3_phrases.json` dal backup.
- Non avendo toccato i tuoi `ckb_D1_*.bin`, tornare indietro è immediato.
- Se usavi l'overlay, basta rimuovere la chiamata `encode_text/decode_text`.

---

## 8) Troubleshooting
- **Il peer non digerisce il D1 supplementare**: usa solo D3; poi valutiamo un builder legacy compatibile.
- **Prestazioni residue**: aggiungi pack tematici o genera D3 dai log con il profiler.
- **File mancanti**: assicurati che i file vadano sotto `dict\`, `tools\`, `overlay\`, `builder\`, `clean_libs\`.

Generato: 2025-09-03 08:29:42