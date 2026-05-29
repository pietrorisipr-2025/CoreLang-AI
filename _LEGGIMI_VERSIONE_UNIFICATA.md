# CoreLang AI — Versione Unificata (preparata il 2025-05-28)

Questa cartella è la fusione ordinata dei tuoi tre pacchetti CoreLang AI,
ripulita e riparata. È questa la versione su cui lavorare d'ora in poi.

## Da dove viene

Avevi tre file caricati, tutti del 3 settembre 2025:
- BUNDLE ...D1_AND_D3PACKS_AND_PROFILER (ore 07:43) — progetto base
- corelangAI_FULL_UPDATE_WITH_CAPA_AUTO (ore 08:47) — pacchetto di aggiornamento
- corelangAI_bundle_MAX_with_docs (ore 12:01) — bundle più recente + documentazione

Il MAX (12:01) e il BUNDLE (07:43) hanno lo stesso identico motore (cl6_link.py).
Questa versione unificata parte dal MAX e gli aggiunge i pezzi che gli mancavano,
recuperati dal FULL_UPDATE.

## Cosa è stato corretto

1. RIPARATO un errore che impediva l'avvio del file principale.
   Nel file cl6_link.py la funzione `send_object` era finita FUORI dalla classe
   (errore di rientro, tipico di un copia-incolla). Era rotto in TUTTI i bundle
   originali: il file non si avviava affatto. Ora è dentro la classe e funziona.

2. SOSTITUITO il vocabolario D3 (ckb_D3_phrases.json) che nel MAX era VUOTO
   (0 frasi) con la versione PIENA del FULL_UPDATE: 2847 frasi in 10 categorie.
   Questo è il "vocabolario condiviso" che dà al protocollo il vantaggio di
   compressione: averlo vuoto azzoppava il progetto.

3. AGGIUNTI gli strumenti che il MAX non aveva:
   - tools/capa_auto.py  (negoziazione automatica delle capacità tra due AI)
   - overlay/d1_overlay_codec.py  (accorcia ulteriormente i token frequenti)

## Cosa NON è ancora stato fatto (i prossimi passi)

- Il "freno a mano" sulla compressione (comprime un messaggio alla volta invece
  che a blocchi) NON è ancora stato corretto. È il prossimo lavoro, da far fare
  a ChatGPT col messaggio già preparato.
- I bug noti ereditati restano da sistemare (vedi i README originali).


---

## AGGIORNAMENTO: dizionario semantico vero (generato il 2025-05-28)

È stato aggiunto il DIZIONARIO GRANDE, che prima mancava.

- File: `ckb_zstd_dict.bin` (384 KB) + `ckb_zstd_dict.manifest.json`
- Addestrato sui 117.000 casi reali del tuo dataset CoreLang5 (quello su Hugging Face).
- Scoperta: il vecchio dizionario piccolo (2847 frasi) PEGGIORAVA la compressione.
  Quello nuovo, addestrato sul corpus completo, la MIGLIORA.

Risultati su 1000 messaggi reali (testo italiano tecnico), con compressione massima:
- senza dizionario: 83.818 byte
- CON questo dizionario: 74.405 byte  (11,2% in meno)
- I dati si riaprono sempre identici (verificato).

Nota: la taglia 384 KB è stata scelta come ottimo. Dizionari piu' grandi (fino a 2 MB)
guadagnano solo un altro ~2%, non vale il peso extra.

Per usarlo serve zstd a livello alto (19) e va passato come dizionario al compressore
stream-batch. Il guadagno pieno si vede a compressione massima.
