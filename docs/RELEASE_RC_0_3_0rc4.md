# EasyWallbox Smart Charging 0.3.0rc4 — dispositivo e Stop SOC opzionale

**Pre-release di sviluppo per Home Assistant**. Non è un collaudo elettrico.
L'autorizzazione **Controllo reale resta OFF dopo installazione/riavvio**.
Nessuna modifica al firmware ESPHome e nessun merge automatico su `main`.

## Correzione della pagina Dispositivi

Le 11 entità di EasyWallbox Smart Charging ora dichiarano tutte il medesimo
dispositivo software: **EasyWallbox Smart Charging**. La scheda Dispositivi
dell'integrazione mostra il controller con le entità associate; gli
`unique_id` esistenti rimangono invariati e non si creano copie.
I due sensori Stato ricarica e Pianificazione ricarica sono diagnostici.
Non abbiamo eliminato alcuna entità: valuteremo insieme cosa è superfluo
dopo una verifica sul tuo Home Assistant.

## Stop SOC per Fiat, opzionale per qualsiasi veicolo

Nelle Opzioni di ogni auto compare:
**«Interrompi la ricarica a target SOC»**, default **OFF**.
Per Kia EV3 (fermata gestita direttamente dal veicolo) lasciarlo OFF.
Per Fiat 500e può essere attivato scegliendo come target l'entità HA
già esistente, anche un `input_number`, oppure un valore fisso.

Con target fisso e Stop abilitato compare un solo slider `number`
**80–100%**, a passi da **5**; se il target proviene già da un'entità,
l'integrazione **non crea un secondo slider**.

Per l'auto con Stop attivo e soltanto mentre ricarica davvero:
lettura SOC e origine temporale devono essere recenti. Avvicinandosi
al limite può richiedere un refresh auto non più spesso di 20 minuti;
quando è presente il timestamp di ultimo aggiornamento, deve
cambiare realmente dopo il pulsante. SOC >= target può autorizzare
**un unico Start-Stop OFF**, nuova eccezione esplicita alla regola
di non cambiare switch durante Charging.

Il controller conferma la fine solo dopo ACK BLE DPM0, Charge Enabled
OFF, Charging OFF e Shelly EV <30 W. Senza tutti i riscontri non
ripete la richiesta, diagnostica il blocco. La ricarica NON riparte
automaticamente nella stessa sessione dopo Stop a target.

## Attenzione alle automazioni esistenti

La tua precedente automazione Fiat 500 che scrive
`switch.wallbox_start_stop` **non viene modificata automaticamente**.
Per il collaudo del nuovo Stop a target, deve essere prima
disattivato il vecchio controllo dello switch. Le notifiche famiglia
e gli avvisi MQTT non sono stati migrati, e possono essere conservati
come funzioni indipendenti una volta collaudata la nuova gestione.

## Aggiornamento

Aggiornare `0.3.0rc3 → 0.3.0rc4` tramite il Marketplace con
*pre-release* abilitate. Riavviare HA, lasciare **Controllo reale OFF**.
La Config Entry e i profili delle auto esistenti vengono conservati;
Stop per target è OFF finché non viene attivato nelle Opzioni.
Aprire la scheda **Dispositivi** dell'integrazione per esaminare i
controlli raggruppati, prima di affrontare la prova elettrica.
Per non creare due proprietari dello stesso dispositivo, non abilitare
il controllo reale mentre l'automazione Fiat legacy può ancora fermare
la ricarica.

Test offline su Python 3.12/3.13, hassfest e HACS sono una
verifica di codice, non sostituiscono prove sul campo.
README e checklist di collaudo nel branch `RC`.
