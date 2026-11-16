# Johnny — prova sul campo a due scenari (0.2.0b2)

**Release di sviluppo, NON pubblicata sul Marketplace. SOLO SIMULAZIONE.**
Il test non invia comandi a wallbox, ESPHome o automobili e non modifica il DPM.
Le automazioni precedenti restano operative senza concorrenza.

## Cosa fa

Quando attivato nelle Opzioni, il laboratorio crea **due Johnny virtuali**:
`shadow_wide` (margine ampio) e `shadow_medium` (intermedio).
Immaginano una stessa auto che chiede continuamente la **potenza massima
impostata** (default 4,0 kW) anche se il cavo fisico è scollegato.
Leggono esclusivamente i sensori Shelly della casa configurati
(escludendo il contatore wallbox). I due algoritmi sono indipendenti:
condividono i campioni reali, non gli stati, i timer o le decisioni.

Usano la Johnny policy corrente: pressione sul DPM, carichi continui
2/3 minuti, finestra mobile 5 minuti per carichi intermittenti, ripristino
15/10 minuti e cooldown 10 minuti. Sono sempre in fascia wide/medium.
**Solo in questo laboratorio è disabilitato il budget energetico**:
altrimenti l'auto inesauribile esaurirebbe presto il budget e smetterebbe
di produrre decisioni utili per il confronto. Non si prevede né calcola
il SOC effettivo dell'auto, il suo target o l'ora di partenza.

La **potenza iniziale** (default 3,6 kW) viene memorizzata per la futura
gestione delle sessioni, ma **non** esiste oggi una rampa automatica 3,6→4,0:
il laboratorio continuo assume già il **massimo ordinario** come EV
virtuale (default 4,0 kW). Entrambi sono modificabili nelle Opzioni.
Sono passi di 0,2 kW, gamma 1,4–6,0, iniziale <= massimo.

### Limite DPM quando la wallbox è in pausa

Se il sensore DPM riporta un valore positivo e attendibile, la
simulazione utilizza quello: ad esempio 4,4 o 4,8 kW. Quando il DPM
diventa **0** per effetto dello Start-Stop, lo scenario virtuale
continua usando **l'ultimo valore positivo visto in questa esecuzione**,
se presente, oppure il **modello DPM esplicitamente configurato**
nell'integrazione. Nel JSONL il campo `dpm_model_source` chiarisce
se la soglia era reale, ricordata o ipotetica. Il DPM fisico a zero
**non provoca alcuno Start**, e la prova non pretende di sapere chi
abbia messo in pausa la wallbox.

## Installazione del pacchetto TEST (non Marketplace)

1. Aprire le [GitHub Actions del pacchetto test](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/workflows/shadow-test-package.yml),
   scegliere l'ultimo run riuscito sul branch `stabilizzatore-m1`.
2. Scaricare l'artifact **`easywallbox-shadow-0.2.0b2`**. Lo ZIP
   scaricato contiene la cartella `easywallbox_smart/` completa.
3. In Home Assistant, fare una copia di sicurezza della precedente
   cartella `/config/custom_components/easywallbox_smart`
   (e delle Opzioni se necessario).
4. Sostituire quella cartella con `easywallbox_smart/` del pacchetto
   (non installare due versioni dello stesso dominio).
5. Riavviare Home Assistant e verificare che l'integrazione esistente
   `EasyWallbox Smart Charging` carichi correttamente. Il nuovo test
   **è spento per default**.
6. In **Impostazioni → Dispositivi e servizi → EasyWallbox Smart Charging →
   Configura / Opzioni → Potenza EV e laboratorio a due scenari** impostare
   potenza iniziale, massimo ordinario e abilitare **Laboratorio virtuale**.
   Il salvataggio delle Opzioni ricarica l'integrazione.

Non serve modificare il firmware ESPHome, il DPM o `configuration.yaml`.
I due nuovi sensori `Johnny test — margine ampio/intermedio` compaiono
soltanto con il laboratorio abilitato.

## Dove trovare i file del test

Una cartella privata nella configurazione HA:

`/config/easywallbox_smart_shadow/`

Un file JSONL (JSON Lines, un oggetto per riga) per giorno locale:

`shadow_2026-11-16.jsonl`, `shadow_2026-11-17.jsonl`, ecc.

Esempio illustrativo, NON una misura reale:

```json
{"time_local":"2026-11-16T20:00:00+01:00","model":"continuous_two_band_no_real_vehicle","session_budget":"disabled_only_for_infinite_ev_lab","house_kw":1.8,"house_data_quality":"ok","dpm_observed_kw":0,"dpm_model_kw":4.8,"dpm_model_source":"last_positive_confirmed_this_run","ev_baseline_kw":4.0,"wide":{"action":"reduce","reason":"dynamic_stable_episode_cap","state":"LIMITED","cap_kw":2.2,"last_event":"dynamic_stable_episode_cap"},"medium":{"action":"hold","reason":"accumulating_load_evidence","state":"NORMAL","cap_kw":4.0,"last_event":null}}
```

Il log registra ogni nuovo campione domestico attendibile e ogni cambio
di decisione. Non esegue polling aggiuntivo: usa gli eventi degli Shelly
e i timer necessari alla policy. Un report ripetuto con lo stesso timestamp
**non** è una nuova conferma. Un sensore `unknown`, `unavailable` o
vecchio non viene interpretato come zero. Il log comprende house kW,
origine/valore DPM del modello, limite e motivo di ciascun Johnny;
**non registra** SOC reale, identità dei veicoli o credenziali.

I file giornalieri sono limitati a **2 MB ciascuno**, senza cancellazione
automatica. Se il disco non è scrivibile o il file raggiunge il limite,
i sensori mostrano `shadow_log_status=error_OSError` (o altro errore),
e la prova non deve essere considerata registrata correttamente.
I log **non vengono caricati su GitHub**. Dopo alcuni giorni, si possono
condividere qui solo i file JSONL per esaminare numero di riduzioni,
ripristini, durata, frequenza e carichi intermittenti.

### Riavvio Home Assistant

Lo stato della simulazione è **solo in RAM**: un riavvio riparte
con due Johnny non limitati, e i nuovi record vengono accodati al file
del giorno. Il campo `shadow_run_started_local` identifica ogni esecuzione
del processo, `virtual_state_reset_on_this_row=true` marca la prima
valutazione della nuova esecuzione, e `house_report_local` indica il
timestamp del campione domestico utilizzato. Il confronto dei cambi
attraverso un riavvio non rappresenta una singola sessione continua.
Il logger non pretende di ripristinare il precedente limite virtuale.

### Disattivazione e ritorno alla versione stabile

Disabilitare il laboratorio dalla stessa voce delle Opzioni: la lettura
continuativa e il logging terminano dopo il reload. I file già creati
restano per analisi. Per tornare integralmente alla versione stabile,
ripristinare la cartella di backup della `0.1.0` o reinstallarla
dal Marketplace, quindi riavviare HA. `main` e la release pubblica
`0.1.0` non sono stati modificati.

**Prima di abilitare comandi reali** servono ancora la separazione
proprietario Manuale/Automatico, la riconciliazione DPM=0 e il collaudo
di Start/Stop; nessuno di questi è incluso nel laboratorio.
