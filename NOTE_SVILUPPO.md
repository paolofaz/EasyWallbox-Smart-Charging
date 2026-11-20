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

**Versione correttiva pubblicata:** `v0.3.0rc2` come prerelease GitHub. Corregge selezione target SOC, configurazione libera dei sensori domestici e rimuove completamente il laboratorio. I test CI Python 3.12/3.13, hassfest e Marketplace sono passati; non eseguito ancora collaudo sulla wallbox reale. Il branch GitHub predefinito è ancora `main` fino all'intervento dell'amministratore.


## Correzione RC successiva alla 0.3.0rc2 — planner e gestione auto

**Regressione riconosciuta:** la 0.3.0rc2 chiedeva una inesistente
"potenza AC media prudenziale" per ogni auto e usava un valore
predefinito 2,4 kW per stimare il tempo e il budget. Questo contraddiceva
l'architettura approvata e non deve essere riproposto.

**Modifica:**
- Eliminato il campo dal Config Flow, dalle traduzioni e dai profili
  veicolo salvati quando vengono modificati. Nessun altro valore
  statico in kW prende il suo posto.
- Il planner calcola un tasso AC candidato dalla potenza casa senza EV
  (campioni recenti RAM, finestra massima 20 minuti, percentile 75)
  e dal DPM **positivo configurato**, limitato al cap EV ordinario.
  Se vi è una storia attendibile di potenza EV effettivamente misurata
  dallo Shelly, questa può ridurre il tasso stimato.
- Prima di avere dati validi, il margine resta sconosciuto. La
  partenza posticipata rimane valida; l'unico uso del cap EV fisico
  in assenza di una media è come limite superiore teorico per
  impedire un avvio più tardivo del massimo già ottimistico.
- Non sono creati nuovi sensori né campioni continuativi nel Recorder.
- Opzioni dell'integrazione: **aggiungi, modifica, rimuovi** veicolo,
  con campi completi (sensori, capacità, rendimento, refresh, orari,
  target SOC da entità o fisso) e controlli di unicità. Ultimo
  veicolo non eliminabile. I profili nuovi e modificati sono salvati
  in `entry.options["vehicles"]`; dopo il salvataggio
  `OptionsFlowWithReload` ricarica l'integrazione e lascia il
  controllo reale disattivato.
- I vecchi profili con `planning_rate_kw` vengono letti in
  compatibilità ma il campo non viene più usato; il salvataggio
  di un profilo lo elimina. Non si modifica manualmente `.storage`.

**Verifiche:** test indipendenti sui dati casa / potenza EV,
stima sconosciuta, casi limite; test concreti GUI con validazione
voluptuous reale e host HA simulato per aggiunta, modifica,
eliminazione e target. Restano necessari test installazione reale
e collaudo elettrico supervisionato.

**Stato repo:** sviluppo sul branch `RC`; `main` rimane invariato
senza autorizzazione di merge. Il changelog e la release devono
essere pubblicati solo dopo qualità CI verde.
