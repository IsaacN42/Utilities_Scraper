# Utilities_Scraper Energy Monitoring System

Automated energy data collection & analysis for HSV Utilities and Ecobee thermostats—complete with insights, usage statistics, and Home Assistant integration.

---

## Features

- Collect electric, gas, and water usage data from HSV Utilities
- Retrieve and analyze HVAC data from Ecobee thermostats
- Output insights, efficiency recommendations, and cost calculations
- Push results/alerts to Home Assistant for notification and dashboarding
- Create system status plots and reports
- Flexible CLI and automation via cron/systemd

---

## Requirements

- Python 3.8+
- Access to your HSV Utilities and Ecobee accounts
- (Optional) A running [Home Assistant](https://www.home-assistant.io/) instance with API access

---

## Quick Start

1. **Clone the repo**
   ```sh
   git clone <your-repo-url>
   cd Utilities_Scraper
   ```

2. **Install dependencies**
   ```sh
   pip install -r requirements.txt
   ```
   Or, run the setup script for one-time initialization:
   ```sh
   python3 setup.py
   ```

3. **Create your `.env` file**
   - Copy the sample:
     ```sh
     cp env.example .env
     ```
   - Fill in all necessary account credentials and customize settings as desired.  
   - **See the comments in `env.example` for every variable, valid choices (intervals, alert thresholds, etc), and what they control.**

4. **Initial data collection**
   ```sh
   python3 hsv_scraper.py
   python3 ecobee_scraper.py
   ```

5. **Run an analysis**
   ```sh
   python3 energy_analyzer.py
   ```

6. **Review reports and plots**
   - Reports are saved in `/reports`
   - Visualizations appear in `/plots`

---

## Environment Configuration

Settings are managed using your `.env` file.  
Variables control:
- Account logins for data scraping
- Collection intervals (e.g., HOURLY, DAILY, MONTHLY: see `env.example`)
- Data analysis window (set `DATA_PERIOD_DAYS=-1` for all available data)
- Home Assistant integration (API URL, access token)
- Feature toggles and thresholds for notifications & alerts

**See `env.example` for full documentation of each variable and valid choices.**

---

## CLI Usage

Manage all tasks via the command line:

```sh
python3 energy_cli.py collect        # Collect both HSV & Ecobee data
python3 energy_cli.py analyze        # Run analysis and output results
python3 energy_cli.py status         # Check data, report, and integration status
python3 energy_cli.py stats          # Quick stats from latest data
python3 energy_cli.py cleanup        # Remove files older than N days (default: 30)
python3 energy_cli.py full-run       # Collect + analyze in one step
```
Additional flags:
- `--weekly` : Run/create a weekly report (for `analyze` and `full-run`)
- `--no-ha`  : Run without Home Assistant integration
- `--cleanup-days <n>` : Custom age (days) for cleanup

---

## Automation & Integration

- **Automate collection/analysis with cron or systemd:**  
  Templates (`cron_template.txt` and `energy-monitoring.service/timer`) are provided—edit with your executable/python path and file locations.

- **Home Assistant Integration:**  
  - Use the `home_assistant_config.yaml` provided in this repo to define sensors, automations, scripts, and dashboard cards.
  - Add it (or merge into) your HA `configuration.yaml`.
  - Notifications will go to your Home Assistant mobile app by default, but you can change the `notify` target to any HA-supported method (see [Home Assistant Notifications](https://www.home-assistant.io/integrations/notify/)).

---

## Troubleshooting

- Double-check `.env` formatting and values if data collection or analysis fails.
- See logs and error messages printed to terminal, and check `/logs` or the reports for diagnostic info.
- For API changes or authentication errors, re-generate your tokens or update your credentials.

---

## FAQ

**Q: What do "notifications" do? Where do they go?**  
A: Home Assistant automations will send push notifications to your mobile phone (if you use the Home Assistant companion app). Configure the target in the `home_assistant_config.yaml` `notify` service.

**Q: How do I customize what “period” my data covers?**  
A: Set `DATA_PERIOD_DAYS` in your `.env`. Use `-1` for all data, or an integer for a specific window.

**Q: Can I change how often scrapers pull data?**  
A: Yes! Edit `ELECTRIC_INTERVAL`, `GAS_INTERVAL`, and `WATER_INTERVAL` in your `.env`. Valid values are documented in `env.example`.

---

## Project Layout

```
Utilities_Scraper/
  ├── README.md
  ├── env.example
  ├── requirements.txt
  ├── setup.py
  ├── energy_cli.py
  ├── energy_analyzer.py
  ├── hsv_scraper.py
  ├── ecobee_scraper.py
  ├── cron_template.txt
  ├── energy-monitoring.service, .timer
  ├── home_assistant_config.yaml
  ├── data/
  ├── logs/
  ├── plots/
  ├── reports/
```
---

Let me know if you want further improvements or specific code blocks/examples shown inline!
