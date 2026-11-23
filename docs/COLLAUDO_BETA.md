# EasyWallbox Smart Charging — checklist prima carica beta 0.9

**Non è una verifica delle protezioni elettriche.** Mantenere DPM attivo.
La fase beta serve a convalidare i dati, l'ownership dei comandi e la gestione
lenta della ricarica con un'auto reale. Evitare prove intenzionali di sovraccarico.

## Preparazione

- [ ] Eseguire backup HA prima dell'aggiornamento e conservare configurazione esistente.
- [ ] Verificare DPM attivo, soglia coerente con l'impianto e valori ESPHome attendibili.
- [ ] Controllare che gli Shelly domestici escludano il ramo EV e che lo Shelly EV sia dedicato.
- [ ] Disabilitare automazioni legacy che inviano comandi concorrenti a Charge power/Start-Stop.
- [ ] Verificare auto, SOC, target e orario partenza previsti.
- [ ] In Opzioni → Diario diagnostico, abilitare il flag; percorso: `/config/easywallbox_smart/decision_logs/`.
- [ ] Dopo aver collegato l'auto, verificare che il diario JSONL contenga eventi di sessione.

## Durante la carica

- [ ] Annotare potenza EV desiderata, limite ESPHome richiesto e confermato, carica effettiva Shelly.
- [ ] Nessun comando dalla sola connessione BLE o da dati non attendibili; nessun retry cieco.
- [ ] Osservare normali carichi domestici intermittenti: il DPM gestisce le variazioni rapide.
- [ ] Misurare eventuale ingresso LIMITED, tempo di permanenza, ritorno NORMAL e motivi.
- [ ] In caso di controllo sospeso, NON assumere che lo slider o il valore storico sia applicato: controllare ESPHome e Shelly.
- [ ] Se possibile, mantenere una sessione separata in Manuale per confronto, senza disattivare il DPM.

## Analisi dopo la carica

- [ ] Unire JSONL e dati Shelly/ESPHome per timestamp.
- [ ] Contare scritture BLE per ora, separando aumenti e riduzioni.
- [ ] Misurare intervalli report Shelly, gap e qualità del margine.
- [ ] Verificare età dell'ultimo aggiornamento SOC e qualità stime.
- [ ] Confrontare energia utile recuperata e rientri in LIMITED entro 15 minuti dopo il ripristino.
- [ ] Se la prima prova è regolare, fare un test supervisionato di riavvio HA **durante LIMITED**, con tempo di partenza non critico.
- [ ] Annotare criticità e decisioni prima di correggere la policy o considerare la stabile 1.0.

## Disattivazione del diario

Dalle Opzioni impostare il flag su OFF. Dopo il ricaricamento non vengono
registrati nuovi eventi. I JSONL già presenti rimangono sul filesystem.
