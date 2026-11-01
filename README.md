# simshood

## Social Simulation Powered By AI Chatbots

### Create
  * Character Creator: Create sims with unique personas based in loosely interpreted Traits
### Observe
  * Get classis sims view of neighborhood
  * Increase Simulated Speed (Speed Up Progression of Time) 1x - 10x
  * Observe relationships, daily habits, secrets & lies &
### Inject
  * Inject Articles Into A Personalized News Feed
  * Change probabilities of events by changing socioeconomic tatistics 
  * Insert a sociopath stalker or a serial-killer psychopath 
### Jack-In (VR)
  * Avatar Mode: Interact & Manipulate 
  * Director Mode: Adjust and Fine-Tune Actors

## Run
```bash
cp .env.example .env
docker compose up --build
```
Open http://localhost:8000

Without Docker (Postgres, Redis and Python installed locally):
```bash
scripts/local_db.sh
```
```bash
scripts/run_local.sh
```
`local_db.sh` starts Postgres and Redis with the same settings as docker-compose (creating the `sim` database the first
time); `scripts/local_db.sh stop` stops them.

If Ollama has no model yet:
```bash
docker compose exec ollama ollama pull llama3
```

## Is Ollama up?
```bash
scripts/check_ollama.sh
```
Probes the Ollama server (default `http://192.168.10.176:11434`, override with `OLLAMA=...`) and prints what the sim
has seen at `GET /admin/ollama_status`: `status` (up / degraded / down), last reply and last error from the real
model calls (core and workers), and whether the configured model is installed.

## Add families
A fresh world starts with three extra households of three, each in its own house. To add more to a running world:
```bash
curl -X POST localhost:8000/admin/generate_households -H 'Content-Type: application/json' -d '{"count": 3, "members": 3}'
```
