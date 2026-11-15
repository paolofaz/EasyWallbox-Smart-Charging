# M4 — studio della soglia dinamica per pressione sul DPM

**Solo laboratorio, NON collegato al coordinatore e NON autorizzato al controllo reale.**

## Contesto e decisioni vincolanti

Il DPM fisico rimane attivo e gestisce i picchi rapidi. Johnny non deve replicare il suo anello di controllo né introdurre comandi BLE frequenti. La potenza elettrica continuativa modellata è **quella impostata e confermata sul DPM**, non il possibile margine di sovraccarico temporaneo del contatore. Il limite EV usato nei calcoli dev'essere quello **confermato** e diverso dalla richiesta HA se questa non ha ancora avuto effetto.

Il codice di produzione/simulazione M4 corrente usa un innesco sulla somma domestica di 1,5 kW. Tale valore non si adatta quando l'utente cambia il limite di carica EV. Questa nota propone un criterio alternativo da verificare, non una nuova funzione già rilasciata.

## Grandezza da osservare

```text
pressione_DPM_kW = max(0, potenza_casa_kw + limite_EV_confermato_kw - limite_DPM_confermato_kw)
```

È un **indicatore teorico** della potenza che il DPM potrebbe dover sottrarre all'auto, non un conteggio di comandi DPM e nemmeno la potenza reale EV. A parità di consumo domestico, se il limite EV passa da 4 kW a 2 kW la pressione diminuisce automaticamente. Non basta però vedere pressione positiva per inviare una nuova scrittura: servono beneficio minimo, persistenza osservata e target SOC raggiungibile.

## Ipotesi di laboratorio da confrontare

- **Margine ampio** (slack del planner sopra 120 minuti): innesco con pressione teorica di almeno 0,6 kW confermata da nuove letture per circa 120 secondi; quiete di circa 10 minuti; tetto energetico conservativo candidato pari al 20% dello slack.
- **Margine intermedio** (45–120 minuti): richiede una pressione maggiore, circa 0,8 kW, confermata per circa 180 secondi; quiete di circa 6 minuti; tetto candidato pari al 10% dello slack.
- **Margine scarso o dati inaffidabili**: nessuna nuova limitazione opzionale. Se il limite virtuale è già attivo, il planner deve preferire la raggiungibilità del target; la futura attuazione richiederà comunque proprietà del comando, riconciliazione e conferma hardware.

Queste soglie sono **varianti sperimentali, non valori approvati**. Il cap candidato resta stabile durante un episodio e viene calcolato con arrotondamento a 0,2 kW, margine antioscillazione e minimo utile pari al limite praticabile. Una variante utilizza il massimo carico osservato negli ultimi tre minuti invece del campione istantaneo: può ridurre il lavoro teorico del DPM ma rischia una riduzione troppo incisiva dopo un picco isolato.

## Criteri di confronto

Con DPM ideale, senza auto reale in carica, misurare separatamente:

1. **Numero di variazioni virtuali di cap** (`reduce`/`restore`): indicatore del futuro costo di scritture, ma non prova usura.
2. **Energia EV aggiuntiva non caricata rispetto a DPM-only**: differenza tra energia controfattuale con solo DPM ed energia con cap virtuale, non semplicemente `limite_originale - cap`.
3. **Minuti teorici di forte modulazione DPM**: proxy della pressione elettrica residua, non osservazione del suo algoritmo interno e non prova delle manovre dei contattori.
4. **Raggiungibilità del target SOC** e banda di slack: nessun cap a target urgente o in assenza di stima credibile.
5. **Qualità e frequenza delle letture**: `unknown` non è zero; un campione vecchio non autorizza una nuova limitazione.

Il test locale ha evidenziato un vero compromesso: una variante può risparmiare energia ma lasciare lavorare più a lungo il DPM, un'altra può limitare la pressione sul DPM sacrificando energia e aggiungendo cambi virtuali. **Nessuna variante è stata dichiarata vincitrice.**

## Limitazioni e passaggi successivi

I replay privati dei consumi restano **fuori da GitHub**. Il test locale ha usato dati domestici forniti in chat, senza creare una sessione di carica reale; non ha potuto osservare PWM, corrente EV, DPM reale né i contattori. Le sette sere precedentemente analizzate non sono state ricalcolate con questa nuova variante, perché i dati grezzi corrispondenti non sono disponibili in questa sessione. I 15 test isolati del candidato puro sono passati localmente, **non sono test CI del repository**.

Prima di modificare `core.py` o `coordinator.py`:
- Ripetere gli esperimenti su tracce rappresentative e su diverse potenze EV; non ottimizzare su una sola serata
- Capire se vale la pena esporre in Config Flow il sensore di limite DPM effettivamente confermato, con fallback conservativo a indisponibile e non a valori inventati
- Verificare che nessuna proposta BLE si sovrapponga a operazioni manuali, a DPM e ad automazioni legacy
- Conservare per ora **solo simulazione** e richiedere autorizzazione esplicita prima di qualsiasi controllo supervisionato

Nessun cambio di firmware, DPM, `main`, release Marketplace o controllo fisico.
