#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

def install_requirements():
    requirements = [
        'pandas>=1.3.0',
        'matplotlib>=3.5.0',
        'seaborn>=0.11.0',
        'numpy>=1.21.0',
        'requests>=2.25.0',
        'python-dotenv>=0.19.0',
        'pyyaml>=6.0'
    ]
    
    print("installing required packages...")
    for package in requirements:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
        print(f"installed {package}")
    
    return True

def setup_directories():
    dirs = ['plots', 'logs', 'data', 'reports']
    
    print("creating directories...")
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        print(f"created {dir_name}/ directory")

def create_config_template():
    env_additions = """
# energy analysis configuration
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token_here

# analysis settings
ANALYSIS_ENABLED=true
AUTO_GENERATE_REPORTS=true
SAVE_PLOTS=true

# notification settings
ENABLE_NOTIFICATIONS=true
EFFICIENCY_THRESHOLD=60
COST_ALERT_THRESHOLD=15.00
"""
    
    print("updating .env configuration...")
    with open('.env', 'a', encoding='utf-8') as f:
        f.write('\n' + env_additions)
    print("configuration template added to .env")

def create_cron_job():
    cron_template = """
# add this to your crontab (run 'crontab -e' to edit)
# run energy analysis every 6 hours
0 */6 * * * /usr/bin/python3 /path/to/your/energy_analyzer.py >> /path/to/your/logs/analysis.log 2>&1

# run data collection every hour
0 * * * * /usr/bin/python3 /path/to/your/utilities_scraper/scrapers/hsv_scraper.py >> /path/to/your/logs/scraper.log 2>&1
30 * * * * /usr/bin/python3 /path/to/your/utilities_scraper/scrapers/ecobee_scraper.py >> /path/to/your/logs/ecobee.log 2>&1

# generate weekly report every monday at 8 am
0 8 * * 1 /usr/bin/python3 /path/to/your/utilities_scraper/main.py analyze --weekly >> /path/to/your/logs/reports.log 2>&1
"""
    
    with open('cron_template.txt', 'w', encoding='utf-8') as f:
        f.write(cron_template)
    
    print("created cron job template: cron_template.txt")

def create_systemd_service():
    service_template = """[Unit]
Description=Energy Data Collection Service
After=network.target

[Service]
Type=oneshot
User=your_username
WorkingDirectory=/path/to/your/energy_monitoring
ExecStart=/usr/bin/python3 /path/to/your/energy_analyzer.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    
    timer_template = """[Unit]
Description=Run Energy Analysis Every 6 Hours
Requires=energy-monitoring.service

[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
Persistent=true

[Install]
WantedBy=timers.target
"""
    
    with open('energy-monitoring.service', 'w', encoding='utf-8') as f:
        f.write(service_template)
    
    with open('energy-monitoring.timer', 'w', encoding='utf-8') as f:
        f.write(timer_template)
    
    print("created systemd service templates")

def setup_home_assistant():
    print("\nhome assistant setup instructions:")
    print("=" * 50)
    print("1. generate a long-lived access token:")
    print("   - go to your ha profile (click your name in sidebar)")
    print("   - scroll to 'long-lived access tokens'")
    print("   - click 'create token'")
    print("   - copy the token and add it to your .env file")
    print()
    print("2. enable python scripts (if not already enabled):")
    print("   - add to configuration.yaml: python_script:")
    print("   - create folder: /config/python_scripts/")
    print("   - restart home assistant")
    print()
    print("3. add the provided yaml to your configuration.yaml")
    print("4. add the dashboard configuration to your lovelace ui")
    print("5. install 'file editor' add-on for easy config editing")

def create_test_script():
    test_script = '''#!/usr/bin/env python3
import sys
import json
from pathlib import Path

def test_data_files():
    print("testing data files...")
    
    hsv_files = list(Path("data/utilities").glob("hsu_usage_*.json"))
    ecobee_files = list(Path("data/ecobee").glob("ecobee_data_*.json"))
    
    if not hsv_files:
        print("no hsv utility data files found")
        return False
    
    print(f"found {len(hsv_files)} hsv data files")
    
    if not ecobee_files:
        print("no ecobee data files found (optional)")
    else:
        print(f"found {len(ecobee_files)} ecobee data files")
    
    # test file format
    with open(hsv_files[0], 'r') as f:
        data = json.load(f)
    print("hsv data file format is valid")
    
    return True

def test_imports():
    print("testing package imports...")
    
    packages = ['pandas', 'matplotlib', 'seaborn', 'numpy', 'requests']
    
    for package in packages:
        __import__(package)
        print(f"✓ {package}")
    
    return True

def test_analyzer():
    print("testing energy analyzer...")
    
    from energy_analyzer import EnergyDataAnalyzer
    analyzer = EnergyDataAnalyzer()
    print("energy analyzer imported successfully")
    return True

def main():
    print("energy monitoring system test")
    print("=" * 40)
    
    tests = [
        ("package imports", test_imports),
        ("data files", test_data_files),
        ("energy analyzer", test_analyzer)
    ]
    
    passed = 0
    for test_name, test_func in tests:
        print(f"\\nrunning {test_name} test...")
        if test_func():
            passed += 1
        else:
            print(f"{test_name} test failed")
    
    print(f"\\ntest results: {passed}/{len(tests)} tests passed")
    
    if passed == len(tests):
        print("all tests passed! your energy monitoring system is ready!")
    else:
        print("some tests failed. please check the issues above.")

if __name__ == "__main__":
    main()
'''
    
    with open('test_system.py', 'w', encoding='utf-8') as f:
        f.write(test_script)
    
    os.chmod('test_system.py', 0o755)
    print("created test script: test_system.py")

def main():
    print("energy monitoring system setup")
    print("=" * 40)
    
    # install requirements
    if not install_requirements():
        print("failed to install requirements. please install manually.")
        return
    
    # setup directories
    setup_directories()
    
    # create config templates
    create_config_template()
    
    # create automation templates
    create_cron_job()
    create_systemd_service()
    
    # create test script
    create_test_script()
    
    # show home assistant setup
    setup_home_assistant()
    
    print("\nsetup complete!")
    print("=" * 40)
    print("next steps:")
    print("1. update your .env file with home assistant details")
    print("2. run 'python3 test_system.py' to verify everything works")
    print("3. configure home assistant using the provided yaml")
    print("4. set up automation using cron or systemd")
    print("5. run your first analysis: 'python3 energy_analyzer.py'")
    print("\ncheck the generated files for detailed configuration!")

if __name__ == "__main__":
    main()