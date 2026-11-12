# Diario tecnico — EasyWallbox Smart Charging

## 2026-11-12 — Commit iniziale, infrastruttura pre-alpha

### Stato iniziale verificato
- Repository: `paolofaz/EasyWallbox-Smart-Charging`, pubblico, permesso di scrittura.
- `main` conteneva soltanto `LICENSE` (MIT), commit `a5c2d20f24b562542692e92bfac745967e2229d4`.
- `sviluppo-test` assente; creato dal commit iniziale dopo autorizzazione dell'utente.
- **Non toccare `main` e non creare PR o issue non richieste.**

### Modifiche introdotte
- Struttura custom integration sotto `custom_components/easywallbox_smart`.
- Manifest e `hacs.json` predisposti per Marketplace Home Assistant; versione tecnica `0.0.1`, **non** release v0.1.
- Config Flow a tre passi e Options Flow per mapping di stati HA esistenti; traduzioni IT/EN.
- Entry caricabile/scaricabile, **senza polling, sensori calcolati, servizi o comandi**.
- Test statici offline e workflow CI limitato al branch `sviluppo-test`.
- README con setup, rollback, limiti e roadmap.
- **Nuovo requisito esplicito**: dashboard Lovelace ad hoc parte obbligatoria della v0.1. Design preliminare in `docs/LOVELACE.md`.

### Motivazioni
- Separare mappatura entità e futura logica del planner.
- Impedire in questa milestone l'uso accidentale di controlli BLE/HA.
- Nessun entity_id domestico hardcodato; input GUI configurabile.
- Pochi file e nessuna dipendenza Python aggiuntiva.

### Verifiche / limitazioni
- Verifica preliminare: documentazione ufficiale Home Assistant Config Flow, Options Flow, manifest e Marketplace (12/11/2026).
- Test statici definiti per esecuzione in CI e locale; **esito esecuzione da registrare separatamente**.
- `hassfest` / HACS action **non ancora eseguite**.
- Installazione/config flow/Options Flow su una istanza HA reale **non ancora verificati**.
- Nessuna release/tag; nessuna prova di compatibilità con la versione HA dell'utente.

### Prossimi passi
1. Verificare test CI statici e installazione HA con la versione effettiva.
2. Raccogliere entity_id reali (Fiat/Kia, ESPHome, tre Shelly) e confermare unità/staleness.
3. Aggiungere lettura/qualità dati con test dedicati.
4. Implementare stime, planner e sensori simulati.
5. Realizzare **dashboard Lovelace** dedicata prima di chiudere la milestone v0.1.

### Decisioni di sicurezza immutate
DPM attivo e responsabile dei picchi. Firmware ESPHome non modificato. Automazioni Fiat SOC e potenza mattutina mantenute. Ogni controllo reale è riservato a release future dopo autorizzazione e collaudo.

## 2026-11-12 — Processo pre-release dal branch sviluppo-test

### Decisione approvata
- L'utente desidera installare direttamente dal Marketplace anche durante lo sviluppo.
- Pubblicare **pre-release 0.x** da `sviluppo-test`, mantenendo `main` invariato fino a 1.0 esplicitamente approvata.
- Alla v1.0 valutare rimozione delle pre-release obsolete **solo dopo migrazione e verifica rollback**, evitando cancellazioni automatiche.

### Modifiche
- Aggiunto workflow `.github/workflows/release-test.yml`: su modifica del manifest o del workflow nel branch di sviluppo, esegue test statici e crea release GitHub pre-release con tag uguale al manifest. Rifiuta tag esistenti privi di release e versioni fuori serie 0.x.
- Aggiunte note `docs/releases/0.0.1.md` e istruzioni Marketplace nel README.
- Nessun comando al caricatore/automobili, nessuna modifica firmware, nessuna modifica `main`.

### Da verificare
- **Verificato:** workflow Publish test pre-release riuscito (run `43261535382`), tag `0.0.1` pubblicato come pre-release sul commit `d6c5dbd2c0fbd563de85930a3182daa27a9d7387`; verificato anche il test statico (run `43261535410`). Prima esecuzione del workflow fallita per regex troppo escapata, corretta in commit successivo; nessun tag/release creato da quella prima esecuzione.
- Possibile limite del Marketplace nel registrare una custom repository con `main` ancora privo di `hacs.json`: non installare il fallback di `main`.
- Installazione e Config Flow su Home Assistant 2026.11 dell'utente.
- Validazione hassfest/HACS action e successive verifiche di compatibilità reale.

## 2026-11-12 — Passaggio alle release normali 0.x

### Richiesta utente e motivo
- L'aggiunta del repository personalizzato nel Marketplace non ha funzionato con la pre-release `0.0.1`; l'errore esatto lato HA resta da acquisire.
- Scelta: pubblicare release **normali** anche per le versioni 0.x, mantenendo il codice di sviluppo e i tag provenienti esclusivamente da `sviluppo-test`.
- Una release normale in questo contesto **non significa software collaudato o pronto per produzione**.

### Modifiche
- Workflow adattato per creare release normali 0.x e convertire la release 0.0.1 già esistente, senza spostare il tag e senza nuove versioni inutili.
- README aggiornato per l'installazione senza switch Pre-release.
- Il branch `main` non viene modificato. `main` contiene soltanto `LICENSE` e potrebbe impedire il riconoscimento del repository nel Marketplace: **ipotesi da verificare** e non risolvibile con la sola tipologia release.

### Verifiche aperte
- **Verificato 12/11/2026:** workflow `Publish 0.x test releases` riuscito (run `43285119169`), release `0.0.1` trasformata in normale (`prerelease=false`) mantenendo tag e commit originari. Test statici riusciti (run `43285119190`).
- Nuovo tentativo dal Marketplace e testo esatto dell'errore se permane.
- Se emerge la necessità di aggiungere file a `main`, chiedere prima consenso esplicito; la policy corrente vieta modifiche a `main`.

## 2026-11-12 — V0.0.2: profili veicolo senza vincolo marca

### Feedback test reale
- Marketplace ha installato correttamente la release 0.0.1 su HA 2026.11.
- Config Flow wallbox visualizzato e compilato; schermata auto Fiat/Kia mostrata, ma l'utente si è fermato perché era richiesto un inesistente sensore target. Non è ancora verificato il completamento integrale del flow.

### Decisioni approvate
- Da 1 a N veicoli, nome e sensori specifici, senza nomi Fiat/Kia codificati.
- Obiettivo SOC **abituale** numerico in Opzioni; override di sessione nella Lovelace v0.1 (mostra un unico target effettivo) e **Escludi obiettivo** per lasciare che l'auto interrompa autonomamente.
- Limite interno auto non letto. Se auto interrompe prima dell'obiettivo HA, annotare arresto prematuro senza ritentare comandi.
- DPM 0 A come futura azione a target HA raggiunto **solo dopo fase simulazione e autorizzazione**; non inviare comandi se ricarica è già arrestata dalla macchina. Conferme fisiche richieste.

### Codice 0.0.2
- Nuova selezione ripetibile veicoli nel Config Flow; obiettivo abituale e capacità utilizzabile configurabili; gestione profili in Options Flow e ID stabile.
- Test di normalizzazione profili, duplicati e validazione; manifest aggiornato per release normale 0.0.2.
- Vecchie mappe auto 0.0.1 non migrate automaticamente: manca la capacità batteria, vietato indovinarla. Riconfigurazione necessaria nelle Opzioni.

### Verifiche da completare
- **Verificato**: test CI statici e pubblicazione release normale 0.0.2 riusciti (runs 43291593790 e 43291593712).
- Test su HA reale: installazione, aggiunta due veicoli, aggiunta terzo, modifiche/ rimozione, reload, aggiornamento da 0.0.1.
- Hassfest/HACS action e test Config Flow con mock HA (non coperti dai test statici).
- Nessuna entità di sessione, dati o Lovelace funzionale in 0.0.2.

## 2026-11-12 — Correzione 0.0.3: migrazione ConfigEntry

- Durante la revisione di 0.0.2 verificata la documentazione Home Assistant 2026.11 sulla migrazione: quando `ConfigFlow.VERSION` passa da 1 a 2 serve `async_migrate_entry`.
- 0.0.3 implementa la migrazione: mantiene i dati originali di 0.0.1, aggiunge una lista vuota `vehicles` senza inventare capacità batteria o ID e aggiorna la versione della ConfigEntry.
- I profili devono essere completati attraverso le Opzioni; nessun comando wallbox o auto.
- Questa release sostituisce 0.0.2 come candidata alla prova reale. Test HA e Marketplace effettivo ancora aperti.
- **Verificato**: test statici e pubblicazione GitHub 0.0.3 riusciti (runs 43291913566 e 43291913523); tag 0.0.3 punta al commit 006e5f97d97d7053ff00bd55b34a73f549be5abd. `main` invariato.

## 2026-11-12 — Requisito target SOC 100% e terminologia DPM

### Decisioni dell'utente (sostituiscono indicazioni precedenti)
- **Eliminata** l'opzione «Escludi obiettivo». Il target SOC può essere 100%, sempre con previsione energetica/temporale fino al 100%.
- Target **inferiore al 100%**: una futura release di controllo potrà considerare una pausa raggiunto l'obiettivo, con stato coerente e conferma indipendente. Non attiva in simulazione.
- Target **100%**: **mai azionare lo switch di pausa ricarica per raggiungimento SOC**, anche se il valore raggiunge 100%; lasciare che il veicolo termini autonomamente l'eventuale bilanciamento delle celle. Mai riavviare una pausa manuale per effetto di questa regola.
- Terminologia obbligatoria: **switch di pausa ricarica** = comando Start-Stop ESPHome, pausa con **limite DPM a 0 A**. **Il DPM deve sempre rimanere attivo e non deve mai essere impostato OFF**. La pausa del flusso non equivale a disattivazione DPM.
- Distinguere comando, conferma, carica reale e potenza Shelly. Stop automatici futuri solo dopo consenso e test.

### Modifiche nel branch di test (non rilasciate)
- README e specifica Lovelace allineati; conservato nel diario lo storico delle decisioni superate.
- Aggiunto modulo puro `soc_policy.py` che valuta esclusivamente la soglia SOC e test offline (nessun servizio Home Assistant, nessun comando BLE).
- Nessun incremento del manifest e nessuna nuova GitHub release per questa sola decisione; includere nel prossimo rilascio con il planner v0.1.

## 2026-11-12 — Correzione tipo integrazione (0.0.4)

### Problema segnalato
- Home Assistant mostra EasyWallbox Smart Charging nella categoria **Helper** a causa del valore `integration_type: helper` introdotto nello scaffolding.

### Correzione e motivazione
- Documentazione ufficiale Home Assistant consultata: `helper` per entità di ausilio; `hub` per una integrazione che aggrega più dispositivi/servizi.
- Cambiato solo `integration_type` da `helper` a **`hub`**; mantenuto `iot_class: calculated`.
- Incrementata versione manifest a **0.0.4**, test statico esplicito sul tipo; README e note release aggiornati. Nessun cambio a config entry, firmware, DPM, automazioni, servizi o comandi.
- La regola della pausa di ricarica per target 100%, definita nel commit precedente, è inclusa nel codice sorgente ma **non ancora collegata a un controllore**.

### Verifiche ancora necessarie
- **Verificato:** test statici CI superati (run `43305338006`) e release GitHub **0.0.4** pubblicata regolarmente (run `43305338160`), tag su commit `7f7b41d03a0ca8d42d19b9f7a49443d78e51b072`. Restano da verificare installazione Marketplace su HA 2026.11, riavvio e classificazione visualizzata nell'istanza dell'utente.
- Validazione runtime Config Flow e compatibilità completa non ancora certificata.
