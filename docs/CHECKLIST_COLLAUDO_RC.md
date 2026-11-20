# Checklist prioritaria RC: parcheggio e nuovo avvio

**Primo collaudo**: non iniziare dal laboratorio con `Controllo reale ON`.
Verificare prima la configurazione grafica, il funzionamento dei tre
Shelly, lo stato BLE, l'assenza di automazioni concorrenti e
che il DPM attivo rimanga ON.

## Test da fare in sequenza (su sessione già prevista)

1. Con cavo scollegato **all'avvio HA**, verificare zero nuovi comandi.
   Attivare eventualmente il laboratorio: JSONL privato sì,
   comandi alla wallbox/auto no.
2. Dopo una sessione reale, a collegamento ancora presente,
   impostare Manuale. Verificare che Johnny NON comandi.
   Scollegare l'auto; dopo 30 s di Shelly EV **sotto 30 W**
   e cavo OFF, verifica di UNA richiesta Start-Stop OFF
   soltanto se il controllo reale era stato esplicitamente
   autorizzato. Il comportamento di `Real` in Manuale va verificato:
   la sessione deve passare in AUTO solo allo scollegamento confermato.
3. Verificare `Charge Enabled OFF` e `DPM limit = 0 A` dalla
   conferma BLE; nessun retry se un report manca.
4. Collegare Fiat/Kia; dopo circa 20 s premere automaticamente
   **solo** il pulsante `Update data` dell'auto riconosciuta,
   oppure entrambi se non riconosciuta. Nessun refresh continuo.
5. Verificare che il nuovo SOC e, se presente, il timestamp
   ultimo aggiornamento siano effettivamente posteriori
   alla richiesta; premere il pulsante **non** prova il successo.
6. Con `Avvio posticipato` abilitato e partenza sufficiente,
   Start-Stop resta OFF fino all'ora consentita. In assenza
   di ritardo, avvio immediato solo dopo riconoscimento e calcoli.
7. Prima dell'avvio: confermare `Charge power = Power set =
   4,0 kW` (oppure valore base esplicitamente impostato),
   solo DOPO chiedere Start-Stop ON.
   Verificare DPM ripristinato al valore positivo
   configurato (es. 4,4 kW).
8. Quando Charging e Shelly EV confermano carica effettiva,
   Johnny può cambiare **soltanto Charge power**, mai Start-Stop.
9. Durante il test di carichi (es. induzione), verificare
   che il DPM fisico gestisca subito i picchi, Johnny
   soltanto dopo le finestre lente.
10. Forzare solo in un ambiente isolato (non sulla ricarica
    attiva) failure di BLE, DPM stale e riavvio HA:
    la RC non deve fare start/stop ciechi; dopo reboot
    controllo reale torna OFF.

**Rollback:** Controllo reale OFF, Manuale, controllare che non
ci siano richieste pendenti. Rimuovere la RC o ripristinare
la beta precedente, riavviare HA e verificare lo stato
DPM fisico dall'ESPHome, evitando `Start-Stop ON` alla cieca.

---

# RC — criteri di collaudo e arresto dei test

**Non installare per caricare l'auto in autonomia senza prima superare questi
controlli.** Il codice contiene chiamate reali a `number.set_value` e
`switch.turn_on/off`; prima della prova devono essere disattivate le
automazioni HA che controllano le stesse entità.

## Preparazione (nessuna scrittura elettrica)

1. Confrontare gli entity_id reali con il Config Flow; non utilizzare
   `sensor` a posto di `number` o `switch`.
2. Confermare che `DPM Active` sia **ON** e che la configurazione del
   DPM non venga mai alterata da EasyWallbox Smart.
3. Verificare sul firmware il significato di `Verified charge power`
   e `Verified DPM` e la frequenza di rinnovo di
   `Limit house power set -DPM-`; non inventare un ACK.
4. Controllare capacità, rendimenti, velocità prudenziale per Fiat/Kia,
   SOC e target con timestamp originali (Kia/Fiat possono aggiornare
   ogni 15 minuti).
5. Verificare in Home Assistant che il laboratorio attivo, con auto
   scollegata, scriva JSONL privati **senza comandi**, e che i due
   sensori diagnostici non pubblichino ogni nuovo watt Shelly.

## Prove in Manuale

- Collegare un'auto in una ricarica già prevista.
- Controllare cavo wallbox ON + esattamente un sensore cavo auto ON.
- Variare una sola volta manualmente Charge power da HA e verificare
  `Power set`, `Command status`, `Charging` e Shelly wallbox.
  Ripetere con DPM presente, nessun distacco.
- Controllare l'ordine reale degli eventi per capire se il readback
  esposto a 0,1 kW è sufficiente a correlare l'ACK.
- In Manuale, spegnimento e riavvio HA non devono provocare comando.

## Prove supervisionate (soltanto dopo consenso specifico)

1. Modalità Automatica e `Controllo reale` attivato a cavo ON;
   verificare che il primo setpoint richiesto sia nei min/max
   ESPHome e che non venga inviato più di una volta.
2. Con auto in carica, simulare aumento casa naturale; Johnny può
   richiedere **solo** una variazione `number.set_value`, mai Start/Stop.
3. Una riduzione diventa `LIMITED` soltanto dopo conferma BLE.
   Il valore sullo slider richiesto non basta.
4. Proseguire fino alla quiete documentata: massimo un ripristino
   diretto dopo 15 minuti, con possibilità di annullarlo se il
   planner richiede priorità (niente due proprietari).
5. Controllare boost solo con margine ≤60 minuti, casa <150 W
   da 15 minuti, e uscita >200 W; isteresi di 75 minuti sul planner.
6. Per avvio posticipato, **non** utilizzare una nuova sessione di
   carica come prova artificiale. Se l'auto comincia già a caricare,
   Johnny non può fermarla con la regola attuale.
7. Se la pausa DPM0 è stata effettivamente inviata da Johnny,
   provare la riconciliazione con l'ACK prima del successivo
   `switch.turn_on`. Non provare Stop/Start alla cieca.
8. Con pausa DPM0 e riavvio HA, Controllo reale deve tornare OFF e
   **non** deve eseguire alcun ripristino automatico.

## Test negativi imprescindibili

- Cavo scollegato, entrambi i sensori OFF, nessuna scrittura,
  laboratorio autonomo.
- Cavi discordanti, sconosciuti o due auto ON: bloccare.
- SOC `unavailable` o più vecchio di 30 minuti: bloccare.
- Shelly in ritardo o potenze negative: bloccare.
- BLE offline, `Telemetry Fresh=OFF`, `Wallbox Fault=ON`,
  `DPM Active=OFF`: bloccare.
- `Charge power` richiesto diverso da `Power set`: bloccare.
- DPM readback vecchio dopo attesa di ore: **non** usare uno
  switch ON come prova. Niente retry.
- Durante una limitazione RC, un cambio di potenza esterno
  deve entrare in riconciliazione, senza oscillazioni fra controller.
- Durante Manuale e Pausa gestione nessun comando automatico.

## Rollback

Portare il controllo reale su OFF, passare a Manuale e controllare
che non ci siano comandi pendenti. Ripristinare la versione 0.2.0b5
del proprio test o la release `main` e riavviare HA. Non forzare
`Start-Stop ON` se il DPM è a zero e la sessione non è compresa:
usare l'interfaccia ESPHome e la procedura manuale verificata.

**Mai cancellare o pubblicare `.storage`, PIN BLE, password, token o
registrazioni della casa.**
