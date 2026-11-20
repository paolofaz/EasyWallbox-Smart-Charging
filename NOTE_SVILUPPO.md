# Diario tecnico — EasyWallbox Smart Charging RC

## Stato del branch RC — 20 novembre 2026

**Un solo progetto:** custom integration nativa Home Assistant, dominio
`easywallbox_smart`, con controllo della wallbox tramite il firmware ESPHome
già esistente. Nessuna modifica al firmware.

**Requisiti confermati:**
- Uno o più sensori di consumo domestico selezionabili liberamente, e
  uno Shelly dedicato alla wallbox, senza associazione a piani specifici.
- Uno o più veicoli, con identificazione tramite cavo e una sola scelta
  fra target SOC fisso e target SOC proveniente da una entità HA.
- Potenza prudenziale per la stima dei tempi distinta dal limite EV
  realmente comandato.
- DPM positivo configurato per la matematica (es. 4,4 kW) distinto dal
  valore 0 A che indica parcheggio reale.
- Evento cavo ON→OFF, con Shelly EV sotto 30 W per 30 s: una singola
  richiesta Start-Stop OFF, confermata da ESPHome.
- Evento cavo OFF→ON: aggiornamento auto dopo 20 s, una sola richiesta;
  attesa nuovi dati, calcolo SOC/partenza, verifica limite EV ordinario
  (4,0 kW), quindi Start-Stop ON quando autorizzato.
- Automatico/Manuale per sessione, programmazione differita, eccezione
  partenza e Carica subito. Manuale torna Automatico allo scollegamento.
- Stabilizzatore lento con forti, moderati, finestra 5/7 in LIMITED,
  ripristino dopo 15 min, boost solo con ≤60 min di margine e isteresi
  d'uscita ≥75 min. DPM sempre incaricato dei picchi rapidi.
- Nessun controllo reale su dati obsoleti/contraddittori, nessuna
  ripetizione cieca dei comandi, un solo esecutore elettrico.
- Autorizzazione Controllo reale OFF dopo ogni riavvio/reload.

**Pulizia del codice del branch:** eliminato il vecchio laboratorio
virtuale, le sue scritture JSONL e i relativi controlli. Eliminato
il riferimento Johnny dalle entità e dalle etichette visibili.
Sostituito il vecchio Config Flow per il target SOC con una scelta
guidata fra una percentuale fissa e una entità. Eliminata la vecchia
documentazione che suggeriva di installare file Lovelace con
segnaposto per due piani o due auto. La dashboard autoprodotta
resta da implementare/testare; non va dichiarata già disponibile.

**Verifiche:** CI Python 3.12/3.13, Home Assistant hassfest,
HACS/Marketplace, test controller e della policy. Non scambiare
test offline per collaudo fisico del DPM e degli ACK BLE.

**Revisione repository:** mantenere il solo branch `RC`;
`main`, `rifondazione-evcc`, `stabilizzatore-m1` e
`sviluppo-test` sono obsoleti. È necessario che un amministratore
sposti PRIMA il branch di default da `main` a `RC`, quindi elimini
gli altri quattro branch. Il connettore GitHub attuale non espone
quelle azioni amministrative. Le vecchie release/tag vanno gestite
separatamente; non rimuoverle inavvertitamente dalla cronologia.

**Da verificare in HA:** rimozione corretta dell'installazione
precedente, caricamento del Config Flow RC e conferma di tutte
le entità; test fisico solo successivamente e sotto supervisione.
