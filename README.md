# EasyWallbox Smart Charging

**Sviluppo 0.2.0b3 — NON PUBBLICATO — SOLO SIMULAZIONE.** La release Marketplace attuale è **0.1.0** su `main`; le nuove funzioni non sono ancora installabili dal Marketplace.

Custom integration Python per Home Assistant che simula la pianificazione di ricarica e uno stabilizzatore lento della potenza EV. Il DPM fisico della EasyWallbox resta attivo, autonomo e responsabile di picchi e sicurezza elettrica. **La 0.1.0 non invia alcun comando reale alla wallbox o alle automobili.** I pulsanti/selettori sono consigli virtuali, non interruttori elettrici.

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

## Field test v0.2.0b3: confronto Johnny Ampio / Intermedio / V2

Il branch `stabilizzatore-m1` contiene un laboratorio **spento di default**.
**Nella beta 0.2.0b3** è stato aggiunto il terzo scenario *Johnny V2*: usa Ampio come logica di riconoscimento dei carichi forti e sperimenta un cuscinetto di 0,4 kW dopo tre minuti di piccola pressione continua, con possibilità di al massimo due ulteriori riduzioni da 0,4 kW distanziate almeno 10 minuti in caso di pressione forte persistente. I vecchi Ampio e Intermedio restano indipendenti e invariati per confronto. Tutte le decisioni sono **virtuali**. Ora i log giornalieri sono `shadow_v2_YYYY-MM-DD.jsonl`, con tre campi `wide`, `medium`, `v2` sincronizzati; i file storici `shadow_*.jsonl` non vengono sovrascritti. Il V2 *non* salva ancora su disco lo stato dei cap reali (che non esistono in questa beta).


Quando abilitato nelle Opzioni, legge continuamente gli Shelly della casa,
anche senza auto collegata, e simula **due auto inesauribili in parallelo**:
margine ampio e margine intermedio. Usa il massimo EV ordinario
configurabile (default **4,0 kW**) e una soglia DPM confermata positiva;
se DPM=0/indisponibile in pausa utilizza un modello **esplicitamente marcato**
nel log. **Nessun comando reale** e nessun SOC reale usato.

Le Opzioni permettono anche una **potenza iniziale EV** (default 3,6 kW):
è un parametro per una futura sessione automatica, **non una rampa attiva**
nel laboratorio. Johnny esamina tutti i report Shelly in memoria; il laboratorio registra
un riepilogo ogni 60 secondi con min/max/media/numero campioni e subito
ogni transizione significativa in JSONL giornalieri, nella cartella HA privata
`/config/easywallbox_smart_shadow/` (massimo 2 MB/giorno).
Tre sensori aggiuntivi read-only mostrano gli stati wide/medium/V2 e
lo stato del log. Il budget SOC è disattivato **solo** nei due scenari
inesauribili; le altre soglie Johnny sono invariate.

**Installazione manuale del pacchetto di test (NON disponibile dal Marketplace):**
[istruzioni complete, GitHub Actions e rollback](docs/JOHNNY_SHADOW_V2_FIELD_TEST_0_2_0B3.md).
Il pacchetto `easywallbox-shadow-0.2.0b3` viene prodotto dalla CI
del branch di sviluppo. Non modificare la cartella della release 0.1.0
senza farne prima una copia di sicurezza.

## Qualità e limiti

**Verifiche per la 0.1.0 pubblicata:** 99 test offline e con mock HA su Python 3.12/3.13, validazione hassfest e HACS/Marketplace. Le verifiche della nuova 0.2.0b2 si trovano nella CI del branch di sviluppo. **Non ancora collaudato** su una Home Assistant reale: Config Flow, Recorder, selettore, runtime con Shelly/ESPHome/auto e riavvio. Quindi questa è una **prima release di prova in sola simulazione**.

La nuova simulazione Johnny v1 usa la **pressione dinamica sul DPM**, con conferma 2/3 minuti per carichi continui, memoria di 5 minuti per quelli intermittenti e quiete 15/10 minuti nelle fasce ampio/intermedio. Il DPM impostato a **zero** per la pausa non è trattato come limite elettrico e non causa mai un avvio automatico; Johnny richiede di conoscere l'origine della pausa prima di qualsiasi futuro controllo reale. Le vecchie soglie domestiche fisse 1,5/1,0 kW appartengono a un precedente test offline, non al supervisore collegato in Home Assistant. Tutti i parametri restano **tarature sperimentali**, non protezioni elettriche.

Nessuna modifica a firmware ESPHome, DPM e automazioni Fiat esistenti. Non inserire PIN BLE, credenziali, token, cronologie private o cartelle `.storage` nel repository.

**Novità sviluppo 0.2.0b2 (precedente):** il target letto da un'entità HA ha priorità esclusiva quando quella modalità è scelta; se la lettura è `unknown` o `unavailable`, il planner segnala dati insufficienti senza utilizzare un vecchio target fisso. Le configurazioni 0.1.0 restano leggibili e la sorgente è modificabile dalle Opzioni. Il planner usa prima la potenza reale Shelly e, dopo almeno 30 minuti di contatori coerenti, combina potenza corrente e media energia/durata della sessione. In assenza di misure non inventa una media. La selezione dei sensori è modificabile dalle Opzioni e le configurazioni già create dalla 0.1.0 restano leggibili. Non salva uno storico di cinque sessioni. Dettagli in [Stima automatica e consumi universali](docs/STIMA_AUTOMATICA_E_CONSUMI_UNIVERSALI.md).\n\n**Johnny v1:** [Policy implementata, replay e gestione casi limite](docs/JOHNNY_V1_POLICY.md). Se la ricarica termina con telemetria coerente, propone la restituzione del limite virtuale; se cavo, proprietario o stato elettrico sono incerti segnala riconciliazione e non presume ripristini. Se uno Shelly resta inattendibile per 8 minuti dall'ultimo report domestico affidabile, propone di rilasciare il cap opzionale; i timer HA non costituiscono nuove letture. La diagnosi conserva l'ultimo evento virtuale. Il controllo elettrico reale **non è ancora implementato né collaudato**.\n\n**Approfondimenti:** [Note tecniche](NOTE_SVILUPPO.md), [Architettura M1](docs/ARCHITETTURA_M1.md), [Dashboard Lovelace](docs/LOVELACE.md), [Note release 0.1.0](docs/RELEASE_NOTES_0.1.0.md).

In caso di problemi puoi rimuovere l'entry di test da Dispositivi e servizi, disinstallare la custom integration da Marketplace e riavviare HA. Questo non cambia il DPM né le automazioni originali.
