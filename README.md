# Won'tBuy

Won'tBuy is an Agentic Marketing demo that separates two campaign failures:

- **Wrong eyes:** paid targeting reaches people who were never going to buy.
- **Wrong words:** the right buyers see the campaign but reject weak copy.

The demo campaign is for **Northline**, a factory-dashboard product for plant managers. In round 1, broad targeting reaches Jules, a student who would click even though she is not a buyer. After targeting is tightened, Jules is **Not reached this round**; she did not change her mind—the campaign stopped paying to reach her.

All impressions and campaign results are simulated. Won'tBuy is not connected to live ads.

## Run locally

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

Start the app:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).
