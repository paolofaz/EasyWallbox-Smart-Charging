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
- Workflow di pubblicazione e presenza della release/tag `0.0.1` su GitHub.
- Possibile limite del Marketplace nel registrare una custom repository con `main` ancora privo di `hacs.json`: non installare il fallback di `main`.
- Installazione e Config Flow su Home Assistant 2026.11 dell'utente.
- Validazione hassfest/HACS action e successive verifiche di compatibilità reale.
