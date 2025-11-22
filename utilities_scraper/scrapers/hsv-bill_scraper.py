import requests
import json
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()
USERNAME = os.getenv("HSV_USERNAME")
PASSWORD = os.getenv("HSV_PASSWORD")
BASE_URL = "https://hsvutil.smarthub.coop"

def create_session():
    """create authenticated session"""
    session = requests.Session()
    
    # login
    response = session.post(
        f"{BASE_URL}/login", 
        data={"username": USERNAME, "password": PASSWORD},
        headers={"User-Agent": "Mozilla/5.0"}, 
        allow_redirects=True
    )
    if not ("/ui/" in response.url or "dashboard" in response.url.lower()):
        print("✗ login failed")
        return None
    print("✓ login successful")
    
    # get oauth token
    response = session.post(
        f"{BASE_URL}/services/oauth/auth/v2",
        data=f"userId={USERNAME}&password={PASSWORD}",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    if response.status_code != 200:
        print("✗ oauth failed")
        return None
    
    token = response.json().get("authorizationToken")
    if not token:
        print("✗ no token")
        return None
    
    session.headers.update({'Authorization': f'Bearer {token}'})
    print("✓ oauth token obtained")
    return session

def get_account_info(session):
    """get account number"""
    response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
    accounts = response.json()
    account_number = str(accounts[0]["account"])
    print(f"✓ account: {account_number}")
    return account_number

def get_billing_history(session, account_number):
    """get list of all bills"""
    response = session.get(
        f"{BASE_URL}/services/secured/billing/history/overview",
        params={"acctNbr": account_number}
    )
    return response.json()

def download_bill_pdf(session, bill_data, output_dir="data/bills"):
    """download single bill pdf"""
    account = bill_data["acctNbr"]
    timestamp = bill_data["billingDateTimestamp"]
    uuid = bill_data["billProcessUuid"]
    system = bill_data["systemOfRecord"]
    
    # generate filename
    date = datetime.fromtimestamp(timestamp / 1000)
    filename = f"{date.year}_{str(date.month).zfill(2)}_{date.day}_{account}.pdf"
    
    url = f"{BASE_URL}/services/secured/billPdfService/{filename}"
    params = {
        "account": account,
        "timestamp": timestamp,
        "uuid": uuid,
        "systemOfRecord": system
    }
    
    response = session.get(url, params=params)
    
    if response.status_code == 200:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        filepath = Path(output_dir) / filename
        with open(filepath, "wb") as f:
            f.write(response.content)
        print(f"  ✓ {bill_data['billPeriod']['year']}-{bill_data['billPeriod']['month']:>3} | ${bill_data['adjustedBillAmount']:>7.2f} | {filename}")
        return filepath
    
    print(f"  ✗ failed: {filename}")
    return None

def save_billing_data(bills, output_dir="data/bills"):
    """save billing data json"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = Path(output_dir) / f"billing_history_{timestamp}.json"
    
    with open(filepath, "w") as f:
        json.dump(bills, f, indent=2)
    print(f"\n✓ billing data saved: {filepath}")

def print_summary(bills):
    """print billing summary"""
    print("\n" + "="*60)
    print("HSV UTILITIES BILLING SUMMARY")
    print("="*60)
    
    total_amount = sum(b["adjustedBillAmount"] for b in bills)
    print(f"\nTotal bills: {len(bills)}")
    print(f"Total amount: ${total_amount:.2f}")
    print(f"Average bill: ${total_amount/len(bills):.2f}")
    
    print("\nBills by month:")
    for bill in bills:
        period = bill["billPeriod"]
        print(f"  {period['year']}-{period['month']:>3}: ${bill['adjustedBillAmount']:>7.2f}")

def main():
    print("="*60)
    print("HSV UTILITIES BILL DOWNLOADER")
    print("="*60)
    
    session = create_session()
    if not session:
        print("\n✗ authentication failed")
        return
    
    account_number = get_account_info(session)
    
    print("\n📄 fetching billing history...")
    bills = get_billing_history(session, account_number)
    print(f"✓ found {len(bills)} bills")
    
    print("\n📥 downloading pdfs...")
    downloaded = 0
    for bill in bills:
        if bill.get("showViewBillLink"):
            if download_bill_pdf(session, bill):
                downloaded += 1
            time.sleep(0.5)
    
    print(f"\n✓ downloaded {downloaded}/{len(bills)} pdfs")
    
    save_billing_data(bills)
    print_summary(bills)
    
    print("\n✓ bill download complete")

if __name__ == "__main__":
    main()