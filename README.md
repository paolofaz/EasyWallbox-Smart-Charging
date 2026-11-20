# EasyWallbox Smart Charging

**Sviluppo 0.2.0b5 — NON PUBBLICATO — SOLO SIMULAZIONE.** La release Marketplace attuale è **0.1.0** su `main`; le nuove funzioni non sono ancora installabili dal Marketplace.

Custom integration Python per Home Assistant che simula la pianificazione di ricarica e uno stabilizzatore lento della potenza EV. Il DPM fisico della EasyWallbox modula autonomamente il carico. Le protezioni elettriche appartengono all'impianto. I selettori della 0.1.0 e della beta agiscono soltanto sulle proposte simulate.

<!-- ha-marketplace:exclude-start -->
## Installazione

**Home Assistant 2026.11 o superiore:** apri **Impostazioni → Marketplace → Add from link**, aggiungi il repository:

```text
https://github.com/paolofaz/EasyWallbox-Smart-Charging
```

Installa la versione **0.1.0**, riavvia Home Assistant e apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → EasyWallbox Smart Charging**. Non servono ZIP, HACS separato, Docker, codice ESPHome nuovo o modifiche a `configuration.yaml`.

Il repository non è ancora incluso nel catalogo pubblico, quindi si aggiunge una volta dal link. Su Home Assistant 2026.11 e successivi, il Marketplace sostituisce HACS.
<!-- ha-marketplace:exclude-end -->

## Funzionamento

- **Pianificatore**: legge SOC auto, target, partenza e capacità; propone quando attendere o partire. Gli orari feriali/weekend sono impostabili per auto.
- **Johnny v1 — stabilizzatore**: legge i consumi domestici senza wallbox e stima la pressione sul DPM dai limiti confermati. Fasce **ampio/intermedio/urgente**; conferma 2/3 minuti per carichi continui, più memoria mobile **5 minuti** per accensioni cicliche (almeno due e almeno 2 minuti cumulativi con pressione integrata sufficiente), sempre su letture Shelly nuove. Una sola riduzione virtuale stabile per episodio, ripristino dopo quiete 15/10 minuti o necessità del target, budget conservativo. Il limite minimo EV simulato è 1,4 kW; oltre interviene il DPM. Niente fasce orarie fisse, nessuna rampa di comandi.
- **DPM**: resta sempre attivo e gestisce autonomamente i picchi rapidi. La simulazione non sostituisce alcuna protezione elettrica.
- **Modalità**: Automatica, Manuale, Pausa e Carica subito sono modalità di simulazione. Una Pausa nel selettore NON interrompe la ricarica reale; Carica subito NON la avvia.

## Configurazione

Nel nuovo Config Flow si possono selezionare **uno o più sensori di consumo domestico**, sommati fra loro, e uno Shelly dedicato alla wallbox separato dalla somma. È consigliato selezionare anche il sensore ESPHome **Limit house power set -DPM-**: quando configurato, Johnny usa il limite DPM realmente riportato; se il sensore non è disponibile **non** ripiega sul valore di modello. Se non si configura alcun sensore, utilizza il limite DPM immesso manualmente come sola ipotesi di simulazione (4,4 kW nelle nuove configurazioni). ESPHome espone **Car Connected**, **Charging**, **Telemetry Fresh**, **Charge power** (number in kW), **Power set** (sensore kW) e, per perfezionare la stima, **Session Energy** (kWh) e **Session Duration** (min). I due contatori sono facoltativi, ma si selezionano insieme. Per ogni veicolo servono cavo collegato, SOC attuale, capacità, rendimento e orari di partenza. **Per l'obiettivo SOC scegli una sola modalità:** entità HA (opzione predefinita, ideale per Fiat/Kia già integrate) oppure percentuale fissa; il Config Flow mostra soltanto il campo selezionato. Lo stesso metodo può essere modificato dalle Opzioni. **Non viene richiesta alcuna potenza media da inserire a mano.** Nessun `entity_id` è fisso, quindi non è limitata a Fiat 500e o Kia EV3.

Il Config Flow crea un profilo nuovo: non è prevista la migrazione della vecchia 0.0.13. L'utente ha confermato che la precedente installazione è stata rimossa.

## Entità

Tre sensori: **sessione**, **pianificatore** e **stabilizzatore**, e un selettore **modalità simulata**. Le proposte `reduce`/`restore` non impostano la potenza reale. L'icona è inclusa in `custom_components/easywallbox_smart/brand/icon.png`; traduzioni IT/EN e Options Flow sono presenti.



## Banco prova Auto Ready — 20 novembre (solo offline)

Il banco offline studia l'avvio posticipato. Con auto scollegata e opzione esplicita contempla una proposta di pausa preventiva DPM 0 A. Con auto identificata confronta inizio preferito e ultimo avvio utile. Prima di proporre il ripristino del DPM originario richiede la conferma del limite EV autorizzato per la sessione. Oggi il coordinatore HA usa Johnny V1 per la sessione e offre V2 nel laboratorio con auto virtuale. I due moduli del banco, `start_routine.py` e `control_guard.py`, sono funzioni offline. [Specifica del banco](docs/BANCO_PROVA_AUTO_READY_2026-11-20.md).

**Prossimo passo proposto per Lovelace.** Un riquadro in sola lettura mostrerà fase osservata, proposta simulata, motivo ed eventuale dato mancante. Automatico e Manuale sono le due scelte principali previste. Pausa esplicita e Carica subito conservano il significato per la sessione. Un DPM trovato a zero con origine sconosciuta deve comparire come «da riconciliare». La proposta di armamento e la conferma di `AUTO_READY` sono due eventi distinti. Questa vista è da implementare e collaudare. [Criteri di accettazione e rollback](NOTE_SVILUPPO.md#revisione-johnny-e-prossima-beta-in-sola-lettura).

## M4 in preparazione — controllo supervisionato, ancora disabilitato

Il guard valuta una possibile modifica del limite EV sulla base di sessione, dati ESPHome e Shelly, budget e proprietà del limite. Il passaggio al controllo reale richiede ancora prove sulla provenienza e sull'età di ogni conferma, sulla proprietà esclusiva dei comandi e sul recupero dopo riavvio. Il confronto fra i kW pubblicati da ESPHome è insufficiente per ricostruire con certezza il valore BLE originario in decimi di ampere. [Guard supervisionato](docs/M4_CONTROLLO_SUPERVISIONATO_GUARD.md).

## Field test v0.2.0b5: Johnny V2 unico, modellato sui comandi BLE in ampere

Nel branch `stabilizzatore-m1` esiste un laboratorio **spento di default**
e senza comandi reali alla wallbox o alle auto. La beta `0.2.0b5` esegue
**una sola policy Johnny V2**, senza i due vecchi laboratori live
Ampio/Intermedio e senza confronti fra modelli DPM multipli.

**Riferimento prova**: DPM virtuale **4,4 kW** → `191` decimi di
ampere BLE (**19,1 A**); massimo EV virtuale da configurare nelle
Opzioni a **4,2 kW** → `183` decimi di ampere (**18,3 A**).
Le equivalenze seguono esattamente la conversione ESPHome
`int(kW/0.23*10+0.5)`. **Non** sono 4.400 W / 4.200 W elettrici fissi.
Il limite reale della wallbox può differire: non viene modificato
automaticamente e la sua fonte viene distinta nel log.

Lo Shelly EM misura **watt attivi** usando la tensione reale;
`W/230 V` usato per la casa in Johnny è esplicitamente soltanto una
**corrente equivalente approssimativa**, non la misura del sensore
fisico DPM e non una garanzia sul prelievo del contatore. DPM e protezioni
fisiche mantengono la responsabilità dei picchi.

**Soglie V2 sperimentali**: carico moderato della casa 0,45–1,10 kW
con pressione equivalente almeno 0,10 kW per 3 minuti →
un cuscinetto EV di 0,4 kW; ripristino dopo 10 minuti con
pressione originaria <=0,18 kW, poi cooldown 10 minuti.
Carico forte: stessa conferma Ampio di 2 minuti su pressione
>=0,6 kW, più memoria 5 minuti dei cicli intermittenti, con
rientro dopo 15 minuti di quiete. Massimo due correzioni da
0,4 kW, separate da almeno 10 minuti, soltanto in presenza di
pressione >=0,25 kW per almeno 5 minuti anche con cap attivo.
Non inseguire i picchi, non fare polling BLE aggiuntivo.

Il laboratorio registra `shadow_v2_amps_YYYY-MM-DD.jsonl` nella cartella
HA privata `/config/easywallbox_smart_shadow/`: un riepilogo circa
ogni 60 secondi e gli eventi importanti, max 2 MB/giorno.
Riporta correnti nominali dei comandi, proxy della corrente
domestica, origine DPM e stato virtuale. I file dei vecchi esperimenti
`shadow_*` e `shadow_v2_*` non vengono sovrascritti.
Le sessioni virtuali sono infinite e non usano un budget SOC reale:
la connessione con pianificatore, stato manuale, ownership e conferma
BLE sarà un passaggio futuro supervisionato e autorizzato separatamente.

**Pacchetto manuale, non Marketplace:** [guida all'installazione,
verifiche e rollback](docs/JOHNNY_V2_AMPERE_FIELD_TEST_0_2_0B5.md).
GitHub Actions genera l'artifact `easywallbox-shadow-0.2.0b5`.
Il branch `main` e la release Marketplace `0.1.0` restano invariati.

## Qualità e limiti

Sul commit di codice `4071863` sono passati 292 test offline, inclusi 25 test di avvio e 15 del guard. Tutti e quattro i workflow GitHub sono riusciti. L'estratto esteso della 0.2.0b5 contiene due episodi forti con ripristino diretto, entrambi con auto virtuale. Le misure disponibili lasciano aperti l'effetto sulla ricarica effettiva e il margine SOC alla partenza. Le soglie di 2 minuti per il carico forte e 15 minuti per il ripristino restano i riferimenti della simulazione. [Revisione di codice verificata](https://github.com/paolofaz/EasyWallbox-Smart-Charging/commit/4071863357aa01fae0520b952c88a1e87862c510).

La nuova simulazione Johnny v1 usa la **pressione dinamica sul DPM**, con conferma 2/3 minuti per carichi continui, memoria di 5 minuti per quelli intermittenti e quiete 15/10 minuti nelle fasce ampio/intermedio. Il DPM impostato a **zero** per la pausa non è trattato come limite elettrico e non causa mai un avvio automatico; Johnny richiede di conoscere l'origine della pausa prima di qualsiasi futuro controllo reale. Le vecchie soglie domestiche fisse 1,5/1,0 kW appartengono a un precedente test offline, non al supervisore collegato in Home Assistant. Tutti i parametri restano **tarature sperimentali**, non protezioni elettriche.

Nessuna modifica a firmware ESPHome, DPM e automazioni Fiat esistenti. Non inserire PIN BLE, credenziali, token, cronologie private o cartelle `.storage` nel repository.

**Novità sviluppo 0.2.0b2 (precedente):** il target letto da un'entità HA ha priorità esclusiva quando quella modalità è scelta; se la lettura è `unknown` o `unavailable`, il planner segnala dati insufficienti senza utilizzare un vecchio target fisso. Le configurazioni 0.1.0 restano leggibili e la sorgente è modificabile dalle Opzioni. Il planner usa prima la potenza reale Shelly e, dopo almeno 30 minuti di contatori coerenti, combina potenza corrente e media energia/durata della sessione. In assenza di misure non inventa una media. La selezione dei sensori è modificabile dalle Opzioni e le configurazioni già create dalla 0.1.0 restano leggibili. Non salva uno storico di cinque sessioni. Dettagli in [Stima automatica e consumi universali](docs/STIMA_AUTOMATICA_E_CONSUMI_UNIVERSALI.md).\n\n**Johnny v1:** [Policy implementata, replay e gestione casi limite](docs/JOHNNY_V1_POLICY.md). Se la ricarica termina con telemetria coerente, propone la restituzione del limite virtuale; se cavo, proprietario o stato elettrico sono incerti segnala riconciliazione e non presume ripristini. Se uno Shelly resta inattendibile per 8 minuti dall'ultimo report domestico affidabile, propone di rilasciare il cap opzionale; i timer HA non costituiscono nuove letture. La diagnosi conserva l'ultimo evento virtuale. Il controllo elettrico reale **non è ancora implementato né collaudato**.\n\n**Approfondimenti:** [Note tecniche](NOTE_SVILUPPO.md), [Architettura M1](docs/ARCHITETTURA_M1.md), [Dashboard Lovelace](docs/LOVELACE.md), [Note release 0.1.0](docs/RELEASE_NOTES_0.1.0.md).

In caso di problemi puoi rimuovere l'entry di test da Dispositivi e servizi, disinstallare la custom integration da Marketplace e riavviare HA. Questo non cambia il DPM né le automazioni originali.
