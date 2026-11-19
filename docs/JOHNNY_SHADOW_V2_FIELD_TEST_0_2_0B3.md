# Johnny V2 — laboratorio di confronto su Home Assistant (0.2.0b3)

**Versione sperimentale, NON Marketplace, SOLO SIMULAZIONE.**
Nessun comando alla EasyWallbox o alle auto; firmware, DPM, automazioni
legacy e branch `main` non cambiano.

## Che cosa confronta

La nuova prova affianca **tre scenari virtuali indipendenti**, tutti alimentati
dalle stesse letture Shelly della casa (senza energia EV):
- `wide` e `medium`: algoritmi V1 originali, **senza modifiche**;
- `v2`: usa il riconoscimento dei carichi forti di Ampio e prova in aggiunta
  un cuscinetto moderato e rare correzioni del limite.

È sempre un'**auto sintetica inesauribile** che richiede la potenza massima
ordinaria configurata (di default 4,0 kW). Non conosce SOC, veicolo,
connessione o orario reale di partenza. Il budget è illimitato **solo per
questo laboratorio**. I risultati non sono comandi fisici né garanzie di
ricarica completata.

### Regole V2 candidate (non ancora definitive)

- Carico forte: conferma/trigger e quiete come V1 **Ampio** (2 minuti di
  carico continuo o memoria dei cicli nella finestra da 5 minuti; ripristino
  dopo 15 minuti di quiete).
- Piccola pressione persistente: carico casa 0,5–1,1 kW e pressione
  teorica sulla richiesta EV >=0,1 kW, osservata per **3 minuti** usando
  letture Shelly nuove e consecutive. Cap moderato **max EV −0,4 kW**.
  Ripristino dopo **10 minuti** di carico casa <=0,35 kW; cooldown 10 minuti.
- Se la pressione *rimane* almeno 0,25 kW **anche con il cap forte** per
  5 minuti, V2 può ridurre ancora di **0,4 kW**. Almeno 10 minuti fra
  correzioni e al massimo 2 correzioni per episodio; minimo 1,4 kW.
- Il passaggio da buffer a carico forte sostituisce il cap, senza aggiungere
  un secondo controllore. Non c'è rampa continua verso l'alto: quando
  ritorna la quiete V2 ripristina il baseline virtuale autorizzato.
- Un sensore scaduto/non disponibile **non è zero** e non costituisce
  conferma. La prova non emette alcun comando BLE. Il modello DPM esplicito
  deve corrispondere allo scenario che vogliamo misurare.

Il cuscinetto NON è una protezione contro l'accensione improvvisa del forno:
la sicurezza elettrica resta esclusivamente affidata al DPM fisico.

## Installazione della prova

1. Aprire [Actions — Johnny V2 test package](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/workflows/shadow-test-package.yml).
2. Selezionare il **run riuscito** più recente di `stabilizzatore-m1`,
   verificare che siano superati i test, e scaricare
   `easywallbox-shadow-0.2.0b3`.
3. Effettuare backup della cartella HA
   `/config/custom_components/easywallbox_smart` (versione installata).
4. Sostituirla con `easywallbox_smart/` contenuta nell'artifact.
   **Non installare due versioni dello stesso dominio.**
5. Riavviare Home Assistant. Verificare che l'integrazione risulti
   caricata e mostri `0.2.0b3`.
6. Aprire Impostazioni → Dispositivi e servizi → EasyWallbox Smart Charging →
   **Configura / Opzioni → Potenza EV e laboratorio a tre scenari**.
   Verificare massimo ordinario, riferimento DPM (4,4 kW per confrontare
   i vecchi log; 4,8 kW per il normale limite fisico se desiderato) e
   abilitare il laboratorio.
7. Controllare che appaiano tre sensori: Johnny test — margine ampio,
   Johnny test — margine intermedio e Johnny V2 — laboratorio.
   Negli attributi verificare `shadow_log_status: ok`.

## File della nuova giornata

La cartella HA resta:
`/config/easywallbox_smart_shadow/`

I **nuovi** file saranno:
`shadow_v2_2026-11-19.jsonl`,
`shadow_v2_2026-11-20.jsonl`, ecc.

Ogni riga contiene `wide`, `medium` e `v2` per un confronto sincronizzato,
con `time_local`, `house_window`, origine DPM e indicatore di riavvio.
Il campo `v2.kind` è `normal`, `buffer` o `strong`. Il limite
`v2.cap_kw` e l'azione `adjust` sono **puramente virtuali**.

Il logger comprime le letture in un riepilogo ogni 60 secondi e registra
immediatamente le transizioni significative; nessun polling aggiuntivo.
Max 2 MB per file al giorno, senza cancellazioni automatiche.

**Vecchi log:** conservare almeno un backup dei file
`shadow_2026-11-16.jsonl`–`shadow_2026-11-19.jsonl` prima di
cancellarli da HA. I file `shadow_v2_*` non li sovrascrivono.

## Riavvii e limitazioni

Un riavvio di HA azzera **soltanto gli stati virtuali** del laboratorio.
Il record `virtual_state_reset_on_this_row=true` segnala il reset e
`shadow_run_started_local` lo distingue. La persistenza del limite
**reale** non è ancora implementata: richiederà ownership, conferma
ESPHome, stato elettrico e riconciliazione prima di comandare.

L'attuale replay V2 in HA usa campioni Shelly vivi; i replay offline sui
JSONL aggregati erano approssimazioni. Il campo DPM modello (4,4 o 4,8)
non misura gli interventi del DPM reale.

## Stop, rollback e verifica domani

Disabilitare il laboratorio nelle Opzioni per fermare i nuovi JSONL,
oppure ripristinare la cartella `custom_components` salvata al punto 3
e riavviare HA. DPM e automazioni legacy non sono mai stati toccati.

Condividere i `shadow_v2_*.jsonl` della giornata per misurare
numero di cap, gradini, durata, energia AC virtuale e modulazione
teorica DPM dei tre scenari. Nessun caricamento automatico dei log.
