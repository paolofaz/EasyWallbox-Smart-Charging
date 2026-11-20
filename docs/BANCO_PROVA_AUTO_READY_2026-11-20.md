# Banco prova — Automatico pronto e avvio posticipato (20/11/2026)

**STATO: simulatore offline, non collegato ad Home Assistant.** Nessun comando
ESPHome, BLE, Home Assistant, switch, DPM o auto. La beta installata 0.2.0b5
rimane invariata. `start_routine.py` è un modello di decisioni, non un executor.

## Decisioni / proposte / dati mancanti

### Deciso e invariato
- DPM fisico sempre attivo e responsabile della protezione elettrica.
- Automatica gestisce la sessione; Manuale e Pausa esplicita non devono
  ricevere alcuna imposizione di Johnny.
- ESPHome resta unico canale BLE. Il limite EV impostato e quello confermato
  sono fatti distinti, come è distinta la potenza Shelly effettivamente erogata.
- Dopo riavvio, modifica manuale, BLE offline o sessione incerta: niente
  ripristino automatico del DPM; nessun retry cieco.
- Johnny V2 `shadow_v2.py` rimane con le soglie candidate **invariate**:
  forte 2 minuti, buffer moderato 3 minuti, ripristino forte 15 minuti
  e buffer 10 minuti. Nessun ripristino a due passi in questo banco.
- I log del 20/11 (10:47–13:21) contengono un episodio del caffè:
  11:00:34 carico ~1,18 kW, 11:03:20 cap virtuale 2,8 kW, 11:03:23
  carico ~0,11 kW, 11:18:24 restore 4,2 kW. Le potenze EV non sono misure
  reali; l'auto del laboratorio è virtuale, senza limiti SOC/partenza.

### Candidato da approvare prima di attuazione: Automatico pronto
- Se modalità AUTO, cavo **certamente** scollegato sia dalla wallbox sia
  dai segnali auto, telemetria BLE valida, DPM attivo e limite originale
  positivo confermato, si può proporre **una sola volta** una pausa
  pre-collegamento DPM = 0 A. Questo armamento è opt-in e il default del
  banco prova resta disabilitato.
- Una volta confermato DPM 0, si è in `AUTO_READY`. Nessuna azione
  periodica con cavo scollegato. Se l'utente cambia manualmente lo switch,
  non comandare nuovamente OFF: passare a riconciliazione.
- In fase di startup HA non inventare un lease per un DPM già a 0:
  ownership sconosciuta -> `RECONCILE`.
- Problema reale da accettare: con HA/BLE indisponibile e DPM 0 la successiva
  ricarica potrebbe non partire. Serve UI chiara e procedura manuale di
  emergenza; niente finta garanzia di partenza.
- Quando l'auto viene collegata, attendere identità univoca e SOC/target
  freschi. Se target già raggiunto, nessun riavvio.
- Orario di **inizio preferito** facoltativo distinto dalla **partenza
  desiderata** e dal suo `latest_safe_start`. Se si può aspettare,
  mantenere la pausa che Johnny possiede; se il target richiede anticipo,
  avviare prima dell'ora preferita e spiegare il motivo.
- Quando l'avvio è consentito e la pausa è di Johnny: prima chiedere il
  massimo EV della sessione (nel nostro caso *candidato* 4,2 kW), attendere
  la conferma `Power set` della wallbox; poi proporre il recupero
  dell'ultimo limite DPM originario **confermato** (es. 4,4, non hardcoded).
  Anche qui una sola richiesta alla volta, niente retry ciechi.
- Soltanto dopo stato `Charging` e misurazione Shelly coerenti si considera
  la ricarica realmente avviata in NORMAL. In seguito Johnny V2 può
  decidere i cap, se il planner reale concede budget.
- Se si seleziona Manuale, nessun comando per portare DPM da 0 a >0:
  la UI segnala che l'utente deve intervenire direttamente.

### Materiale ancora da implementare
- Persistenza della vera ownership, id di sessione univoco su reboot, ACK,
  timer di timeout, lock e operazioni idempotenti.
- Config flow / Lovelace per attivare AUTO_READY e impostare l'ora di avvio
  preferita, senza creare sensori inutili.
- Adapter reale delle entità ESPHome (richiesta EV, conferma EV, DPM
  confermato, fault, telemetria, collegamento), con TTL e verifica unità
  per ogni sorgente; contratto di DPM e step da convalidare sull'hardware.
- Gestione della Fiat con limite SOC software e della Kia che arresta da sé;
  niente doppio proprietario con le automazioni Fiat/mattina legacy.
- Capacità di ri-armarsi dopo riavvio solo tramite riconciliazione approvata.
  Se il DPM è già a zero per intervento utente, non farlo proprio per errore.
- Test hardware supervisionati con consenso specifico, a carico dell'utente;
  nessuna attivazione automatica a seguito di questi test offline.

## API del simulatore

`evaluate_bench(BenchInputs(...)) -> BenchAdvice(...)` produce
`offer_park`, `offer_ev_limit`, `offer_resume` o `none`. Qualunque
`offer_*` contiene sempre `simulation_only=True` e
`requires_explicit_authorization=True`. Nessuna funzione di dispatcher.

Il parametro `data_valid` è soltanto un contratto fittizio del test:
il futuro adapter deve validare **separatamente** ogni lettura (età, unità,
presenza e coerenza), non considerare veri dati solo per un booleano.

## Test e rollback

I casi di `tests/test_start_routine.py` coprono sconnessione coerente,
prearm solo una volta, intervallo di attesa, urgenza che anticipa l'ora,
ordine EV→DPM, modalità Manuale, SOC ignoto, handoff errato, DPM esterno,
reboot, mancata conferma e divieto di retry.

La suite CI del branch deve essere verificata sul commit finale. Per
rollback non serve intervenire sulla wallbox: il modulo è isolato e
**non viene importato dal coordinatore di Home Assistant**.
