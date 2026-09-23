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

If Ollama has no model yet:
```bash
docker compose exec ollama ollama pull llama3
```
