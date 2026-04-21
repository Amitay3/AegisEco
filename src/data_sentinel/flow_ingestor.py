import requests
import time
import os
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables (Make sure DATABASE_URL is in your .env file)
load_dotenv()

class AegisEcoDataIngestor:
    def __init__(self):
        self.base_url = "https://www.weather2day.co.il/clientfiles/public/floods.json"
        self.database_url = os.getenv("DATABASE_URL")
        
        # Translating Hebrew to English basin names
        self.station_mapping = {
            "חרוד-כביש 90": "Harod",
            "שורק-יבנה": "Sorek - lower",
            "שורק-יסודות": "Sorek - lower", 
            "שורק-מוצא": "Shorek - upper",
            "שורק הר טוב": "Shorek - upper",
            "שורק-כביש גדרה בילו": "Sorek - lower",
            "דישון-כביש ראש פינה-מטולה": "Dishon",
            "ירדן דגניה": "Upper Jordan River-south west",
            "ירדן-שדה נחמיה": "Upper Jordan River-north west",
            "ירדן-גשר הפקק": "Upper Jordan River-east",
            "ירדן-אתר טבילה": "Upper Jordan River-east",
            "ירדן-בית זרע": "Jordan Naharayim",
            "ירדן - גשר": "Jordan Naharayim",
            "ירקון-כביש להרצליה": "Yarkon - lower",
            "דן שמורת טבע": "Dan",
            "חרמון-כביש לכפר סאלד": "Hermon",
            "שניר מעין ברוך": "Snir",
            "שניר-כביש לדן": "Snir",
            "בשור-רעים": "Besor -lower",
            "יהודיה-בית צידה": "Yehudiya",
            "חיון": "Hayon - upper",
            "צלמון": "Tzalmon",
            "איילון נתבג": "Yarkon - upper, Ayalon",
            "איילון - לוד": "Yarkon - upper, Ayalon",
            "קישון-מחצבה": "Kishon - lower",
            "באר שבע-חצרים": "Besor - upper, Beer Sheva",
            "נטוף-אל על": "Yarkon - upper, Shilo",
            "דליה בת שלמה": "Dalya",
            "דליה כביש תא-חיפה": "Dalya",
            "חדרה - גן שמואל": "Hadera",
            "עיון-מטולה": "Upper Jordan River-north west",
            "אלכסנדר-אליישיב": "Alexander",
            "משושים-דרדרה": "Meshushim",
            "שקמה -ארז": "Shikma - lower",
            "שקמה-ברור חייל": "Shikma - upper",
            "ציפורי-תל עליל": "Kishon - upper, Zepuri",
            "עורבים-להבות הבשן": "Upper Jordan River-east",
            "רחף": "Rahaf",
            "אשלים במעלה": "Ashalim",
            "תעלת אשלים": "Ashalim",
            "יבניאל": "Yavneel",
            "געתון - בן עמי ח.": "Gaaton",
            "עמוד": "Amud",
            "לכיש-עד הלום": "Lachish - Sourek",
            "דליות-בית צידה": "Daliyot",
            "חילזון-יסעור": "Naaman - upper",
            "צין - כביש הערבה": "Tsin -lower",
            "צאלים": "Zeelim",
            "ערוגות": "Arugot",
            "אמציהו- במעלה עין תמר": "Amatsyahu",
            "שילה - כביש לוד-ראש העין": "Yarkon - upper, Shilo",
            "שילה במורד הזרימה": "Yarkon - upper, Shilo",
            "שילה במעלה": "Yarkon - upper, Shilo",
            "נחל חברון": "Besor - upper, Beer Sheva",
            "האלה - גן יבנה": "Lachish - Ela",
            "האלה-תל צפית": "Lachish - Ela",
            "קנה-ירחיב": "Yarkon - upper, Kana",
            "עדה-גבעת עדה": "Hadera",
            "תנינים עמיקם": "Taninim",
            "בצת - כביש 4": "Betzet",
            "כזיב": "Kziv",
            "סמך": "Samach",
            "יסף": "Yasaf",
            "עמרם": "Amram"
        }

    def fetch_live_data(self):
        print("[API Client] Fetching live river flows via API...")
        current_timestamp = int(time.time() * 1000)
        dynamic_url = f"{self.base_url}?_={current_timestamp}"
        rivers_data = {}
        
        try:
            response = requests.get(dynamic_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for station in data:
                raw_name = station["name"]
                if '\\u' in raw_name:
                    hebrew_name = raw_name.encode('utf-8').decode('unicode_escape')
                else:
                    hebrew_name = raw_name

                english_name = self.station_mapping.get(hebrew_name)
                
                if english_name:
                    for obs in station.get("obs", []):
                        if obs.get("flow") not in (None, ""):
                            current_flow = float(obs["flow"])
                            
                            # Keep the maximum flow if multiple stations map to the same English basin name
                            if english_name not in rivers_data or current_flow > rivers_data[english_name]["flow_m3s"]:
                                
                                # Convert API date/time string to a proper Python datetime object
                                date_str = obs.get('date')
                                time_str = obs.get('time')
                                try:
                                    # Expected format from weather2day: DD/MM/YYYY HH:MM
                                    dt_obj = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                                except ValueError:
                                    print(f"Warning: Could not parse date '{date_str} {time_str}' for {english_name}. Using current time.")
                                    dt_obj = datetime.now()

                                rivers_data[english_name] = {
                                    "flow_m3s": current_flow,
                                    "measurement_time": dt_obj,
                                    "original_hebrew": hebrew_name
                                }
                            break 
            
            print(f"[API Client] Extracted data for {len(rivers_data)} mapped stations.")
            return rivers_data

        except Exception as e:
            print(f"[API Client Error]: {e}")
            return {}

    def save_to_neon(self, rivers_data):
        """Pushes the fetched flow data into the Neon PostgreSQL database."""
        if not rivers_data:
            print("No flow data to save.")
            return

        if not self.database_url:
            print("Error: DATABASE_URL environment variable is missing!")
            return

        # Prepare data tuples for the bulk insert
        data_tuples = []
        for basin, data in rivers_data.items():
            data_tuples.append((
                basin, 
                data['measurement_time'], 
                data['flow_m3s'], 
                data['original_hebrew']
            ))

        # The UPSERT query: Insert, but if the record already exists for this exact time and basin, update it.
        insert_query = """
        INSERT INTO raw_flow_measurements (basin_name, measurement_time, flow_m3s, original_hebrew_name)
        VALUES %s
        ON CONFLICT (basin_name, measurement_time) 
        DO UPDATE SET flow_m3s = EXCLUDED.flow_m3s, original_hebrew_name = EXCLUDED.original_hebrew_name;
        """

        try:
            conn = psycopg2.connect(self.database_url)
            cur = conn.cursor()
            
            print(f"--- Pushing {len(data_tuples)} flow records to Neon ---")
            execute_values(cur, insert_query, data_tuples)
            
            conn.commit()
            print(f"✅ Successfully saved {len(data_tuples)} records to 'raw_flow_measurements'.")

        except Exception as e:
            print(f"Database insertion error: {e}")
            if 'conn' in locals() and conn: conn.rollback()
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals() and conn: conn.close()

# ==========================================
# Execution
# ==========================================
if __name__ == "__main__":
    ingestor = AegisEcoDataIngestor()
    
    # 1. Fetch the data from the API
    live_map_data = ingestor.fetch_live_data()
    
    # 2. Save it straight to Neon
    ingestor.save_to_neon(live_map_data)