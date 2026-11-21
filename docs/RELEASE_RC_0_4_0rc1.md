# EasyWallbox Smart Charging v0.4.0rc1

**Prerelease Home Assistant — controllo elettrico reale non ancora collaudato sul campo.**
Il firmware ESPHome, il DPM fisico e il branch `main` restano invariati.

## Novità concordate

- **Avvio ricarica posticipato** è una richiesta di una sola sessione.
  L'ora `Inizia non prima delle` si riferisce alla prossima occorrenza
  locale, **strettamente futura ed entro 12 ore reali**.
  Esempio 20:00→19:00: la prossima occorrenza è domani alle 19:00,
  23 ore dopo → **rifiuto ON senza Start-Stop OFF** e avviso.
  20:00→01:00: domani alle 01:00, entro 5 ore → accettato.
- Puoi attivarlo **anche con l'auto già in carica**. In Automatico,
  con permessi e telemetrie affidabili, l'integrazione richiede una
  sola pausa DPM 0 A via Start-Stop OFF e verifica BLE + Charging
  OFF + Shelly wallbox <30 W; in assenza di conferma blocca,
  senza nuovi tentativi ciechi.
- L'orario richiesto **non viene anticipato** se il planner teme
  di non raggiungere l'obiettivo entro la partenza. Il sensore
  `Avviso ricarica` indica il problema e un orario stimato
  che avrebbe consentito di rispettare il target, se calcolabile.
- Lo switch Avvio posticipato torna **OFF automaticamente soltanto
  dopo una vera ripresa Charging confermata** oppure allo
  scollegamento del cavo, non semplicemente allo scoccare dell'ora.
- Nuova entità `Auto pronta entro`, compilata dall'orario
  feriale/weekend dell'auto identificata e modificabile per
  la sessione. L'override si azzera allo scollegamento, senza
  cambiare i profili permanenti; viene salvato durante la sessione.
- Altri sensori semantici: veicolo riconosciuto, stabilizzatore
  NORMAL/LIMITED/BOOST, energia AC residua stimata, fine prevista
  arrotondata a 10 minuti, stato e avviso testuale.
  Niente sensori watt/cavo/DPM duplicati; niente countdown al
  secondo o attributi pubblicati a ogni nuovo watt.
- Wallbox normalmente spenta tramite teleruttore: opzionale ma
  consigliato il binary sensor ESPHome `Connection` BLE.
  BLE OFF = **non disponibile**, senza errori definitivi, timer
  aggiuntivi o comandi. All'evento BLE ON la RC rilegge e
  riconcilia. Cavo OFF stabile non diventa stale dopo 2 minuti
  se BLE è confermato online.
- Rimossi dall'interfaccia: Carica subito, Pausa gestione,
  Riprendi gestione, Annulla eccezione, Controllo reale,
  vecchio `datetime` Prossima partenza eccezionale.
  La migrazione rimuove **solo** le voci obsolete appartenenti
  alla Config Entry dell'integrazione.
- **Controllo automatico reale** è ora una scelta esplicita nelle
  **Opzioni → Wallbox**, inizialmente **OFF per le installazioni
  esistenti**. È consentito soltanto con gli altri controllori
  disabilitati; una volta autorizzato può riprendere dopo
  reboot HA soltanto con letture verificabili e senza retry.
- Pausa DPM0 dovuta a posticipo e confermata viene salvata
  insieme ad auto, limite DPM e ora richiesta. Dopo reboot si
  recupera solo se tutti i riscontri elettrici attuali
  corrispondono; pause manuali mai adottate automaticamente.

## Aggiornamento dalla 0.3.0rc4

1. Backup completo di Home Assistant. Non editare `.storage`.
2. Aggiorna alla prerelease `0.4.0rc1` via Marketplace e riavvia.
3. **Non eliminare la Config Entry**: i profili auto, target SOC,
   sensori e impostazioni sono conservati.
4. Apri **Configura → Wallbox** e seleziona il sensor BLE
   `Connection` esposto da ESPHome, se disponibile. Verifica
   i consumi e DPM di riferimento.
5. Prima di abilitare l'opzione **Controllo automatico reale**
   escludi le automazioni concorrenti, in particolare
   il vecchio Stop Fiat se si intende usare il nuovo Stop SOC.
6. Con auto scollegata e wallbox OFF, controlla che lo stato
   sia `Wallbox non disponibile`; dopo accensione/connessione
   controlla la riconciliazione e le nuove entità.
7. Prova inizialmente i comandi soltanto secondo
   `docs/CHECKLIST_COLLAUDO_RC.md`, in modo supervisionato.

**Limitazioni note:** senza una lettura SOC recente o senza storia
Shelly sufficiente, il planner non inventa una durata. Il
posticipo esplicito può comportare un completamento oltre
la scadenza richiesta: l'RC lo segnala ma non anticipa.
Non è inclusa ancora una Lovelace auto-installata; si usano
le entità native nel dispositivo HA.

**Rollback:** disabilita Controllo automatico dalle Opzioni,
controlla fisicamente DPM/Start-Stop sul firmware ESPHome,
ripristina il tag precedente. Non eseguire Start/Stop ciechi.
