from flask import Flask, request, jsonify, make_response
import requests
from datetime import datetime
import xml.etree.ElementTree as ET

app = Flask(__name__)

TMS_API = "https://tms.tpf.go.tz/api/OffenceCheck"
TIRA_API = "https://tiramis.tira.go.tz/covernote/api/public/portal/verify"
GePG_API = "https://app.gepg.go.tz/api/v3/internal-assessment"

LOG_FILE = "log.txt"

def log_alert(message):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {message}\n")

def get_traffic_penalties(plate):
    try:
        res = requests.post(TMS_API, json={"vehicle": plate}, timeout=7)
        res.raise_for_status()
        data = res.json()
        if data.get("status") == "success" and data.get("pending_transactions"):
            tickets = data["pending_transactions"]
            total = sum(int(float(t.get("charge", 0)) + float(t.get("penalty", 0))) for t in tickets)
            log_alert(f"📛 Violation found for {plate} – Total: {total:,} TZS")
            return {"found": True, "tickets": tickets, "total": total}
        return {"found": False}
    except Exception as e:
        return {"error": str(e)}

def get_parking_fees(plate):
    try:
        payload = {
            "spCode": "SP99860",
            "assessType": "ASSESS-E",
            "assessTypeValue": plate.upper()
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Dart/3.2"
        }
        res = requests.post(GePG_API, json=payload, headers=headers, timeout=10)
        bills = res.json()[0].get("billDetails", [])
        if bills:
            total = sum([float(b["billAmount"]) for b in bills])
            log_alert(f"💸 Parking fee found for {plate} – Total: {int(total):,} TZS")
            return {"found": True, "bills": bills, "total": int(total)}
        return {"found": False}
    except Exception as e:
        return {"error": str(e)}

def get_insurance(plate):
    try:
        payload = {"paramType": 2, "searchParam": plate}
        headers = {
            "Content-Type": "application/json",
            "Origin": "https://tiramis.tira.go.tz",
            "User-Agent": "Mozilla/5.0"
        }
        res = requests.post(TIRA_API, json=payload, headers=headers, timeout=7, verify=False)
        xml_root = ET.fromstring(res.text)
        entries = xml_root.findall(".//data")
        if not entries:
            return {"expired": True, "expired_days": None}

        active = next((e for e in entries if e.findtext("statusTitle", "").upper() == "ACTIVE"), None)

        if not active:
            try:
                end_ts = int(entries[0].findtext("coverNoteEndDate", "0")) / 1000
                end_date = datetime.fromtimestamp(end_ts)
                days = (datetime.now() - end_date).days
                log_alert(f"❌ Insurance expired for {plate} – {days} days ago")
                return {"expired": True, "expired_days": days}
            except:
                return {"expired": True, "expired_days": None}
        else:
            end_ts = int(active.findtext("coverNoteEndDate", "0")) / 1000
            end_date = datetime.fromtimestamp(end_ts)
            days_left = (end_date - datetime.now()).days
            return {
                "active": True,
                "valid_till": end_date.strftime('%Y-%m-%d'),
                "remaining_days": days_left
            }
    except Exception as e:
        return {"error": str(e)}

@app.route("/check", methods=["POST"])
def check():
    try:
        data = request.json or {}
        plate = data.get("plate", "").upper()
        lang = data.get("lang", "en").lower()
        detail_type = data.get("type", "full").lower()

        result = {"plate": plate}
        traffic = get_traffic_penalties(plate)
        parking = get_parking_fees(plate)
        insurance = get_insurance(plate)

        result["traffic_penalties"] = traffic
        result["parking_fees"] = parking
        result["insurance"] = insurance

        notifications = []
        if isinstance(traffic, dict) and traffic.get("found"):
            msg = "🔴 Traffic Violation" if lang == "en" else "🔴 Kuna makosa ya barabarani"
            notifications.append(msg)
        if isinstance(parking, dict) and parking.get("found"):
            msg = "🅿️ Unpaid Parking" if lang == "en" else "🅿️ Kuna maegesho hayajalipwa"
            notifications.append(msg)
        if isinstance(insurance, dict) and insurance.get("expired"):
            msg = "⚠️ Insurance Expired" if lang == "en" else "⚠️ Bima imekwisha muda wake"
            notifications.append(msg)
        if isinstance(insurance, dict) and insurance.get("active") and insurance["remaining_days"] <= 10:
            msg = f"⏳ Insurance expiring soon ({insurance['remaining_days']} days left)" if lang == "en"                 else f"⏳ Bima inakaribia kuisha ({insurance['remaining_days']} siku)"
            notifications.append(msg)

        if detail_type == "summary":
            result = {
                "plate": plate,
                "notifications": notifications
            }
        else:
            result["notifications"] = notifications

        return make_response(jsonify(result), 200)

    except Exception as e:
        return make_response(jsonify({"error": str(e)}), 500)

if __name__ == "__main__":
    app.run(debug=True)
