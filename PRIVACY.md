# Privacy

🇮🇹 [Italiano](#italiano) · 🇬🇧 [English](#english)

<a id="italiano"></a>

## 🇮🇹 Italiano

Informativa ai sensi del Regolamento (UE) 2016/679 (GDPR). Ultimo aggiornamento: 19 ottobre 2026.

### In breve
didup-calendar-sync è un programma **self-hosted**: lo installa e lo fa girare chi lo usa, sul
proprio server. L'autore del progetto non gestisce alcun servizio, non riceve e non conserva dati,
non usa telemetria, analytics o cookie. Tutti i dati restano nell'installazione di chi usa il
programma e nei servizi che ha scelto di collegare.

### Chi è il titolare del trattamento
Chi installa e usa il programma decide quali dati trattare e dove inviarli, ed è quindi il
titolare del trattamento. Se il programma è usato da un genitore per i dati scolastici dei
propri figli, il trattamento rientra di norma nell'attività a carattere esclusivamente personale
o domestico (art. 2, par. 2, lett. c GDPR). Se invece viene usato per conto di altri (per esempio
da una scuola, un'associazione o un'azienda), chi lo gestisce deve valutare autonomamente gli
obblighi del GDPR (base giuridica, informativa, registro dei trattamenti, eventuale DPIA).

### Quali dati vengono trattati
- **Credenziali Argo** (codice scuola, utente, password) del genitore: usate solo per accedere ad
  Argo didUP Famiglia; stanno nel `.env`, nelle variabili del container o in `data/config.toml`.
- **Dati scolastici degli alunni** letti da Argo: nome, scuola e classe, orario, compiti,
  promemoria, voti, note, assenze, comunicazioni della bacheca e relativi allegati. Si tratta di
  dati di **minori**: vanno trattati con particolare cura.
- **Token Google OAuth** (`data/token.json`), per scrivere su Google Calendar e, se attivato,
  Google Drive.
- **Stato locale** (`data/state.json`): identificativi degli elementi già visti, per non ripetere
  le notifiche, e contatore degli errori.
- **Log e metriche**: il log riporta nomi degli alunni, codici scuola e titoli delle notifiche;
  le metriche Prometheus (`/metrics`) usano il nome dell'alunno come etichetta. Token, password e
  `codMin` non compaiono mai nel log.

### Dove vanno i dati
Solo verso i servizi configurati da chi usa il programma, ciascuno con la propria informativa:
- **Argo Software** (portaleargo.it): sorgente dei dati, con le credenziali del genitore.
- **Google Calendar**: eventi di lezioni, compiti e promemoria, nei calendari indicati.
- **Google Drive** (facoltativo): allegati della bacheca.
- **Nextcloud** (facoltativo): allegati della bacheca, sul server indicato.
- **Home Assistant** e/o **Telegram** (facoltativi): testo delle notifiche (es. voto, materia,
  titolo della comunicazione) e link all'allegato.
- **Uptime Kuma** e **Prometheus** (facoltativi): esito e durata dei giri, contatori.

Google e Telegram possono trattare i dati fuori dallo Spazio Economico Europeo, con le garanzie
previste dalle rispettive condizioni (per esempio clausole contrattuali standard o EU-US Data
Privacy Framework). Chi vuole tenere tutto in Europa o in casa può usare Nextcloud e Home
Assistant self-hosted al posto di Drive e Telegram.

### Dati Google (Google API Services User Data Policy)
Il programma chiede solo gli scope necessari:
- `calendar.events`: creare, aggiornare e rimuovere gli eventi che ha creato lui stesso (marcati
  `argo_sync=1`); gli eventi creati a mano non vengono toccati;
- `drive.file` (solo se si archiviano gli allegati su Drive): accesso ai soli file creati dal
  programma, non al resto del Drive.

I dati ottenuti dalle API Google sono usati solo per queste funzioni, non vengono trasferiti a
terzi, non sono usati per pubblicità e non sono letti da persone. L'uso e il trasferimento di
informazioni ricevute dalle API Google rispettano la
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
compresi i requisiti di Limited Use.

### Conservazione
- Gli eventi passati restano nel calendario come storico, finché non li cancelli.
- Gli allegati restano su Drive o Nextcloud finché non li cancelli; i link pubblici Nextcloud
  possono avere una scadenza (`scadenza_giorni`).
- `state.json` e `token.json` restano in `data/` finché il programma è installato.
- I log seguono la rotazione configurata in Docker o nel sistema.

### Sicurezza
Il container gira come utente non privilegiato, con file system in sola lettura e privilegi
ridotti; `data/` va protetta (`chmod 600` sui file con segreti). Si consiglia di esporre
`/metrics` solo sulla rete interna. Vedi anche [SECURITY.md](SECURITY.md).

### Diritti e revoca
I dati sono sotto il controllo di chi usa il programma, che può in ogni momento:
- revocare l'accesso Google da <https://myaccount.google.com/permissions> e cancellare
  `data/token.json`;
- cancellare gli eventi gestiti, gli allegati archiviati, `data/` e i log;
- disattivare singole funzioni (notifiche, allegati, monitoraggio) nel config.

Per i dati conservati da Argo, Google, Telegram o dagli altri servizi si applicano le loro
informative e ci si rivolge a loro. Per i dati scolastici il titolare resta la scuola.
È sempre possibile proporre reclamo all'autorità di controllo (in Italia il
[Garante per la protezione dei dati personali](https://www.garanteprivacy.it)).

### Contatti
Per domande su questa informativa o sul progetto: issue su
<https://github.com/fabrizionota/didup-calendar-sync> (senza incollare dati personali) oppure
segnalazione privata da **Security → Report a vulnerability**.

---

<a id="english"></a>

## 🇬🇧 English

Privacy notice under Regulation (EU) 2016/679 (GDPR). Last updated: 19 October 2026.

### In short
didup-calendar-sync is **self-hosted** software: whoever uses it installs and runs it on their own
server. The project's author runs no service, receives and stores no data, and uses no telemetry,
analytics or cookies. All data stays in the user's installation and in the services they choose to
connect.

### Who is the controller
Whoever installs and uses the program decides which data is processed and where it goes, and is
therefore the controller. When a parent uses it for their own children's school data, processing
normally falls under the purely personal or household activity exemption (Art. 2(2)(c) GDPR). If
it is used on behalf of others (e.g. by a school, association or company), whoever runs it must
assess their own GDPR obligations (legal basis, privacy notice, records of processing, DPIA if
needed).

### Data processed
- **Argo credentials** (school code, username, password) of the parent: used only to access Argo
  didUP Famiglia; kept in `.env`, the container variables or `data/config.toml`.
- **Pupils' school data** read from Argo: name, school and class, timetable, homework, reminders,
  grades, disciplinary notes, absences, notice board messages and their attachments. This is data
  about **minors** and deserves particular care.
- **Google OAuth token** (`data/token.json`), to write to Google Calendar and, if enabled, Google
  Drive.
- **Local state** (`data/state.json`): IDs of items already seen, so notifications are not
  repeated, and the failure counter.
- **Logs and metrics**: logs show pupils' names, school codes and notification titles; Prometheus
  metrics (`/metrics`) use the pupil's name as a label. Tokens, passwords and `codMin` never appear
  in logs.

### Where data goes
Only to the services configured by the user, each under its own privacy policy:
- **Argo Software** (portaleargo.it): the data source, with the parent's credentials.
- **Google Calendar**: lesson, homework and reminder events, in the configured calendars.
- **Google Drive** (optional): notice board attachments.
- **Nextcloud** (optional): notice board attachments, on the configured server.
- **Home Assistant** and/or **Telegram** (optional): notification text (e.g. grade, subject,
  notice title) and the attachment link.
- **Uptime Kuma** and **Prometheus** (optional): run outcome and duration, counters.

Google and Telegram may process data outside the European Economic Area, under the safeguards in
their terms (e.g. standard contractual clauses or the EU-US Data Privacy Framework). To keep
everything in Europe or at home, use self-hosted Nextcloud and Home Assistant instead of Drive and
Telegram.

### Google data (Google API Services User Data Policy)
The program requests only the scopes it needs:
- `calendar.events`: create, update and remove the events it created itself (tagged
  `argo_sync=1`); events created by hand are left alone;
- `drive.file` (only when attachments are archived on Drive): access only to files created by the
  program, not the rest of Drive.

Data obtained from Google APIs is used only for these functions, is not transferred to third
parties, is not used for advertising and is not read by humans. didup-calendar-sync's use and
transfer of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements.

### Retention
- Past events stay in the calendar as history until you delete them.
- Attachments stay on Drive or Nextcloud until you delete them; Nextcloud public links can expire
  (`scadenza_giorni`).
- `state.json` and `token.json` stay in `data/` while the program is installed.
- Logs follow the rotation configured in Docker or the system.

### Security
The container runs as an unprivileged user, with a read-only file system and reduced privileges;
`data/` must be protected (`chmod 600` on files holding secrets). Exposing `/metrics` only on the
internal network is recommended. See also [SECURITY.md](SECURITY.md).

### Rights and revocation
The data is under the user's control, who can at any time:
- revoke Google access at <https://myaccount.google.com/permissions> and delete `data/token.json`;
- delete the managed events, archived attachments, `data/` and logs;
- turn off individual features (notifications, attachments, monitoring) in the config.

For data held by Argo, Google, Telegram or the other services, their own privacy policies apply and
requests go to them. For school data the school remains the controller. You can always lodge a
complaint with a supervisory authority (in Italy the
[Garante per la protezione dei dati personali](https://www.garanteprivacy.it)).

### Contact
For questions about this notice or the project: an issue on
<https://github.com/fabrizionota/didup-calendar-sync> (without pasting personal data) or a private
report via **Security → Report a vulnerability**.
