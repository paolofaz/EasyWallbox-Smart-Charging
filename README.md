# EasyWallbox Smart Charging

Custom integration Python per **Home Assistant** che pianificherà la ricarica di **Fiat 500e** e **Kia EV3**, utilizzando stati ESPHome, SOC e potenze misurate dai tre Shelly EM.

> **Stato: infrastruttura pre-alpha (manifest v0.0.1). Non è ancora la v0.1 di simulazione.** Non stima energia o tempi, non identifica l'auto, non espone sensori calcolati e **non comanda la wallbox o le automobili**. Non usarla come controllore della ricarica.

## Sicurezza e separazione delle responsabilità

- Il firmware ESPHome rimane proprietario della comunicazione BLE.
- Il **DPM della wallbox rimane attivo** e gestisce autonomamente picchi e limiti elettrici; non è sostituito da Home Assistant.
- Questa pre-alpha salva esclusivamente la mappatura delle entità HA, **senza listener, polling, servizi o attuatori**.
- L'automazione Fiat per il limite SOC e quella di riduzione mattutina della potenza **restano attive** fino a una migrazione futura verificata.
- Nessuna credenziale, PIN BLE o file `.storage` va pubblicato.

## Branch e versione

- `main`: stabile, **non modificare senza autorizzazione esplicita**.
- `sviluppo-test`: unico branch per lo sviluppo iniziale.
- `0.0.1`: solo infrastruttura. La **v0.1** sarà una milestone successiva, interamente in **simulazione**.
- Non c'è ancora una release pubblicata né una compatibilità con HA reale certificata.

## Installazione per test in Home Assistant

**Non installare da `main`: contiene solo la licenza iniziale.** Per una prova locale, copiare la directory `custom_components/easywallbox_smart/` dal branch `sviluppo-test` nella cartella di configurazione Home Assistant, mantenendo la struttura. Riavviare Home Assistant se necessario, quindi aggiungere l'integrazione da *Impostazioni → Dispositivi e servizi → Aggiungi integrazione*.

Il requisito indicativo dichiarato per il Marketplace è **Home Assistant 2026.11.0+**; la versione effettivamente installata e l'esito del test sono ancora da verificare. **Non è necessaria alcuna configurazione YAML**.

Il config flow offre tre schermate:
1. wallbox (sensori di stato, connessione e freschezza);
2. Fiat 500e e Kia EV3 (cavo, ricarica, SOC e target);
3. tre Shelly EM (ramo piano terra, primo piano, wallbox).

Tutti i campi sono facoltativi **solo in questa pre-alpha**, per consentire di creare l'entry mentre si raccolgono gli entity_id. Una mappatura incompleta non sarà ritenuta valida per il planner delle prossime milestone. Gli entity_id vengono selezionati nella GUI, non scritti nel codice. Le selezioni potranno essere aggiornate dalle **Opzioni** dell'integrazione. Non sono presenti switch o pulsanti per inviare comandi.

## Verifiche di questa pre-alpha

Controlli offline (non richiedono Home Assistant):

```bash
python -m unittest discover -s tests -v
```

Sono verifiche statiche di sintassi, manifest, traduzioni e assenza di alcune chiamate di comando. **Non equivalgono a un test del config flow eseguito in Home Assistant, né a hassfest/HACS action.** Prima di pubblicare e installare su impianti reali servono test aggiuntivi.

### Rollback

In sviluppo, disabilitare/rimuovere l'integrazione da *Dispositivi e servizi* e rimuovere la directory `custom_components/easywallbox_smart/` copiata manualmente. Nessuna automazione esistente o configurazione ESPHome viene cambiata. Per ripristinare il codice usare un commit precedente del solo branch `sviluppo-test`.

## Roadmap concordata

- **v0.1 — simulazione**: validazione/qualità dati, identificazione auto, energia e tempi, scadenza, raccomandazione spiegabile, sensori, test e **dashboard Lovelace dedicata**.
- **v0.2 — supervisione (solo previa autorizzazione)**: controllore unico e comandi sicuri con conferma.
- **v1.0 — automazione (solo dopo collaudo e consenso)**: gestione completa della sessione, eccezioni, modalità manuale, pausa e Carica subito.

La dashboard Lovelace è **parte obbligatoria della v0.1**, non un accessorio opzionale. La progettazione e le schermate previste sono in [docs/LOVELACE.md](docs/LOVELACE.md). Si partirà dalle card native HA; eventuali card frontend personalizzate andranno motivate e approvate prima di aggiungere codice JavaScript.

Per attività, verifiche e limiti vedi [NOTE_SVILUPPO.md](NOTE_SVILUPPO.md).

## Compatibilità Marketplace

La struttura `custom_components/easywallbox_smart/`, il manifest con `version`, le traduzioni `en.json`/`it.json` e `hacs.json` sono una **predisposizione** per il Marketplace Home Assistant (ex HACS). Non è ancora stata pubblicata una release o richiesta l'inclusione nel catalogo.

## Documentazione tecnica ufficiale

- [Marketplace: pubblicare una custom integration](https://contributors.home-assistant.io/marketplace/guides/integrations/)
- [Config flow](https://developers.home-assistant.io/docs/core/integration/config_flow/)
- [Options flow](https://developers.home-assistant.io/docs/core/integration/options_flow/)
- [Localizzazione custom integration](https://developers.home-assistant.io/docs/internationalization/custom_integration/)

Licenza: MIT.
