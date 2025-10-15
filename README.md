# energy monitoring system

automated energy data collection and analysis for hsv utilities and ecobee thermostats.

## features
- collect electric, gas, and water usage data from hsv utilities
- collect hvac runtime and temperature data from ecobee
- analyze usage patterns and efficiency
- generate insights and recommendations
- send data to home assistant
- create visualizations and reports

## setup
1. install dependencies: `python3 setup.py`
2. update .env with your credentials
3. run initial data collection: `python3 hsv_scraper.py && python3 ecobee_scraper.py`
4. run analysis: `python3 energy_analyzer.py`

## Environment Configuration

This project uses a `.env` file to manage credentials and important runtime settings. You should copy or use the provided `.env.example` as a template. Set your values according to the following guidelines:

- **Account Credentials:**
  - HSV and Ecobee usernames/passwords are required for scraping their respective portals.

- **Data Collection Intervals:**
  - You can control how often data is collected for each utility (e.g., electric, gas, water) by setting the related interval options. Common options are `HOURLY`, `DAILY`, `MONTHLY`, and sometimes `15_MIN` (for HSV electric data). See `.env.example` for available choices. Typically, faster intervals mean more granular data, but can increase API calls.

- **Analysis Period:**
  - The configurable number of days of data to analyze/collect is set in your `.env`. Adjust this if you want long-term or short-term views.

- **Home Assistant Integration:**
  - Set your Home Assistant URL and create a long-lived access token in your HA profile under security. This enables pushing data and automation triggers directly.

- **Feature/Notification Settings:**
  - Various `true`/`false` toggles are available for enabling notifications, report generation, and efficiency/cost alert thresholds. Adjust according to your notification preferences and what you consider "high usage."

- **Other Settings:**
  - Visual output, such as plot images, reporting options, and further customizations, are also managed via your `.env` file.
  

For a complete list of all possible variables and descriptions of valid values, see the comments in the `.env.example` file included with this repository.

## cli usage
```bash
python3 energy_cli.py collect    # collect data
python3 energy_cli.py analyze    # run analysis
python3 energy_cli.py status     # show system status
python3 energy_cli.py stats      # quick usage stats
python3 energy_cli.py cleanup    # clean old files
python3 energy_cli.py full-run   # collect + analyze
```

## automation
use cron or systemd to automate data collection and analysis. templates provided in setup.