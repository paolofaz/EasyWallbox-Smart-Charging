# Prova v0.1 in simulazione: compatibilità 0.0.13 e rollback

**Stato al 15/11/2026:** procedura PREPARATA, **NON ESEGUITA** sulla Home Assistant di casa. Nessuna release pubblicata, nessun comando alla wallbox. Una custom integration con dominio `easywallbox_smart` può avere **un solo codice per istanza HA**: non si possono eseguire 0.0.13 e M3/v0.1 una accanto all'altra nella stessa istanza.

## Prima di qualsiasi prova sulla HA di produzione

1. **Non eliminare la configurazione 0.0.13** da Impostazioni → Dispositivi e servizi; non modificare a mano `.storage/core.config_entries`. Il suo schema v3 usa `connected`, `default_target_soc`, `house_power_sources` o `site_total_power`; la M3 usa dati nuovi non convertibili senza una mappatura verificata.
2. Effettua un backup da **Impostazioni → Sistema → Backup** che includa le impostazioni di Home Assistant (cartella di configurazione). Scaricane una copia fuori dalla macchina, controllane la recuperabilità e conserva in modo sicuro l'eventuale chiave di cifratura. I backup e i file `.storage` possono contenere segreti: **non** caricarli in GitHub o in chat.
3. Conserva anche una **copia privata esatta** della directory `custom_components/easywallbox_smart/` realmente installata (non supporre che coincida con un ramo GitHub). Annotane la versione `manifest.json`.
4. Le automazioni Fiat del target e della potenza mattutina, ESPHome e DPM rimangono invariati. Nessuna doppia logica attuativa.

**Fonte backup ufficiale:** https://www.home-assistant.io/common-tasks/general/backups/

## Prova raccomandata: istanza isolata

- Predisporre una **HA di test separata**, con accesso elettrico/BLE/servizi auto **escluso**; non clonare una HA completa con automazioni che potrebbero azionare dispositivi reali. Meglio partire da una configurazione di test vuota e fornire entità fittizie controllate.
- Copiare esclusivamente il codice di `custom_components/easywallbox_smart/` dal branch `stabilizzatore-m1` **sull'istanza di test** (non occorrono codice ESPHome o dati privati).
- Riavviare HA di test. In Impostazioni → Dispositivi e servizi → Aggiungi integrazione, scegliere EasyWallbox Smart Charging.
- Configurare due sensori casa **distinti**, il sensore EV dedicato, i tre segnali osservativi della wallbox e i due limiti letti in sola lettura. Impostare profili Fiat/Kia *solo con valori dichiarati e verificabili*; non inventare id o capacità.
- Verificare i tre sensori simulati e il selettore modalità. Durante un carico fittizio impegnativo il planner può emettere `reduce` o `restore`, ma **non deve esistere nessun servizio verso wallbox/auto**.
- Verificare dati `unknown`/`unavailable`, SOC vecchio, due auto collegate, override Manuale, Pausa, Carica subito, target raggiunto e reboot con cavo collegato (richiede riconciliazione).
- Controllare **Recorder** e log senza esportare campioni privati: non devono comparire nuove entità potenza duplicative né aggiornamenti del riepilogo per ogni singola misura.
- Controllare Setup/Options Flow, il reload e l'unload anche dopo errore. La CI con fake HA e hassfest **non certifica** questi comportamenti sul runtime reale.

## Se per errore si installa il nuovo codice sopra 0.0.13

- Il guard `preflight.inspect()` riconosce la vecchia entry v3 e `async_setup_entry` restituisce un errore esplicativo **senza modificare entry.data, entry.options o versione**. `config_flow` blocca la creazione di una seconda entry sullo stesso dominio.
- **Non correggere il problema cancellando l'entry legacy!** Non eseguire migrazioni a mano su `.storage`. Il mancato setup è intenzionale e reversibile.
- Ripristinare la **directory del codice 0.0.13 copiata realmente dalla propria HA**, riavviare Home Assistant e verificare che entità/automazioni precedenti siano presenti; evitare di usare il branch GitHub come sostituto di una copia della versione realmente installata.
- Se qualche entry o file è stato nel frattempo rimosso/sovrascritto, ripristinare il backup HA con la relativa chiave seguendo la procedura ufficiale; la possibilità di rollback è da **verificare effettivamente**, non assumere.

## Gate da superare PRIMA di autorizzare una release v0.1

- [ ] UI e lifecycle su una vera istanza Home Assistant 2026.11.x separata;
- [ ] modalità sessione, errori e riavvio verificati in laboratorio HA;
- [ ] qualità/freschezza di ESPHome, SOC e Shelly da validare in casa **in sola lettura**;
- [ ] assenza di scritture per campione nel Recorder e nessun servizio device;
- [ ] migrazione da 0.0.13 **guidata ed esplicitamente autorizzata**, con test di rollback realmente completati;
- [ ] test della dashboard Lovelace, prova di gestione errori e verifica HACS su branch predefinito;
- [ ] parametri di planner/stabilizzatore calibrati: i valori numerici del replay restano candidati.

## Perché la nuova configurazione dichiara ancora VERSION = 3

La 0.0.13 installata usa già **schema config entry 3**. La nuova configurazione riconosce il contenuto **per forma**, non interpreta lo stesso numero come compatibilità. In questa fase mantenere VERSION=3 evita di introdurre un'inutile migrazione per le entry v3 e permette al guard di rifiutarle senza toccare i dati. I vecchi schemi v1/v2 non sono stati certificati. In futuro il passaggio a un nuovo numero di schema e il metodo `async_migrate_entry` potranno essere progettati solo dopo una vera migrazione guidata/testata: **non** committare `async_update_entry` ora.

Documento di sviluppo, non istruzioni di sostituzione immediata nella HA di casa.
