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
- Le versioni di prova `0.x` vengono pubblicate come **pre-release** dal branch `sviluppo-test`; il workflow rilascia una versione solo se il tag non esiste già. Nessuna compatibilità con HA reale è ancora certificata.

## Installazione tramite Marketplace (pre-release)

Dopo che la GitHub Action di pubblicazione ha confermato la release `0.0.1`:

1. In Home Assistant 2026.11+ aprire **Impostazioni → Marketplace → Aggiungi da link**.
2. Inserire `https://github.com/paolofaz/EasyWallbox-Smart-Charging`. La registrazione di repository personalizzati richiede l'autorizzazione GitHub in sola lettura.
3. Abilitare la voce **Pre-release** del repository: in **Impostazioni → Dispositivi e servizi → Marketplace**, trovare il dispositivo del repository, abilitare l'entità disabilitata **Pre-release** e accendere lo switch. Se necessario, scegliere manualmente la versione `0.0.1` dalle versioni disponibili.
4. Installare la release `0.0.1`, **non il commit di `main`**. Da **Dispositivi e servizi**, aggiungere EasyWallbox Smart Charging e verificare le tre schermate di configurazione.

> **Attenzione:** `main` contiene soltanto `LICENSE`. La pre-release punta all'esatto commit di `sviluppo-test`. Se il Marketplace non permette di aggiungere il repository o la versione `0.0.1` non compare, **non installare la versione di default** e segnalarlo per diagnosi.

**Installazione manuale alternativa, solo in caso di problemi con Marketplace:** scaricare l'archivio della pre-release `0.0.1` da GitHub e copiare `custom_components/easywallbox_smart/` nella directory di configurazione HA. Per questa prima milestone non cambia alcuna automazione.

<!-- ha-marketplace:exclude-start -->
Link alle [pre-release GitHub](https://github.com/paolofaz/EasyWallbox-Smart-Charging/releases).
<!-- ha-marketplace:exclude-end -->

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

## Processo di release di test

Ogni nuova versione pubblicabile richiede **un cambio esplicito** del campo `version` in `custom_components/easywallbox_smart/manifest.json` e la creazione di `docs/releases/<versione>.md`. Un workflow GitHub Actions sul branch `sviluppo-test` esegue i test statici, rifiuta versioni non `0.x` o tag preesistenti privi di release e crea una **GitHub pre-release** dal commit corrente. Non pubblica su `main`, non fa merge, non crea PR. Non creare una release di un commit non testato.

Le vecchie pre-release verranno riesaminate **dopo il rilascio 1.0**, conservando le versioni necessarie per rollback e migrazione; cancellazioni non automatiche.

## Compatibilità Marketplace

La struttura `custom_components/easywallbox_smart/`, il manifest con `version`, le traduzioni `en.json`/`it.json` e `hacs.json` sono una **predisposizione** per il Marketplace Home Assistant (ex HACS). Non è ancora stata pubblicata una release o richiesta l'inclusione nel catalogo.

## Documentazione tecnica ufficiale

- [Marketplace: pubblicare una custom integration](https://contributors.home-assistant.io/marketplace/guides/integrations/)
- [Config flow](https://developers.home-assistant.io/docs/core/integration/config_flow/)
- [Options flow](https://developers.home-assistant.io/docs/core/integration/options_flow/)
- [Localizzazione custom integration](https://developers.home-assistant.io/docs/internationalization/custom_integration/)

Licenza: MIT.
