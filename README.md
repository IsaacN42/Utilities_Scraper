# Utilities Scraper

Automated energy data collection for HSV Utilities and Ecobee thermostats with Home Assistant integration.

---

## Features

- **HSV Utilities Data Collection**
  - Electric, gas, and water usage
  - Historical data retrieval
  - Incremental updates every 15 minutes
  - Automatic bill PDF downloads

- **Ecobee Thermostat Data**
  - HVAC runtime and temperature data
  - Indoor/outdoor conditions
  - Equipment usage tracking
  - 5-minute interval data

- **Home Assistant Integration**
  - Real-time usage sensors
  - Automated data collection
  - Dashboard-ready metrics
  - Cost tracking and alerts

---

## Requirements

- Python 3.8+
- Home Assistant instance
- HSV Utilities account
- Ecobee account with authenticator app (Microsoft Authenticator recommended)

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium  # Required for Ecobee login
```

### 2. Configure Environment

Copy the example file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your account details:

```bash
# HSV Utilities
HSV_USERNAME=your_email@example.com
HSV_PASSWORD=your_password

# Ecobee
ECOBEE_USERNAME=your_email@example.com
ECOBEE_PASSWORD=your_password
ECOBEE_TOTP_SECRET=YOUR_AUTHENTICATOR_SECRET

# Data collection
DATA_PERIOD_DAYS=-1  # -1 for all available data, or number of days
STORE_INTERVAL_MINUTES=15

# Intervals
ELECTRIC_INTERVAL=HOURLY  # Options: HOURLY, DAILY, MONTHLY, 15_MIN
GAS_INTERVAL=HOURLY
WATER_INTERVAL=MONTHLY
```

**Getting your Ecobee TOTP secret:**
1. Go to Ecobee security settings
2. Enable authenticator app 2FA
3. Click "Can't scan QR code?"
4. Copy the secret key shown
5. Add to both Microsoft Authenticator and your `.env` file

### 3. Initial Data Collection

Run the full scrapers once to get historical data:

```bash
# Set DATA_PERIOD_DAYS=-1 in .env first
python utilities_scraper/scrapers/ecobee_scraper_v2.py
python utilities_scraper/scrapers/hsv_scraper_v2.py
```

This creates:
- `data/ecobee/ecobee_current.json` - Main data file
- `data/utilities/hsv_current.json` - Main data file
- Timestamped backups in the same directories

### 4. Set Up Incremental Updates

The incremental scrapers append new data every 15 minutes:

```bash
python utilities_scraper/scrapers/ecobee_scraper_incremental.py
python utilities_scraper/scrapers/hsv_scraper_incremental.py
```

---

## Home Assistant Integration

### Shell Commands

Add to your `configuration.yaml`:

```yaml
shell_command:
  ecobee_update: "python /path/to/Utilities_Scraper/utilities_scraper/scrapers/ecobee_scraper_incremental.py"
  hsv_update: "python /path/to/Utilities_Scraper/utilities_scraper/scrapers/hsv_scraper_incremental.py"
  hsv_bills: "python /path/to/Utilities_Scraper/utilities_scraper/scrapers/hsv_bill_scraper.py"
```

### Automations

Add automated data collection:

```yaml
automation:
  - alias: "Ecobee Data Collection"
    trigger:
      - platform: time_pattern
        minutes: "/15"
    action:
      - service: shell_command.ecobee_update

  - alias: "HSV Utilities Data Collection"
    trigger:
      - platform: time_pattern
        minutes: "/15"
    action:
      - service: shell_command.hsv_update
  
  - alias: "HSV Bill Download"
    trigger:
      - platform: time
        at: "03:00:00"  # Daily at 3am
    action:
      - service: shell_command.hsv_bills
```

### Sensors

Create template sensors to expose the data:

```yaml
sensor:
  - platform: command_line
    name: "Electric Usage"
    command: "python /path/to/read_usage.py electric"
    unit_of_measurement: "kWh"
    scan_interval: 900  # 15 minutes
  
  - platform: command_line
    name: "Gas Usage"
    command: "python /path/to/read_usage.py gas"
    unit_of_measurement: "CCF"
    scan_interval: 900
```

---

## File Structure

```
Utilities_Scraper/
├── .env                          # Your credentials (gitignored)
├── .env.example                  # Template
├── requirements.txt
├── .gitignore
└── utilities_scraper/
    └── scrapers/
        ├── ecobee_scraper_v2.py           # Full historical pull
        ├── ecobee_scraper_incremental.py  # Append new data
        ├── hsv_scraper_v2.py              # Full historical pull
        ├── hsv_scraper_incremental.py     # Append new data
        └── hsv_bill_scraper.py            # Download bill PDFs

Data files (gitignored):
├── data/
│   ├── ecobee/
│   │   ├── ecobee_current.json           # Incrementally updated
│   │   └── ecobee_data_*.json            # Timestamped backups
│   ├── utilities/
│   │   ├── hsv_current.json              # Incrementally updated
│   │   └── hsu_usage_*.json              # Timestamped backups
│   └── bills/
│       ├── billing_history_current.json
│       └── *.pdf                         # Bill PDFs

Token files (gitignored):
├── ecobee_session.json           # Playwright browser session
├── ecobee_token.json             # API access token
└── hsv_token.json                # API access token
```

---

## How It Works

### Token Caching
Both scrapers cache authentication tokens to avoid unnecessary logins:
- **Ecobee**: Token valid for 1 hour, browser session valid for weeks
- **HSV**: Token valid until expiration timestamp

On first run, scrapers will authenticate. Subsequent runs reuse cached tokens until they expire.

### Data Collection Strategy

**Full Scrapers (v2):**
- Set `DATA_PERIOD_DAYS=-1` to fetch all available history
- Auto-detects how far back data exists
- Saves to `*_current.json` + timestamped backup
- Use once initially, then switch to incremental

**Incremental Scrapers:**
- Load existing `*_current.json`
- Find last timestamp in data
- Fetch from last timestamp - 1 day (for overlap)
- Deduplicate by timestamp
- Append only new readings
- Overwrite `*_current.json`
- Run every 15 minutes via Home Assistant

### Bill Scraper
- Downloads all available HSV utility bill PDFs
- Skips already-downloaded files
- Saves billing history JSON
- Run monthly or as needed

---

## Environment Variables

### Required
```bash
HSV_USERNAME              # HSV Utilities email
HSV_PASSWORD              # HSV Utilities password
ECOBEE_USERNAME           # Ecobee account email
ECOBEE_PASSWORD           # Ecobee account password
ECOBEE_TOTP_SECRET        # Authenticator app secret key
```

### Optional
```bash
DATA_PERIOD_DAYS=-1                 # -1 for all data, or number of days (default: 7)
STORE_INTERVAL_MINUTES=15           # Ecobee reading interval (default: 15)
ELECTRIC_INTERVAL=HOURLY            # Options: HOURLY, DAILY, MONTHLY, 15_MIN
GAS_INTERVAL=HOURLY                 # Options: HOURLY, DAILY, MONTHLY
WATER_INTERVAL=MONTHLY              # Options: MONTHLY (HSV limitation)
```

---

## Troubleshooting

**Ecobee login fails:**
- Verify TOTP secret is correct
- Check username/password
- Ensure Microsoft Authenticator shows same codes
- Delete `ecobee_session.json` and `ecobee_token.json` to force fresh login

**HSV login fails:**
- Verify credentials in `.env`
- Check for special characters in password (they're automatically URL-encoded)
- Delete `hsv_token.json` to force fresh login

**No data collected:**
- Check file permissions on `data/` directory
- Verify Python can write to the directory
- Look for error messages in script output

**Incremental scraper not adding data:**
- Verify `*_current.json` exists (run full scraper first)
- Check that enough time has passed for new data (15+ minutes)
- Look at timestamps in the JSON to verify data is recent

---

## Data Format

### Ecobee Data Structure
```json
{
  "THERMOSTAT": [{
    "thermostatId": "421824700251",
    "totalReadings": 16316,
    "readings": [{
      "timestamp": 1735257600000,
      "datetime": "2024-12-27T00:00:00",
      "data": {
        "zoneAveTemp": "720",
        "outdoorTemp": "450",
        "hvacMode": "heat",
        ...
      }
    }]
  }]
}
```

### HSV Data Structure
```json
{
  "ELECTRIC": [{
    "meterNumber": "123456789",
    "unitOfMeasure": "KWH",
    "totalReadings": 8640,
    "readings": [{
      "timestamp": 1735257600000,
      "datetime": "2024-12-27T00:00:00",
      "usage": 1.25
    }]
  }],
  "GAS": [...],
  "WATER": [...]
}
```

---

## Advanced Usage

### Manual Data Collection
Run scrapers manually anytime:
```bash
# Get new data
python utilities_scraper/scrapers/ecobee_scraper_incremental.py
python utilities_scraper/scrapers/hsv_scraper_incremental.py

# Download bills
python utilities_scraper/scrapers/hsv_bill_scraper.py
```

### Rebuild From Scratch
To start over with fresh data:
```bash
# Delete existing data
rm data/ecobee/ecobee_current.json
rm data/utilities/hsv_current.json

# Delete tokens to force reauth
rm ecobee_token.json ecobee_session.json hsv_token.json

# Run full pull
python utilities_scraper/scrapers/ecobee_scraper_v2.py
python utilities_scraper/scrapers/hsv_scraper_v2.py
```
