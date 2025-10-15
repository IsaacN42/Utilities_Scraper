import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import requests
import yaml
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

class EnergyDataAnalyzer:
    def __init__(self, ha_url: str = None, ha_token: str = None):
        self.ha_url = ha_url
        self.ha_token = ha_token
        self.ha_headers = {'Authorization': f'Bearer {ha_token}', 'Content-Type': 'application/json'} if ha_token else None
        
        # analysis results storage
        self.insights = []
        self.recommendations = []
        
    def load_hsv_data(self, filename: str) -> pd.DataFrame:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        all_readings = []
        
        for utility_type, meters in data.items():
            for meter in meters:
                meter_number = meter['meterNumber']
                unit = meter['unitOfMeasure']
                
                for reading in meter['readings']:
                    # handle different datetime formats
                    if reading['timestamp']:
                        dt = datetime.fromtimestamp(reading['timestamp'] / 1000)
                    else:
                        # handle monthly format like "8/2024"
                        dt = datetime.strptime(reading['datetime'], "%m/%Y") if "/" in reading['datetime'] else datetime.fromisoformat(reading['datetime'])
                    
                    all_readings.append({
                        'datetime': dt,
                        'utility_type': utility_type,
                        'meter_number': meter_number,
                        'usage': reading['usage'],
                        'unit': unit,
                        'flow_direction': meter.get('flowDirection', 'DELIVERED')
                    })
        
        df = pd.DataFrame(all_readings)
        df['hour'] = df['datetime'].dt.hour
        df['day_of_week'] = df['datetime'].dt.day_name()
        df['month'] = df['datetime'].dt.month
        df['date'] = df['datetime'].dt.date
        
        return df
    
    def load_ecobee_data(self, filename: str) -> pd.DataFrame:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        all_readings = []
        
        for thermostat in data['THERMOSTAT']:
            thermostat_id = thermostat['thermostatId']
            
            for reading in thermostat['readings']:
                dt = datetime.fromtimestamp(reading['timestamp'] / 1000)
                
                # parse thermostat data
                reading_data = {
                    'datetime': dt,
                    'thermostat_id': thermostat_id,
                    'hour': dt.hour,
                    'day_of_week': dt.day_name(),
                    'month': dt.month,
                    'date': dt.date
                }
                
                # add all sensor data
                for key, value in reading['data'].items():
                    try:
                        reading_data[key] = float(value) if value and value != '' else None
                    except (ValueError, TypeError):
                        reading_data[key] = value
                
                all_readings.append(reading_data)
        
        return pd.DataFrame(all_readings)
    
    def analyze_usage_patterns(self, hsv_df: pd.DataFrame) -> Dict:
        patterns = {}
        
        for utility_type in hsv_df['utility_type'].unique():
            utility_data = hsv_df[hsv_df['utility_type'] == utility_type].copy()
            
            if len(utility_data) == 0:
                continue
                
            # daily patterns
            hourly_avg = utility_data.groupby('hour')['usage'].mean()
            peak_hour = hourly_avg.idxmax()
            peak_usage = hourly_avg.max()
            
            # weekly patterns
            daily_avg = utility_data.groupby('day_of_week')['usage'].mean()
            peak_day = daily_avg.idxmax()
            
            # usage statistics
            total_usage = utility_data['usage'].sum()
            avg_usage = utility_data['usage'].mean()
            
            patterns[utility_type] = {
                'total_usage': total_usage,
                'average_usage': avg_usage,
                'peak_hour': peak_hour,
                'peak_hour_usage': peak_usage,
                'peak_day': peak_day,
                'hourly_pattern': hourly_avg.to_dict(),
                'daily_pattern': daily_avg.to_dict(),
                'unit': utility_data['unit'].iloc[0]
            }
        
        return patterns
    
    def analyze_hvac_efficiency(self, ecobee_df: pd.DataFrame) -> Dict:
        if ecobee_df.empty:
            return {}
        
        # calculate runtime percentages
        hvac_columns = ['compCool1', 'compCool2', 'compHeat1', 'compHeat2', 'auxHeat1', 'auxHeat2', 'auxHeat3', 'fan']
        
        efficiency_data = {}
        
        # runtime analysis
        for col in hvac_columns:
            if col in ecobee_df.columns:
                runtime_pct = ecobee_df[col].mean() * 100 if ecobee_df[col].notna().any() else 0
                efficiency_data[f'{col}_runtime_pct'] = runtime_pct
        
        # temperature analysis
        if 'zoneAveTemp' in ecobee_df.columns and 'outdoorTemp' in ecobee_df.columns:
            temp_diff = ecobee_df['zoneAveTemp'] - ecobee_df['outdoorTemp']
            efficiency_data['avg_temp_differential'] = temp_diff.mean()
            
        # setpoint analysis
        if 'zoneCoolTemp' in ecobee_df.columns and 'zoneHeatTemp' in ecobee_df.columns:
            cooling_setpoint_avg = ecobee_df['zoneCoolTemp'].mean()
            heating_setpoint_avg = ecobee_df['zoneHeatTemp'].mean()
            efficiency_data['avg_cooling_setpoint'] = cooling_setpoint_avg
            efficiency_data['avg_heating_setpoint'] = heating_setpoint_avg
        
        return efficiency_data
    
    def correlate_hvac_usage(self, hsv_df: pd.DataFrame, ecobee_df: pd.DataFrame) -> Dict:
        correlations = {}
        
        # get electric usage data
        electric_data = hsv_df[hsv_df['utility_type'] == 'ELECTRIC'].copy()
        
        if electric_data.empty or ecobee_df.empty:
            return correlations
        
        # aggregate by hour for correlation
        electric_hourly = electric_data.groupby(electric_data['datetime'].dt.floor('H'))['usage'].sum()
        
        # hvac runtime data
        ecobee_df['datetime_hour'] = ecobee_df['datetime'].dt.floor('H')
        hvac_hourly = ecobee_df.groupby('datetime_hour').agg({
            'compCool1': 'mean',
            'compHeat1': 'mean',
            'fan': 'mean',
            'zoneAveTemp': 'mean',
            'outdoorTemp': 'mean'
        })
        
        # merge datasets
        merged = pd.merge(electric_hourly, hvac_hourly, left_index=True, right_index=True, how='inner')
        
        if not merged.empty:
            # calculate correlations
            for col in ['compCool1', 'compHeat1', 'fan']:
                if col in merged.columns:
                    corr = merged['usage'].corr(merged[col])
                    correlations[f'{col}_correlation'] = corr
            
            # temperature correlation
            if 'outdoorTemp' in merged.columns:
                correlations['outdoor_temp_correlation'] = merged['usage'].corr(merged['outdoorTemp'])
        
        return correlations
    
    def generate_insights(self, usage_patterns: Dict, hvac_efficiency: Dict, correlations: Dict):
        self.insights = []
        self.recommendations = []
        
        # electric usage insights
        if 'ELECTRIC' in usage_patterns:
            electric = usage_patterns['ELECTRIC']
            peak_hour = electric['peak_hour']
            
            if 14 <= peak_hour <= 18:  # peak demand hours
                self.insights.append(f"peak electric usage occurs at {peak_hour}:00 during expensive peak hours")
                self.recommendations.append("consider shifting high-energy activities to off-peak hours (before 2 pm or after 6 pm)")
            
            if electric['peak_day'] in ['Saturday', 'Sunday']:
                self.insights.append(f"highest usage day is {electric['peak_day']} - likely due to increased home occupancy")
            
        # hvac efficiency insights
        if hvac_efficiency:
            # cooling analysis
            if 'compCool1_runtime_pct' in hvac_efficiency:
                cool_runtime = hvac_efficiency['compCool1_runtime_pct']
                if cool_runtime > 50:
                    self.insights.append(f"ac compressor running {cool_runtime:.1f}% of the time - indicating high cooling load")
                    self.recommendations.append("consider raising cooling setpoint by 1-2°f or improving insulation")
            
            # heating analysis
            if 'compHeat1_runtime_pct' in hvac_efficiency:
                heat_runtime = hvac_efficiency['compHeat1_runtime_pct']
                if heat_runtime > 40:
                    self.insights.append(f"heat pump running {heat_runtime:.1f}% of the time")
                    self.recommendations.append("consider lowering heating setpoint or sealing air leaks")
            
            # auxiliary heat usage
            if any(key.startswith('auxHeat') for key in hvac_efficiency):
                aux_usage = sum(v for k, v in hvac_efficiency.items() if k.startswith('auxHeat') and isinstance(v, (int, float)))
                if aux_usage > 10:
                    self.insights.append("high auxiliary heat usage detected - very inefficient")
                    self.recommendations.append("check heat pump operation and consider maintenance")
        
        # correlation insights
        if correlations:
            if 'compCool1_correlation' in correlations and correlations['compCool1_correlation'] > 0.7:
                self.insights.append("strong correlation between ac usage and electric consumption")
                
            if 'outdoor_temp_correlation' in correlations:
                temp_corr = correlations['outdoor_temp_correlation']
                if abs(temp_corr) > 0.6:
                    direction = "increases" if temp_corr > 0 else "decreases"
                    self.insights.append(f"electric usage strongly {direction} with outdoor temperature")
    
    def create_visualizations(self, hsv_df: pd.DataFrame, ecobee_df: pd.DataFrame, save_dir: str = "plots"):
        Path(save_dir).mkdir(exist_ok=True)
        plt.style.use('seaborn-v0_8')
        
        # hourly usage patterns
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle('energy usage analysis', fontsize=16, fontweight='bold')
        
        # electric usage by hour
        if not hsv_df[hsv_df['utility_type'] == 'ELECTRIC'].empty:
            electric_hourly = hsv_df[hsv_df['utility_type'] == 'ELECTRIC'].groupby('hour')['usage'].mean()
            axes[0, 0].plot(electric_hourly.index, electric_hourly.values, marker='o', linewidth=2)
            axes[0, 0].set_title('average electric usage by hour')
            axes[0, 0].set_xlabel('hour of day')
            axes[0, 0].set_ylabel('kwh')
            axes[0, 0].grid(True, alpha=0.3)
        
        # daily usage comparison
        daily_usage = hsv_df.groupby(['date', 'utility_type'])['usage'].sum().reset_index()
        for utility in daily_usage['utility_type'].unique():
            utility_data = daily_usage[daily_usage['utility_type'] == utility]
            axes[0, 1].plot(utility_data['date'], utility_data['usage'], 
                           marker='o', label=utility, linewidth=2)
        axes[0, 1].set_title('daily usage trends')
        axes[0, 1].set_xlabel('date')
        axes[0, 1].set_ylabel('usage')
        axes[0, 1].legend()
        axes[0, 1].grid(True, alpha=0.3)
        
        # temperature vs hvac runtime (if data available)
        if not ecobee_df.empty and 'outdoorTemp' in ecobee_df.columns and 'compCool1' in ecobee_df.columns:
            scatter_data = ecobee_df.dropna(subset=['outdoorTemp', 'compCool1'])
            axes[1, 0].scatter(scatter_data['outdoorTemp'], scatter_data['compCool1'], 
                              alpha=0.5, s=10)
            axes[1, 0].set_title('outdoor temperature vs ac runtime')
            axes[1, 0].set_xlabel('outdoor temperature (°f)')
            axes[1, 0].set_ylabel('ac runtime %')
            axes[1, 0].grid(True, alpha=0.3)
        
        # weekly usage pattern
        weekly_usage = hsv_df.groupby('day_of_week')['usage'].mean()
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        weekly_ordered = weekly_usage.reindex(day_order).fillna(0)
        axes[1, 1].bar(range(len(weekly_ordered)), weekly_ordered.values)
        axes[1, 1].set_title('average usage by day of week')
        axes[1, 1].set_xlabel('day of week')
        axes[1, 1].set_ylabel('average usage')
        axes[1, 1].set_xticks(range(len(day_order)))
        axes[1, 1].set_xticklabels([day[:3] for day in day_order])
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(f'{save_dir}/energy_analysis.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        return f'{save_dir}/energy_analysis.png'
    
    def send_to_home_assistant(self, data: Dict, entity_id: str):
        if not self.ha_url or not self.ha_headers:
            return False
        
        url = f"{self.ha_url}/api/states/{entity_id}"
        response = requests.post(url, json=data, headers=self.ha_headers)
        response.raise_for_status()
        return True
    
    def create_ha_sensors(self, usage_patterns: Dict, hvac_efficiency: Dict):
        if not self.ha_url:
            return
        
        sensors = {}
        
        # create usage sensors
        for utility_type, data in usage_patterns.items():
            sensors[f"sensor.{utility_type.lower()}_usage_total"] = {
                "state": round(data['total_usage'], 2),
                "attributes": {
                    "unit_of_measurement": data['unit'],
                    "friendly_name": f"{utility_type.title()} Total Usage",
                    "peak_hour": data['peak_hour'],
                    "peak_day": data['peak_day'],
                    "average_usage": round(data['average_usage'], 2)
                }
            }
        
        # create hvac efficiency sensors
        if hvac_efficiency:
            sensors["sensor.hvac_efficiency"] = {
                "state": "monitoring",
                "attributes": {
                    "friendly_name": "HVAC Efficiency Monitor",
                    **{k: round(v, 2) if isinstance(v, (int, float)) else v 
                       for k, v in hvac_efficiency.items()}
                }
            }
        
        # send all sensors to ha
        for entity_id, data in sensors.items():
            self.send_to_home_assistant(data, entity_id)
    
    def generate_report(self, output_file: str = "energy_report.txt"):
        with open(output_file, 'w') as f:
            f.write("=" * 50 + "\n")
            f.write("energy usage analysis report\n")
            f.write(f"generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 50 + "\n\n")
            
            f.write("key insights:\n")
            f.write("-" * 20 + "\n")
            for i, insight in enumerate(self.insights, 1):
                f.write(f"{i}. {insight}\n")
            
            f.write("\nrecommendations:\n")
            f.write("-" * 20 + "\n")
            for i, rec in enumerate(self.recommendations, 1):
                f.write(f"{i}. {rec}\n")

def main():
    # configuration - update these with your home assistant details
    HA_URL = "http://homeassistant.local:8123"  # your ha url
    HA_TOKEN = "your_long_lived_access_token"   # create in ha profile > security
    
    # initialize analyzer
    analyzer = EnergyDataAnalyzer(HA_URL, HA_TOKEN)
    
    # find latest data files
    hsv_files = list(Path(".").glob("hsu_usage_*.json"))
    ecobee_files = list(Path(".").glob("ecobee_data_*.json"))
    
    if not hsv_files:
        print("no hsv utility data files found!")
        return
    
    # use the most recent files
    latest_hsv = max(hsv_files, key=lambda p: p.stat().st_mtime)
    latest_ecobee = max(ecobee_files, key=lambda p: p.stat().st_mtime) if ecobee_files else None
    
    print(f"loading hsv data from: {latest_hsv}")
    hsv_df = analyzer.load_hsv_data(str(latest_hsv))
    
    ecobee_df = pd.DataFrame()
    if latest_ecobee:
        print(f"loading ecobee data from: {latest_ecobee}")
        ecobee_df = analyzer.load_ecobee_data(str(latest_ecobee))
    
    # run analysis
    print("analyzing usage patterns...")
    usage_patterns = analyzer.analyze_usage_patterns(hsv_df)
    
    print("analyzing hvac efficiency...")
    hvac_efficiency = analyzer.analyze_hvac_efficiency(ecobee_df)
    
    print("correlating hvac and electric usage...")
    correlations = analyzer.correlate_hvac_usage(hsv_df, ecobee_df)
    
    # generate insights
    print("generating insights...")
    analyzer.generate_insights(usage_patterns, hvac_efficiency, correlations)
    
    # create visualizations
    print("creating visualizations...")
    plot_path = analyzer.create_visualizations(hsv_df, ecobee_df)
    print(f"plots saved to: {plot_path}")
    
    # send to home assistant (if configured)
    print("sending data to home assistant...")
    analyzer.create_ha_sensors(usage_patterns, hvac_efficiency)
    
    # generate report
    print("generating report...")
    analyzer.generate_report()
    
    print("\n" + "=" * 50)
    print("analysis complete!")
    print("=" * 50)
    print(f"insights found: {len(analyzer.insights)}")
    print(f"recommendations: {len(analyzer.recommendations)}")
    
    # print key insights
    if analyzer.insights:
        print("\nkey insights:")
        for insight in analyzer.insights[:3]:  # show top 3
            print(f"  • {insight}")
    
    if analyzer.recommendations:
        print("\ntop recommendations:")
        for rec in analyzer.recommendations[:3]:  # show top 3
            print(f"  • {rec}")

if __name__ == "__main__":
    main()