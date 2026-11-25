# Deploying to a server

The whole system runs on **one Linux VM** under Docker Compose. Caddy is the only
thing exposed to the internet. It serves HTTPS, asks for a shared login (unless
deployed with `-Public`), and forwards to the orchestrator. The four agents and the orchestrator stay on the
internal Docker network.

```
browser --HTTPS + login--> Caddy :443 --> orchestrator --> soft_power / policy_stance / trade_intelligence / event_summarization
```

## 1. Create the VM (once)

Any cloud works. What matters:

| | |
|---|---|
| OS | Ubuntu 24.04 LTS |
| Memory | **8 GB recommended** (4 GB works; the deploy script adds 4 GB of swap) |
| Disk | 30 GB |
| Inbound ports | 22 (SSH), 80 and 443 (web) |
| Login | an SSH key pair; keep the private key file (`.pem`) |

**AWS EC2**: Launch instance → Ubuntu Server 24.04 → `t3.large` (8 GB) → create
a key pair and download the `.pem` → storage 30 GB → security group: allow SSH,
HTTP and HTTPS. The SSH user is `ubuntu`.

**Azure for Students** (free credit, no card): Create a virtual machine → Ubuntu
24.04 → size `B2ms` (8 GB) → SSH public key, download the key → inbound ports
SSH, HTTP, HTTPS → disk 30 GB. The SSH user is `azureuser`.

Note the VM's **public IP**. An 8 GB VM costs about $60-70 a month on demand;
stop it between reviews to save credit. Stopping can change the IP, and with it
the URL. Re-run the deploy after a restart; the data is kept.

## 2. Choose the login (once, on your laptop)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\set_password.ps1
```

This saves a bcrypt hash in `deploy\.auth` (gitignored). The password never
leaves your machine. Share it with the team and your guide separately.

To skip the login and let anyone with the link in, leave this step out and add
`-Public` to every `deploy.ps1` command below.

## 3. Deploy

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -Server ubuntu@<public-ip> -Key C:\path\to\key.pem
```

The script:

1. Bundles the code (about 24 MB) and the datasets that are not in git
   (about 490 MB: the trade cache with its 345 MB product store, the UN votes and
   UCDP data, the GGE scores).
2. Uploads both over SSH.
3. On the server, installs Docker, adds swap on small VMs, writes the Caddy login,
   builds the five images, and starts everything.

The first deploy takes **20-30 minutes**. Building the images takes 10-20, and
Policy Stance builds its cache on first start (about 10 minutes). When it
finishes it prints the URL, e.g. `https://203.0.113.10.sslip.io`.

`sslip.io` turns the IP into a hostname, so Caddy can get a real HTTPS certificate
without a domain. If you have a domain, point it at the IP and pass
`-Site team128.example.com`. For plain HTTP (not recommended, because the login
would travel unencrypted), pass `-Site http://<public-ip>`.

## 4. Update after code changes

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -Server ubuntu@<public-ip> -Key C:\path\to\key.pem -SkipData
```

`-SkipData` skips re-uploading the datasets. Only images whose code changed are
rebuilt.

### Faster: let the server fetch the code from GitHub

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -Server ubuntu@<public-ip> -Key C:\path\to\key.pem -SkipData -Public -FromGitHub
```

The normal update uploads the whole working tree (about 80 MB) from your laptop,
which takes 10-20 minutes on a slow or mobile connection. With `-FromGitHub` the
laptop sends a 1 KB script; the server downloads the latest commit of `main` from
GitHub itself (seconds on AWS's network) and builds it in the background, so the
whole update takes about 5 minutes and a dropped connection does not stop it.

- It deploys **what is on GitHub**, not your working tree: push first. It refuses
  to run while you have local commits that are not pushed, and it lists
  uncommitted files it is leaving out. `-Ref <branch>` deploys another branch.
- The repository must stay public, because the server downloads it without a login.
- Data still comes from your laptop: leave out `-SkipData` only when the datasets
  changed (see below).
- The build log is `~/team128-upload/setup.log` on the server; the commit that is
  live is in `~/team128-upload/deployed_commit`.

**If your network blocks SSH** (port 22 times out while websites load), open a
terminal in the browser instead: EC2 → Instances → select the instance → Connect →
EC2 Instance Connect → Connect, then run

```bash
curl -fsSL https://raw.githubusercontent.com/Takshak-CS/team128-geopolitical-intelligence/main/deploy/remote_from_github.sh -o ~/remote_from_github.sh && bash ~/remote_from_github.sh Takshak-CS/team128-geopolitical-intelligence main 65.1.109.59.sslip.io public && tail -f ~/team128-upload/setup.log
```

It is finished at the line `SETUP_EXIT=0` (Ctrl+C stops watching; the build carries on).

Do not `git pull` or `docker compose restart` on the server to update it: the
server has no git checkout, and the pages are built into the images, so only a
deploy (either kind above) picks up a change.

The trade sector tables are committed, so they travel with the code even with
`-SkipData`. The trade product store (`services/trade_intelligence/cache/products/`,
about 345 MB) is not: after building or refreshing it, deploy once **without**
`-SkipData` so the server gets it. Until it arrives the trade dashboard simply
hides product filtering.

## 5. Operating it

Run these on the server (`ssh -i key.pem ubuntu@<ip>`, then `cd ~/team128`):

| Task | Command |
|---|---|
| Status | `sudo docker compose -f docker-compose.prod.yml ps` |
| Logs of one service | `sudo docker compose -f docker-compose.prod.yml logs --tail 50 policy_stance` |
| Restart everything | `sudo docker compose -f docker-compose.prod.yml restart` |
| Stop everything | `sudo docker compose -f docker-compose.prod.yml down` |
| Change the login | run `set_password.ps1` again, then deploy with `-SkipData` |
| Switch between login and open access | deploy with `-SkipData`, adding `-Public` for open access |
| Read visitor reviews | on your laptop: `scripts\get_reviews.ps1 -Server ubuntu@<ip> -Key <key.pem>` saves them to `reviews.csv` |

The containers restart automatically after a crash or a VM reboot.

## Notes

- Each module's own dashboard is served on its own host next to the briefing UI:
  `softpower.`, `policystance.`, `events.` and `trade.` in front of the site
  address (e.g. `https://softpower.203.0.113.10.sslip.io`), and the briefing UI's
  "Open module dashboard" links point there. They are built into the Caddy image
  (`deploy/web.Dockerfile`) and call their agent through `/api` on their own host.
  sslip.io resolves these names by itself; with your own domain, add DNS records
  for them too. A plain-HTTP deploy on a bare IP (`-Site http://<ip>`) has no
  subdomains, so it skips the dashboards.
- Events downloads each new GDELT day from `data.gdeltproject.org`, so the server
  needs outbound internet. It keeps the last five days.
- `GEMINI_API_KEY` is only used by the Events module's optional article
  verification, which the orchestrator does not call.
- The site has three pages: `/` (home, the two ways in), `/features` (the four
  module dashboards) and `/engine` (the GEOINT Engine run console). Both second
  pages have a "Post a review" button; reviews (rating, review, suggestions,
  optional name) are stored by the orchestrator in SQLite on the
  `orchestrator_data` volume, so they survive redeploys. The site shows only
  their count and average; read them with `scripts/get_reviews.ps1`.
