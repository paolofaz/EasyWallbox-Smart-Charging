# EasyWallbox Smart Charging

**Stato 15/11/2026: nuova installazione da zero per Home Assistant, versione di sviluppo `0.1.0b1`, esclusivamente SIMULAZIONE.** La vecchia 0.0.13 è stata completamente rimossa dall'installazione dell'utente, quindi la nuova base non include migrazione. Non è stata pubblicata una release né eseguito il collaudo sulla HA reale.

## Prima installazione

**[Guida completa: installazione da zero](docs/INSTALLAZIONE_DA_ZERO.md)**

La nuova integrazione si configura tramite **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**. Scarica il codice dal branch `stabilizzatore-m1` e copia **solo** `custom_components/easywallbox_smart/` in `/config/custom_components/`; riavvia Home Assistant e aggiungi l'integrazione.

**Non usare HACS dal ramo predefinito `main` per questa prova**: non contiene la nuova base. Nessuna copia parallela della vecchia integrazione deve restare nello stesso dominio `easywallbox_smart`.

### Architettura

La wallbox EasyWallbox mantiene il **DPM autonomo attivo** e gestisce tutti i picchi elettrici; il firmware ESPHome continua a esporre BLE e conferme senza modifiche. L'integrazione legge soltanto entità Home Assistant. Non imposta potenza, non avvia né interrompe la ricarica e non contatta direttamente l'auto.

Il planner usa SOC, target, capacità, rendimento, potenza sostenibile e partenza per consigliare quando avviare la ricarica o attendere. Il supervisore lento osserva **solo P_casa = P_piano_terra + P_piano_primo** ed emette proposte virtuali `NORMAL/LIMITED`: un cap stabile per episodio, ripristino diretto dopo quiete, rimozione del cap virtuale se la partenza è in difficoltà. Il DPM rimane il controllore rapido e responsabile della protezione.

### Entità configurabili

- Due Shelly per potenza casa senza auto e un terzo Shelly per l'EV, tutti distinti.
- ESPHome EasyWallbox: `Car Connected`, `Charging`, `Telemetry Fresh`, `Charge power` (entità number in kW), `Power set` (sensore del limite confermato in kW).
- Uno o più veicoli con sensore cavo, SOC, target opzionale, capacità utile, rendimento, potenza sostenibile, partenza feriale e weekend.

Gli `entity_id` vengono scelti nella UI: Fiat 500e e Kia EV3 sono la prima installazione di prova, ma nessun ID è fisso nel codice. Il Config Flow genera un'entry **schema 1**, senza compatibilità o conversioni della vecchia 0.0.13. `validation.py` controlla mapping e opzioni, rifiuta sensori duplicati e input incoerenti.

### Entità proprie

Tre sensori (sessione, pianificatore, stabilizzatore) e un selettore per **Automatica / Manuale / Pausa / Carica subito**, **solo virtuali**. La selezione Pausa NON arresta la wallbox, Carica subito NON la avvia, e una proposta `reduce`/`restore` NON cambia il limite reale. Dopo riavvio HA con auto già collegata serve una riconciliazione esplicita. No stream continuo Shelly in idle, nessun Recorder per campione aggiunto.

## Test e limiti

- CI offline e con mock HA: **99 test superati** su Python 3.12 e 3.13 (15/11/2026), inclusi Config Flow e Options Flow simulati, validazione dei mapping, modalità sessione, timer e divieto di attuazione.
- Hassfest ufficiale Home Assistant: superato. **Questi test non equivalgono a installazione/GUI/Recorder collaudati sulla HA reale.**
- Le soglie 1,5/1,0 kW, quiete 10 min, budget 25% dello slack, modello DPM 4,3 kW sono **candidati del simulatore**, non limiti elettrici approvati.
- Non sono ancora presenti le eccezioni temporanee della partenza; non implementare tariffe, fotovoltaico o comandi alla wallbox senza decisione esplicita.
- Conservare le automazioni legacy Fiat limite SOC e riduzione mattutina finché non sarà autorizzata e verificata una migrazione reale.
- Non caricare PIN BLE, credenziali, file `.storage`, backup, storici privati o informazioni personali nel repository.

Il nuovo branch nasce dal commit iniziale con sola LICENSE. `main`, il repo firmware e i vecchi rami non sono modificati. Note tecniche in [NOTE_SVILUPPO.md](NOTE_SVILUPPO.md), modello in [docs/ARCHITETTURA_M1.md](docs/ARCHITETTURA_M1.md) e dashboard base in [docs/LOVELACE.md](docs/LOVELACE.md).
