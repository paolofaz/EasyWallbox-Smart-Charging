# EasyWallbox Smart Charging

Custom integration Python per **Home Assistant** che pianificherà la ricarica di **Fiat 500e** e **Kia EV3**, utilizzando stati ESPHome, SOC e potenze misurate dai tre Shelly EM.

> **Stato: infrastruttura pre-alpha (manifest v0.0.3). Non è ancora la v0.1 di simulazione.** Non stima energia o tempi, non identifica l'auto, non espone sensori calcolati e **non comanda la wallbox o le automobili**. Non usarla come controllore della ricarica.

## Sicurezza e separazione delle responsabilità

- Il firmware ESPHome rimane proprietario della comunicazione BLE.
- Il **DPM della wallbox rimane sempre attivo** e gestisce autonomamente picchi e limiti elettrici; **mai disattivarlo**. Lo **switch di pausa ricarica** è lo Start-Stop ESPHome: quando usato nelle future fasi di controllo, richiede una pausa impostando il **limite DPM a 0 A**, senza spegnere il DPM. Lo stato dello switch da solo non dimostra che l'erogazione elettrica si sia arrestata.
- Questa pre-alpha salva esclusivamente la mappatura delle entità HA, **senza listener, polling, servizi o attuatori**.
- L'automazione Fiat per il limite SOC e quella di riduzione mattutina della potenza **restano attive** fino a una migrazione futura verificata.
- Nessuna credenziale, PIN BLE o file `.storage` va pubblicato.

## Branch e versione

- `main`: stabile, **non modificare senza autorizzazione esplicita**.
- `sviluppo-test`: unico branch per lo sviluppo iniziale.
- `0.0.3`: Config Flow con profili veicolo dinamici e obiettivo SOC abituale. La **v0.1** sarà una milestone successiva, interamente in **simulazione**.
- Le versioni di prova `0.x` vengono pubblicate come **release GitHub normali**, ma sono **software sperimentale e non stabile**. I tag puntano ai commit verificati di `sviluppo-test`, senza modificare `main`. Nessuna compatibilità con HA reale è ancora certificata.

## Installazione tramite Marketplace (release di prova)

Dopo che la GitHub Action di pubblicazione ha confermato la release `0.0.3`:

1. In Home Assistant 2026.11+ aprire **Impostazioni → Marketplace → Aggiungi da link**.
2. Inserire `https://github.com/paolofaz/EasyWallbox-Smart-Charging`. La registrazione di repository personalizzati richiede l'autorizzazione GitHub in sola lettura.
3. Selezionare la **release normale** `0.0.1` quando viene proposta. Non occorre abilitare lo switch **Pre-release**.
4. Installare la release `0.0.3`, **non il commit di `main`**. Da **Dispositivi e servizi**, aggiungere EasyWallbox Smart Charging e verificare le tre schermate di configurazione.

> **Attenzione:** `main` contiene soltanto `LICENSE`. La release punta all'esatto commit di `sviluppo-test`. **Il branch predefinito `main` non contiene ancora `hacs.json` né l'integrazione: il Marketplace potrebbe quindi non riuscire a riconoscere il repository durante l'aggiunta da link.** Se il repository non viene accettato, riportare l'errore e non installare il fallback di `main`.

**Installazione manuale alternativa, solo in caso di problemi con Marketplace:** scaricare l'archivio della release `0.0.3` da GitHub e copiare `custom_components/easywallbox_smart/` nella directory di configurazione HA. Per questa prima milestone non cambia alcuna automazione.

<!-- ha-marketplace:exclude-start -->
Link alle [release GitHub](https://github.com/paolofaz/EasyWallbox-Smart-Charging/releases).
<!-- ha-marketplace:exclude-end -->

Il requisito indicativo dichiarato per il Marketplace è **Home Assistant 2026.11.0+**; la versione effettivamente installata e l'esito del test sono ancora da verificare. **Non è necessaria alcuna configurazione YAML**.

Il Config Flow prevede: (1) sensori wallbox, (2) **uno o più veicoli configurabili**, (3) tre Shelly EM. A ogni veicolo si assegna **nome, sensore SOC, sensore cavo collegato, eventuale sensore ricarica, capacità utilizzabile e obiettivo SOC abituale**. Non richiede un sensore del limite impostato nell'auto. Dopo ogni veicolo, la procedura chiede se aggiungerne un altro.

Le Opzioni permettono di aggiungere, modificare o rimuovere profili, preservando i loro identificatori stabili; per salvare premere **Salva modifiche**. La schermata di configurazione **non invia comandi**.

**Migrazione 0.0.1 → 0.0.3:** se avevi già completato la configurazione vecchia, occorre inserire almeno un nuovo profilo nelle Opzioni; i valori batteria sconosciuti **non vengono inventati**. Se invece ti eri fermato prima della fine, configura da zero con il nuovo flusso.

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

**Decisione SOC (aggiornamento 12/11/2026):** ogni veicolo ha un obiettivo **abituale** configurabile nelle Opzioni. La dashboard v0.1 mostrerà un solo obiettivo effettivo, eventualmente modificabile **per la sessione corrente**; alla sessione successiva tornerà all'abituale. **Non esiste «Escludi obiettivo».** Se il target HA è inferiore a 100%, al suo raggiungimento la logica futura **potrà valutare** una pausa attraverso lo **switch di pausa ricarica** (ESPHome Start-Stop), soltanto dopo verifica delle condizioni e autorizzazione delle funzionalità attuative. Se il target è **100%**, il planner stima energia e tempo fino al 100%, ma **non aziona lo switch di pausa ricarica per SOC**, anche se l'auto dichiara 100% e continua a gestire le celle. Non riattiva nemmeno una sessione fermata manualmente. Il limite interno dell'auto non viene letto o modificato. In v0.1 **nessun comando reale**; la logica della sessione e la dashboard sono ancora da implementare.

La dashboard Lovelace è **parte obbligatoria della v0.1**, non un accessorio opzionale. La progettazione e le schermate previste sono in [docs/LOVELACE.md](docs/LOVELACE.md). Si partirà dalle card native HA; eventuali card frontend personalizzate andranno motivate e approvate prima di aggiungere codice JavaScript.

Per attività, verifiche e limiti vedi [NOTE_SVILUPPO.md](NOTE_SVILUPPO.md).

## Processo di release di test

Ogni nuova versione pubblicabile richiede **un cambio esplicito** del campo `version` in `custom_components/easywallbox_smart/manifest.json` e la creazione di `docs/releases/<versione>.md`. Un workflow GitHub Actions sul branch `sviluppo-test` esegue i test statici, rifiuta versioni non `0.x` o tag preesistenti privi di release, e crea una **GitHub release normale** dal commit corrente. Per la release esistente `0.0.1` aggiorna soltanto la classificazione senza alterare il tag. Non pubblica su `main`, non fa merge, non crea PR. Non creare una release di un commit non testato.

Le vecchie release `0.x` verranno riesaminate **dopo il rilascio 1.0**, conservando le versioni necessarie per rollback e migrazione; cancellazioni non automatiche.

## Compatibilità Marketplace

La struttura `custom_components/easywallbox_smart/`, il manifest con `version`, le traduzioni `en.json`/`it.json` e `hacs.json` sono una **predisposizione** per il Marketplace Home Assistant (ex HACS). Non è ancora stata pubblicata una release o richiesta l'inclusione nel catalogo.

## Documentazione tecnica ufficiale

- [Marketplace: pubblicare una custom integration](https://contributors.home-assistant.io/marketplace/guides/integrations/)
- [Config flow](https://developers.home-assistant.io/docs/core/integration/config_flow/)
- [Options flow](https://developers.home-assistant.io/docs/core/integration/options_flow/)
- [Localizzazione custom integration](https://developers.home-assistant.io/docs/internationalization/custom_integration/)

Licenza: MIT.
