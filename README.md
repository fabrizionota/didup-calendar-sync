# didup-calendar-sync

🇬🇧 English · 🇮🇹 [Italiano](README.it.md)

Syncs the **Argo didUP Famiglia** school register (the Italian electronic register used by many
schools) with **Google Calendar**, one calendar per child, and sends new items as **Home Assistant**
and/or **Telegram** notifications. Works with several children and several schools: each pupil has
its own Argo account.

| From Argo | In Google Calendar / notifications |
| --- | --- |
| Timetable (next N days) | Lesson events: consecutive hours of the same subject merged, co-taught subjects in the same event. Title with the Argo abbreviation (`Matem. con inform.`), full name in the description |
| Homework | In the description of that subject's **lesson** on the due date (title marked ✏️), with assignment date and teacher. If there is no such lesson that day: **all-day event** `📚 Subject: text` |
| Reminders / tests (promemoria) | Timed events; all-day when Argo gives no time (`00:00`) |
| Notice board items requiring sign-up (`dataScadAdesione`) | All-day deadline event. `dataScadenza` is just the end of the notice's publication and is ignored |
| Notice board attachments (optional) | PDFs archived on **Google Drive** or **Nextcloud** in `Scuola/<pupil>/<year>/<MM - Month>/`; the link opens the file from the notification and from the deadline event |
| Grades, notice board, disciplinary notes, reminders (+ optional absences, homework) | Home Assistant and/or Telegram notifications, only for new items |

> **Unofficial project**, not affiliated with or endorsed by Argo Software. It uses undocumented APIs
> of the Argo didUP Famiglia app, which may change without notice; everyone uses it with their own
> credentials and at their own risk. [MIT](LICENSE) licence.

## Layout
```
README.md / README.it.md   this documentation (English / Italian)
CHANGELOG.md / .it.md      changes, by date
didup_calendar_sync.py     single script (Argo → snapshot → Google Calendar + notifications)
config.example.toml        configuration template (the real one lives in data/config.toml)
.env.example               secrets template (Argo passwords, notification tokens)
Dockerfile                 image; the "test" stage runs the unit tests in CI
tests/                     offline tests, no account needed
pocs/                      exploratory scripts to check each integration (see pocs/README.md)
deploy/compose.yml         Docker Compose install (or Portainer stack)
.github/workflows/ci.yml   CI: tests, multi-arch image on GHCR
LICENSE, SECURITY.md       MIT licence, security reports
```
`data/`, `.env`, `pocs/out/` are git-ignored: they hold credentials and the children's data.

Configuration keys and log messages are in Italian (`alunni` = pupils, `orario` = timetable,
`compiti` = homework, `notifiche` = notifications, `fasce` = time slots).

## Configuration

### Pupils and accounts
There is no main account: each `[[alunni]]` block has `codice_scuola` (school code), `username`,
`password_env` (name of the environment variable holding the password), `profilo` (index within that
account, default 0) and `calendar_id`. Pupils sharing an account (school + username) share a single
login; if one account fails, the others are still synced. Profile indexes are shown by
`uv run pocs/01_argo_login.py`.

The global sections `[orario]`, `[compiti]`, `[colori_materie]`, `[notifiche] tipi` apply to everyone;
each pupil can override them with `[alunni.orario]` / `[alunni.orario.fasce]`, `[alunni.compiti]`,
`[alunni.colori_materie]`, `notifiche = [...]`, `materie_ignorate = [...]` (subjects to skip,
e.g. `["SOSTEGNO"]`).

### Time slots
Argo usually **does not provide lesson times** (empty `ora` field), only the hour number: without
`[orario.fasce]` (global or per pupil) no lessons are created and the log says `N ore senza orario`.
Take the slots from the school timetable (school circular or website):
```toml
[alunni.orario.fasce]
1 = "08:00-09:00"
2 = "09:00-10:00"
```

### Secrets
Argo passwords (one variable per `password_env`), `HA_TOKEN` (Home Assistant long-lived token),
`TELEGRAM_BOT_TOKEN`, and for attachments on Nextcloud `NEXTCLOUD_APP_PASSWORD` (plus the optional
`NEXTCLOUD_URL` and `NEXTCLOUD_USER`): in `.env` for local use (see `.env.example`), in the stack's
*Environment variables* in Portainer.

### Notifications
What gets notified is set by `[notifiche] tipi` (or `notifiche = [...]` on a single pupil). Values:
`voti` (grades), `bacheca` (notice board), `note` (disciplinary notes), `promemoria` (reminders),
`assenze` (absences/late entries), `compiti` (homework). Default:
`["voti", "bacheca", "note", "promemoria"]`: homework is already in the calendar, so it is not
notified unless you add it.

`[notifiche.homeassistant]`: `url` (the internal IP is fine, e.g. `http://192.168.1.x:8123`) and
`service`, the phone's notify service, e.g. `mobile_app_<phone>` (a `notify.` prefix is accepted).
Check with `uv run pocs/07_notify.py`, which lists the available services if the name is wrong.

Notice board notifications whose attachment is archived carry its link: tapping the notification
opens the file in Drive or Nextcloud (not Home Assistant); long-press shows an "Apri allegato" button.

### Attachments (Google Drive or Nextcloud)
Notice board attachments are downloaded through the same app session (call
`downloadallegatobacheca`, which does **not** mark the notice as read) and uploaded to an archive,
chosen with `[allegati] archivio` (or per pupil in `[alunni.allegati]`):

| `archivio` | Where | Link in the notification and the event |
| --- | --- | --- |
| `""` (default) | disabled | — |
| `"drive"` (or the older `drive = true`) | Google Drive of the calendars' account | the file's Drive page (Google login) |
| `"nextcloud"` | Nextcloud over WebDAV | `<url>/f/<id>` (Nextcloud login) or a public share |

Each attachment is uploaded once: tracked in `state.json` (separately for Drive and Nextcloud, so
switching archive re-uploads everything to the new one) and by an `argo_key` property on the file,
which prevents duplicates even if `state.json` is lost. The first runs also fetch attachments already
published, at most `max_per_giro` per run. A failure on one attachment does not stop the sync: it is
retried at the next run.

**Folders and names** are set by `percorso` and `nome_file`; the defaults give:
```
Scuola/Anna/2026/10 - Ottobre/2026-10-12 Circ. n. 012 - Uscita didattica….pdf
```
```toml
[allegati]
archivio = "drive"
cartella = "Scuola"
percorso = "{cartella}/{alunno}/{anno}/{mese:02d} - {nome_mese}"
nome_file = "{data} {nome}"
max_per_giro = 30
```
Placeholders: `{cartella}` (root folder) `{alunno}` (pupil name or `sottocartella`) `{anno}` (year)
`{mese}` (month) `{nome_mese}` (Italian month name) `{giorno}` (day) `{data}` (YYYY-MM-DD) `{nome}`
(original file name), with Python format specs such as `{mese:02d}`. When a notice has no date,
folders using it are skipped and the file keeps its original name. An unknown placeholder stops the
startup with an error. Changing them does not move files already uploaded.

**Google Drive.** Needs the `drive.file` permission (the script only sees files it creates) and the
Google Drive API enabled in the project: `uv run pocs/04_google_auth.py --login`, then copy
`token.json` to the server again. If the permission is missing, the log says so and attachments are
skipped; the calendar keeps working.

**Nextcloud.** WebDAV with an app password (Personal settings → Security → Create new app password)
in `NEXTCLOUD_APP_PASSWORD`, or the variable named in `password_env`. URL and user come from
`[allegati.nextcloud]` or from `NEXTCLOUD_URL` / `NEXTCLOUD_USER`, which win (handy in the Portainer
stack); a pupil's own `[alunni.allegati.nextcloud]` still wins over both.
```toml
[allegati]
archivio = "nextcloud"
[allegati.nextcloud]
url = "https://cloud.example.org"
utente = "my.user"
link = "interno"        # or "pubblico"
scadenza_giorni = 0     # "pubblico" only: 0 = never expires
```
- `link = "interno"` (default): `<url>/f/<id>`, opens only after logging in to Nextcloud.
- `link = "pubblico"`: read-only public share (reusing the file's existing one), openable by anyone
  with the link. With `scadenza_giorni` it stops working after N days, also in the calendar events
  already created. If the server requires a password for public links, the log says so and the link
  is retried at the next run.
- Switching `link` doesn't re-upload anything: links of the attachments still on the notice board
  are rebuilt, `max_per_giro` per run.
- Two attachments with the same name in the same folder become `name (2).pdf`; a file you put there
  by hand with the same name is never overwritten.
- Check with `uv run pocs/09_nextcloud.py` (read-only) and `--scrivi` (test file). If Nextcloud is
  unreachable or the password is wrong, the log says so and attachments are skipped.

The config is read **at startup**: after editing `config.toml` on the server, restart the container
(`docker compose restart`).

## Google setup (one-off)
1. Google Cloud Console, with the calendars' account → new project → enable **Google Calendar API**
   (and **Google Drive API** if attachments are archived on Drive).
2. *Google Auth Platform → Audience* (OAuth consent screen): External, then **Publish app**
   (*In production*). In *Testing* the login is blocked for non-testers (403 `access_denied`) and the
   refresh token expires after 7 days. Google verification is not needed: the consent screen shows
   "app not verified" → Advanced → Go to … .
3. *Credentials* → OAuth client ID → **Desktop app** → download the JSON to `data/client_secret.json`.
4. From a computer with a browser:
   ```bash
   uv run pocs/04_google_auth.py --login        # creates pocs/out/token-poc.json
   cp pocs/out/token-poc.json data/token.json && chmod 600 data/token.json
   uv run pocs/04_google_auth.py                # checks scopes, refresh and calendar access
   ```
5. In Google Calendar create one calendar per child; its ID (Settings → Integrate calendar,
   `…@group.calendar.google.com`) goes into `calendar_id`. The `calendar.events` scope cannot create
   calendars, so this is manual. A 404 from PoC 04 means a wrong ID.

## Local trial
```bash
mkdir -p data && cp config.example.toml data/config.toml     # then edit
cp .env.example .env && chmod 600 .env                       # then fill in
uv run pocs/01_argo_login.py                                 # Argo login and profiles
uv run pocs/03_argo_orario.py --giorni 6                     # timetable and resulting lessons
docker build -t didup-calendar .
E="-v $PWD/data:/data --env-file .env"
docker run --rm $E didup-calendar --dry-run                       # what it would do, no writes or notifications
docker run --rm $E didup-calendar -v                              # one real run
```
The first real run stores everything without notifying; from the second one only new items are
notified. A second run right after must report `0 creati, 0 aggiornati, 0 rimossi`.

Once in production do **not** also run the script from your computer: two instances fight over
`token.json` and `state.json` and notifications are sent twice.

## Installation
The image is public and multi-arch (amd64, arm64: it runs on a Raspberry Pi too):
`ghcr.io/fabrizionota/didup-calendar-sync`, tagged `latest` and per version (e.g. `2026.10.13`).

### Docker Compose
```bash
mkdir didup-calendar-sync && cd didup-calendar-sync
curl -fsSLO https://raw.githubusercontent.com/fabrizionota/didup-calendar-sync/main/deploy/compose.yml
mkdir -p data      # config.toml, client_secret.json, token.json (see Configuration and Google setup)
curl -fsSL -o .env https://raw.githubusercontent.com/fabrizionota/didup-calendar-sync/main/.env.example
chmod 600 .env     # then fill in
sudo chown -R 1000:1000 data && sudo chmod 700 data
docker compose up -d && docker compose logs -f
```
`deploy/compose.yml` runs every 30 minutes (`SYNC_INTERVAL`), with a healthcheck (the container is
*healthy* only if the last run succeeded and is recent), a non-root user and a read-only filesystem
except `/data`.

- **Update**: `docker compose pull && docker compose up -d`. To choose when to update, pin a version
  instead of `latest` (see the [CHANGELOG](CHANGELOG.md)).
- **Config changed**: it is read at startup, so `docker compose restart`.
- **Portainer**: create a stack with the same compose and put the secrets in *Environment variables*;
  `env_file` can be replaced by `environment:`.

### Where to run it
It needs very little: about 150 MB of RAM, a few CPU seconds every 30 minutes, under 1 MB of disk,
no inbound port.

- **At home** (Raspberry Pi, NAS, mini PC): the simplest choice, it reaches Home Assistant on the LAN.
- **Free VM** (e.g. Google Compute Engine e2-micro "Always Free", US regions): same compose. To
  notify a Home Assistant at home you need a public HA URL or a VPN (Tailscale, WireGuard).
- **Scheduled job** (Cloud Run Job + Cloud Scheduler, cron, Kubernetes CronJob): start the container
  with `--loop 0` (one run, then exit) and a persistent `/data`.

One instance per configuration: two instances fight over `token.json` and `state.json` and
notifications are sent twice.

## Releases
GitHub Actions runs the tests on every push and pull request. A push to `main` publishes the `edge`
image; a `vYYYY.MM.DD` tag publishes `YYYY.MM.DD` and `latest`. The version is logged at startup.

## Tests
```bash
uv run --no-project --python 3.12 --with-requirements requirements.txt \
  python -m unittest discover -s tests -v       # offline, no account
docker build --target test .                    # same as CI
```

## PoCs
`pocs/` holds one script per integration (Argo login, dashboard, timetable and attachments, Google
auth, Calendar, notifications, Nextcloud), run with `uv run`, reusing `data/config.toml` and `.env`. Read-only by default,
writes only with `--scrivi` on a test calendar, `--anonimizza` to share output safely. They also show
how the main script interprets the same data. Details (in Italian) in [pocs/README.md](pocs/README.md).

## Behaviour
- Managed events are tagged (extended property `argo_sync=1`): anything created by hand is left alone.
- Lessons: updated or removed only on days whose timetable was downloaded successfully; past ones stay.
- Homework: a change by the teacher updates the lesson (or the 📚 event); past 📚 events stay as history.
- Safety net: if Argo returns nothing in a run, or more than half of the existing events (and more
  than 10) would disappear, deletion is skipped.
- When a sync fails you get **one** error notification, and one when it recovers.
- `argo-client-version` is read from the App Store on every run, to avoid the 410 for outdated clients.
- At startup the log shows the version and one line per pupil with active notifications and the
  attachment archive, e.g. `didup-calendar-sync 2026.10.13-abc1234 …` and `config /data/config.toml:
  Anna (SC67890/0): notifiche voti,bacheca,note,promemoria, allegati drive`: handy to check that
  the container runs the right image and config.
- Attachments: the script never calls "presa visione" (read receipt) or sign-up; downloading an
  attachment doesn't set them.

## Known limitations
- Unofficial Argo APIs (reverse engineered): they can change without notice.
- The Argo timetable can be incomplete compared with the school's (e.g. hours of a teacher not yet
  entered): those hours are missing and their homework becomes 📚 events.
- A Drive attachment link opens only for the Google account owning the files (the calendars' one)
  or whoever has access to the folder: for other phones share the `Scuola` folder in Drive, or use
  Nextcloud with `link = "pubblico"`.
- Schools use different fields (e.g. disciplinary notes with `desDescrizione`/`datNota`): if a type
  comes through empty, PoCs 02/03 show the raw response to see which fields to use.
