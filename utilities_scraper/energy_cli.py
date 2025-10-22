#!/usr/bin/env python3
import argparse
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

def run_data_collection():
    print("starting data collection...")
    
    # run hsv scraper
    print("collecting hsv utility data...")
    result = subprocess.run([sys.executable, 'hsv_scraper.py'], 
                          capture_output=True, text=True, timeout=300)
    if result.returncode == 0:
        print("hsv data collection completed")
    else:
        print(f"hsv collection failed: {result.stderr}")
    
    # run ecobee scraper
    print("collecting ecobee data...")
    result = subprocess.run([sys.executable, 'ecobee_scraper.py'], 
                          capture_output=True, text=True, timeout=180)
    if result.returncode == 0:
        print("ecobee data collection completed")
    else:
        print(f"ecobee collection failed: {result.stderr}")

def run_analysis(weekly_report=False, send_to_ha=True):
    print("starting energy analysis...")
    
    from energy_analyzer import EnergyDataAnalyzer
    
    # configure home assistant integration
    ha_url = os.getenv('HA_URL')
    ha_token = os.getenv('HA_TOKEN')
    
    if send_to_ha and ha_url and ha_token:
        analyzer = EnergyDataAnalyzer(ha_url, ha_token)
        print("home assistant integration enabled")
    else:
        analyzer = EnergyDataAnalyzer()
        print("running analysis without ha integration")
    
    # find data files
    hsv_files = list(Path(".").glob("hsu_usage_*.json"))
    ecobee_files = list(Path(".").glob("ecobee_data_*.json"))
    
    if not hsv_files:
        print("no hsv utility data found. run data collection first.")
        return False
    
    # load data
    latest_hsv = max(hsv_files, key=lambda p: p.stat().st_mtime)
    hsv_df = analyzer.load_hsv_data(str(latest_hsv))
    print(f"loaded hsv data: {len(hsv_df)} records")
    
    ecobee_df = None
    if ecobee_files:
        latest_ecobee = max(ecobee_files, key=lambda p: p.stat().st_mtime)
        ecobee_df = analyzer.load_ecobee_data(str(latest_ecobee))
        print(f"loaded ecobee data: {len(ecobee_df)} records")
    else:
        import pandas as pd
        ecobee_df = pd.DataFrame()
        print("no ecobee data available")
    
    # run analysis
    usage_patterns = analyzer.analyze_usage_patterns(hsv_df)
    hvac_efficiency = analyzer.analyze_hvac_efficiency(ecobee_df)
    correlations = analyzer.correlate_hvac_usage(hsv_df, ecobee_df)
    
    # generate insights
    analyzer.generate_insights(usage_patterns, hvac_efficiency, correlations)
    
    # create visualizations
    plot_path = analyzer.create_visualizations(hsv_df, ecobee_df)
    
    # send to home assistant
    if send_to_ha and ha_url and ha_token:
        analyzer.create_ha_sensors(usage_patterns, hvac_efficiency)
    
    # generate report
    report_type = "weekly" if weekly_report else "standard"
    report_file = f"energy_report_{report_type}_{datetime.now().strftime('%Y%m%d')}.txt"
    analyzer.generate_report(report_file)
    
    # print summary
    print("\n" + "="*50)
    print("analysis summary")
    print("="*50)
    print(f"insights: {len(analyzer.insights)}")
    print(f"recommendations: {len(analyzer.recommendations)}")
    print(f"plot saved: {plot_path}")
    print(f"report saved: {report_file}")
    
    # show top insights
    if analyzer.insights:
        print("\nkey insights:")
        for i, insight in enumerate(analyzer.insights[:3], 1):
            print(f"  {i}. {insight}")
    
    if analyzer.recommendations:
        print("\ntop recommendations:")
        for i, rec in enumerate(analyzer.recommendations[:3], 1):
            print(f"  {i}. {rec}")
    
    return True

def show_status():
    print("energy monitoring system status")
    print("="*40)
    
    # check for data files
    hsv_files = list(Path(".").glob("hsu_usage_*.json"))
    ecobee_files = list(Path(".").glob("ecobee_data_*.json"))
    
    print(f"hsv data files: {len(hsv_files)}")
    if hsv_files:
        latest = max(hsv_files, key=lambda p: p.stat().st_mtime)
        mod_time = datetime.fromtimestamp(latest.stat().st_mtime)
        print(f"   latest: {latest.name} ({mod_time.strftime('%Y-%m-%d %H:%M:%S')})")
    
    print(f"ecobee data files: {len(ecobee_files)}")
    if ecobee_files:
        latest = max(ecobee_files, key=lambda p: p.stat().st_mtime)
        mod_time = datetime.fromtimestamp(latest.stat().st_mtime)
        print(f"   latest: {latest.name} ({mod_time.strftime('%Y-%m-%d %H:%M:%S')})")
    
    # check reports
    reports = list(Path(".").glob("energy_report_*.txt"))
    print(f"reports generated: {len(reports)}")
    
    # check plots
    plots = list(Path("plots").glob("*.png")) if Path("plots").exists() else []
    print(f"plots generated: {len(plots)}")
    
    # home assistant status
    ha_url = os.getenv('HA_URL')
    ha_token = os.getenv('HA_TOKEN')
    ha_status = "configured" if (ha_url and ha_token) else "not configured"
    print(f"home assistant: {ha_status}")

def cleanup_old_files(days_old=30):
    print(f"cleaning up files older than {days_old} days...")
    
    cutoff_date = datetime.now() - timedelta(days=days_old)
    cutoff_timestamp = cutoff_date.timestamp()
    
    file_patterns = ["hsu_usage_*.json", "ecobee_data_*.json", "energy_report_*.txt"]
    cleaned_count = 0
    
    for pattern in file_patterns:
        for file_path in Path(".").glob(pattern):
            if file_path.stat().st_mtime < cutoff_timestamp:
                file_path.unlink()
                print(f"deleted: {file_path.name}")
                cleaned_count += 1
    
    # clean old plots
    if Path("plots").exists():
        for file_path in Path("plots").glob("*.png"):
            if file_path.stat().st_mtime < cutoff_timestamp:
                file_path.unlink()
                print(f"deleted: plots/{file_path.name}")
                cleaned_count += 1
    
    print(f"cleaned up {cleaned_count} old files")

def quick_stats():
    # find latest hsv data
    hsv_files = list(Path(".").glob("hsu_usage_*.json"))
    if not hsv_files:
        print("no data files found")
        return
    
    latest_hsv = max(hsv_files, key=lambda p: p.stat().st_mtime)
    
    with open(latest_hsv, 'r') as f:
        data = json.load(f)
    
    print("quick energy stats")
    print("="*30)
    
    for utility_type, meters in data.items():
        total_usage = 0
        unit = "unknown"
        
        for meter in meters:
            unit = meter.get('unitOfMeasure', unit)
            for reading in meter.get('readings', []):
                total_usage += reading.get('usage', 0)
        
        print(f"{utility_type}: {total_usage:.2f} {unit}")

def main():
    parser = argparse.ArgumentParser(description='energy monitoring system cli')
    parser.add_argument('command', choices=[
        'collect', 'analyze', 'status', 'stats', 'cleanup', 'full-run'
    ], help='command to run')
    
    parser.add_argument('--weekly', action='store_true', 
                       help='generate weekly report (for analyze command)')
    parser.add_argument('--no-ha', action='store_true',
                       help='skip home assistant integration')
    parser.add_argument('--cleanup-days', type=int, default=30,
                       help='days old for cleanup (default: 30)')
    
    args = parser.parse_args()
    
    print(f"energy monitoring cli - {args.command.upper()}")
    print("="*50)
    
    if args.command == 'collect':
        run_data_collection()
        
    elif args.command == 'analyze':
        run_analysis(weekly_report=args.weekly, send_to_ha=not args.no_ha)
        
    elif args.command == 'status':
        show_status()
        
    elif args.command == 'stats':
        quick_stats()
        
    elif args.command == 'cleanup':
        cleanup_old_files(args.cleanup_days)
        
    elif args.command == 'full-run':
        print("running complete data collection and analysis...")
        run_data_collection()
        print("\n" + "="*30)
        run_analysis(weekly_report=args.weekly, send_to_ha=not args.no_ha)
    
    print("\ncommand completed!")

if __name__ == "__main__":
    main()