import requests
import json
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import os
import urllib.parse

load_dotenv()
USERNAME = os.getenv("HSV_USERNAME")
PASSWORD = os.getenv("HSV_PASSWORD")
BASE_URL = "https://hsvutil.smarthub.coop"
TOKEN_FILE = "hsv_token.json"

def save_token(token_data):
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'token': token_data['authorizationToken'],
            'expiration': token_data['expiration'],
            'timestamp': datetime.now().isoformat()
        }, f)

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            data = json.load(f)
            exp = datetime.fromtimestamp(data['expiration'] / 1000)
            if exp > datetime.now():
                return data['token']
    return None

def create_session():
    """create authenticated session"""
    session = requests.Session()
    
    # try existing token
    token = load_token()
    if token:
        session.headers.update({'Authorization': f'Bearer {token}'})
        try:
            response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
            if response.status_code == 200:
                print("using cached token")
                return session
        except:
            pass
    
    # fresh login
    response = session.post(
        f"{BASE_URL}/login", 
        data={"username": USERNAME, "password": PASSWORD},
        headers={"User-Agent": "Mozilla/5.0"}, 
        allow_redirects=True
    )
    if not ("/ui/" in response.url or "dashboard" in response.url.lower()):
        print("login failed")
        return None
    
    # get oauth token
    response = session.post(
        f"{BASE_URL}/services/oauth/auth/v2",
        data=f"userId={urllib.parse.quote(USERNAME)}&password={urllib.parse.quote(PASSWORD)}",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    if response.status_code != 200:
        print("oauth failed")
        return None
    
    token_data = response.json()
    token = token_data.get("authorizationToken")
    if not token:
        print("no token")
        return None
    
    save_token(token_data)
    session.headers.update({'Authorization': f'Bearer {token}'})
    print("login successful")
    return session

def get_account_info(session):
    """get account number"""
    response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": USERNAME})
    accounts = response.json()
    account_number = str(accounts[0]["account"])
    print(f"account: {account_number}")
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
    
    # check if already exists
    filepath = Path(output_dir) / filename
    if filepath.exists():
        return filepath, True  # already downloaded
    
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
        with open(filepath, "wb") as f:
            f.write(response.content)
        return filepath, False  # newly downloaded
    
    return None, False

def save_billing_data(bills, output_dir="data/bills"):
    """save billing data json"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # save as current file
    current_file = Path(output_dir) / "billing_history_current.json"
    with open(current_file, "w") as f:
        json.dump(bills, f, indent=2)
    
    # also save timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = Path(output_dir) / f"billing_history_{timestamp}.json"
    with open(backup_file, "w") as f:
        json.dump(bills, f, indent=2)
    
    print(f"\ndata saved to {current_file}")
    print(f"backup saved to {backup_file}")

def print_summary(bills, downloaded, skipped):
    """print billing summary"""
    print("\n" + "="*60)
    print("hsv utilities billing summary")
    print("="*60)
    
    total_amount = sum(b["adjustedBillAmount"] for b in bills)
    print(f"\ntotal bills: {len(bills)}")
    print(f"downloaded: {downloaded} new, {skipped} existing")
    print(f"total amount: ${total_amount:.2f}")
    print(f"average bill: ${total_amount/len(bills):.2f}")
    
    print("\nbills by month:")
    for bill in bills[-12:]:  # show last 12 months
        period = bill["billPeriod"]
        print(f"  {period['year']}-{period['month']:>3}: ${bill['adjustedBillAmount']:>7.2f}")

def main():
    print("="*60)
    print("hsv utilities bill downloader")
    print("="*60)
    
    session = create_session()
    if not session:
        print("\nauthentication failed")
        return
    
    account_number = get_account_info(session)
    
    print("\nfetching billing history...")
    bills = get_billing_history(session, account_number)
    print(f"found {len(bills)} bills")
    
    print("\ndownloading pdfs...")
    downloaded = 0
    skipped = 0
    
    for bill in bills:
        if bill.get("showViewBillLink"):
            date = datetime.fromtimestamp(bill["billingDateTimestamp"] / 1000)
            filepath, exists = download_bill_pdf(session, bill)
            
            if filepath:
                if exists:
                    skipped += 1
                    print(f"  [skip] {date.year}-{date.month:02d} (already exists)")
                else:
                    downloaded += 1
                    print(f"  [new]  {date.year}-{date.month:02d} ${bill['adjustedBillAmount']:>7.2f}")
            else:
                print(f"  [fail] {date.year}-{date.month:02d}")
            
            time.sleep(0.3)
    
    save_billing_data(bills)
    print_summary(bills, downloaded, skipped)
    
    print("\nbill download complete")

if __name__ == "__main__":
    main()