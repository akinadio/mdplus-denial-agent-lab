# Putting OrthoAppeals online — the simple version

You need three things, then one command. Total time: about 20 minutes, most of
it waiting.

## What you're doing

Right now the app runs on a laptop. To let real patients use it, it has to live
on an always-on computer in the cloud (a "server"). You'll rent a small one,
point your web address at it, and paste in one setup command. That's it. You
never have to log into it again day to day.

## Step 1 — Rent the server (~$6–12/month)

Make an account at one of these and create the smallest "Ubuntu 24.04" machine
they offer (any of them is fine):

- Hetzner Cloud (cheapest, ~$5) — https://console.hetzner.cloud
- DigitalOcean (easiest UI) — https://cloud.digitalocean.com
- Fly.io, Linode, Vultr — all fine

Pick 2 GB of memory or more. When it's created, they'll show you an **IP
address** (four numbers like `203.0.113.5`) and let you log in with a "root"
password or an SSH key. Keep that handy.

## Step 2 — Point your domain at it

In whatever site you bought your domain from (GoDaddy, Namecheap, Cloudflare,
etc.), add a DNS **A record** that points your domain at the server's IP
address from Step 1. If your domain is `orthoappeals.com`, point both
`orthoappeals.com` and `www.orthoappeals.com` at that IP.

DNS can take a few minutes to an hour to take effect. That's normal.

## Step 3 — Run the one command

Log into the server (your host shows you how — usually a "Console" button in
their website, or `ssh root@YOUR-IP`). Then paste this, replacing the domain
with yours:

```bash
curl -fsSL https://raw.githubusercontent.com/andrewbouras/mdplus-denial-agent-lab/main/deploy/setup.sh -o setup.sh
sudo ORTHO_DOMAIN=orthoappeals.com bash setup.sh
```

It installs everything and starts the site. Near the end it will tell you to add
your **Anthropic API key**. Do that:

```bash
sudo nano /etc/mdplus/mdplus.env      # find ANTHROPIC_API_KEY= and paste your key after the =
sudo systemctl restart orthoappeals
```

(Your key stays on your server. You never send it to anyone, including me.)

## Done

Open `https://your-domain.com/` in a browser. The HTTPS lock icon appears
automatically the first time you visit. Patients can now use it.

Everyday commands, if you ever need them:

- See that it's running: `systemctl status orthoappeals`
- Watch live logs: `journalctl -u orthoappeals -f`
- Update to the newest code later: re-run the `setup.sh` command from Step 3

### Notes

- **Daily spending cap.** The setup sets a safety cap (default $50/day of API
  usage) so a busy day can't surprise you with a big bill. Change it in
  `/etc/mdplus/mdplus.env` (`MDPLUS_DAILY_BUDGET_USD=`) and restart. When the
  cap is hit, the site politely tells people to try again tomorrow.
- **Optional extra models.** To turn on the live Claude-vs-GPT-vs-Gemini
  comparison, add `OPENAI_API_KEY=` and `GOOGLE_API_KEY=` in the same secrets
  file. Anthropic alone is all you need to launch.
