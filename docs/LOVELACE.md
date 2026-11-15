# Dashboard Lovelace M2 — SIMULAZIONE

Questa dashboard utilizza soltanto card native Home Assistant. **Non offre comandi alla wallbox o alle auto.**

Dopo aver configurato l'integrazione, apri **Strumenti per sviluppatori → Stati**, cerca `easywallbox` e sostituisci gli ID nell'esempio: gli ID reali sono assegnati dal registro delle entità.

```yaml
type: vertical-stack
cards:
  - type: markdown
    content: |
      ## ⚡ EasyWallbox Smart Charging
      **SIMULAZIONE — NESSUN COMANDO**

      Il DPM fisico resta autonomo e operativo.
  - type: entities
    title: Sessione e piano
    entities:
      - entity: sensor.easywallbox_smart_charging_sessione_di_ricarica
        name: Veicolo e sessione
      - entity: sensor.easywallbox_smart_charging_pianificatore_partenza
        name: Rischio e margine partenza
      - entity: sensor.easywallbox_smart_charging_stabilizzatore_ricarica
        name: Cap virtuale e motivo
      - entity: select.easywallbox_smart_charging_modalita_sessione_solo_simulazione
        name: Modalità sessione — solo simulazione
  - type: markdown
    content: |
      Un cap proposto NON equivale a un comando inviato,
      confermato dalla wallbox o verificato dal contatore.
      Le metriche di SOC, energia residua e budget sono negli
      attributi dei sensori e restano stime.
```

## Selettore virtuale: utilizzo e riavvio

Il selettore presenta **Automatica**, **Manuale**, **Pausa (simulata)** e
**Carica subito (simulazione)**. Cambia **solo** la modalità del planner:
non invia uno Start, Stop o DPM 0 A e non cambia la potenza elettrica.
Un veicolo può risultare **fisicamente in carica** anche mentre
la modalità visualizzata è Pausa: la telemetria ha precedenza sulla UI.

- **Automatica:** il planner può proporre attesa/avvio e cap facoltativi se il budget lo consente.
- **Manuale:** il supervisore si ritira; non sovrascrive la scelta utente fino alla conclusione del collegamento.
- **Pausa:** il planner non propone nuovi avvii e non toglie da solo la pausa; occorre un'esplicita scelta utente o uno scollegamento accertato.
- **Carica subito:** raccomanda l'avvio immediato e non introduce cap stabilizzanti facoltativi; è sempre **virtuale**.

Se Home Assistant riparte con il cavo già presente, lo stato entra in
**RICONCILIAZIONE RICHIESTA**: il selettore può iniziare senza valore
selezionato finché non si imposta esplicitamente una modalità.
Non confondere una temporanea indisponibilità dei sensori con uno
scollegamento, e non interpretare `start_now` come avvio elettrico riuscito.

Gli `entity_id` YAML sono **esempi**: usare gli ID effettivamente creati
dall'integrazione nella propria istanza. Nessuna scheda va usata per
controllare il dispositivo prima del collaudo della versione attuativa.

## Verifiche necessarie prima di rilasciare v0.1

- Installazione su HA 2026.11.x con i tre Shelly reali, ESPHome e le due auto; verifica degli entity_id effettivi.
- `unknown/unavailable`, mancanza/ritardo SOC, due auto contemporaneamente, gap e tempo quiete, idle e restart.
- Verificare nel Recorder che non si scriva a ogni campione di potenza.
- Nessun comando reale, nessun retry di Start/Stop.
- La versione 0.0.13 installata richiede migrazione guidata: non sostituire direttamente senza backup della config entry.
