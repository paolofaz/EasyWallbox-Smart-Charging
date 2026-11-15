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
  - type: markdown
    content: |
      Un cap proposto NON equivale a un comando inviato,
      confermato dalla wallbox o verificato dal contatore.
      Le metriche di SOC, energia residua e budget sono negli
      attributi dei sensori e restano stime.
```

## Verifiche necessarie prima di rilasciare v0.1

- Installazione su HA 2026.11.x con i tre Shelly reali, ESPHome e le due auto; verifica degli entity_id effettivi.
- `unknown/unavailable`, mancanza/ritardo SOC, due auto contemporaneamente, gap e tempo quiete, idle e restart.
- Verificare nel Recorder che non si scriva a ogni campione di potenza.
- Nessun comando reale, nessun retry di Start/Stop.
- La versione 0.0.13 installata richiede migrazione guidata: non sostituire direttamente senza backup della config entry.
