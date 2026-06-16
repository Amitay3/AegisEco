"""
This is the main entry point for the AegisEco system. 
Running 'python main.py' in the terminal will immediately execute a single system cycle (fetching data and running the AI agents), 
and then start a background scheduler to automatically run the cycle at the top of every hour.
"""

import os
import sys
import time
import signal
from datetime import datetime, timedelta
from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED
from crewai import LLM

import warnings
# Suppress Resource management Warnings
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(base_dir)

# Disable litellm's remote fetch before importing crewai components
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

from src.crew.aegiseco_crew import AegisEcoCrew
from src.crew.tools.db_tools import _run_all_basins_inference, _get_alert_plan, _log_alert
from src.crew.tools.alert_tools import _send_telegram

last_sigint_time = 0
scheduler = BackgroundScheduler()
def run_system_cycle(mode="full"):
    """
    Executes the system cycle.
    mode="full" runs all agents (top of the hour).
    mode="data_only" runs only the Data Engineer (minutes 20, 40).
    """
    current_time = datetime.now().strftime('%H:%M:%S')
    cycle_name = "FULL System Cycle" if mode == "full" else "DATA SYNC ONLY Cycle"
    print(f"\n[{current_time}] Starting AegisEco {cycle_name}...")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY is missing from .env file.")
        return

    os.environ["GEMINI_API_KEY"] = api_key

    models_to_try = [
        "gemini/gemini-2.5-flash-lite",
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.0-pro-exp"
    ]

    result = None

    for attempt_idx, model_name in enumerate(models_to_try):
        attempt = attempt_idx + 1
        try:
            print(f"--- Attempt {attempt} (Model: {model_name}) ---")
            os.environ["MODEL"] = model_name
            
            aegis_project = AegisEcoCrew()
            
            if mode == "data_only":
                active_crew = aegis_project.data_only_crew()
            else:
                active_crew = aegis_project.crew()
            result = active_crew.kickoff()
            
            finish_time = datetime.now().strftime('%H:%M:%S')
            print(f"\n[{finish_time}] Cycle Completed Successfully!")
            print("================ SUMMARY ================")
            print(result)
            print("=========================================\n")
            
            break 
            
        except Exception as e:
            error_msg = str(e)
            print(error_msg)
            print(f"\nAttempt {attempt} Failed: {error_msg[:150]}...")
            if attempt < len(models_to_try):
                print(f"Model failure detected. Switching to backup model: {models_to_try[attempt_idx + 1]}...")
                time.sleep(2)
            else:
                print("All models failed. System cycle aborted.")

    if result is None and mode == "full":
        print("\n--- Running rule-based failsafe check ---")
        try:
            report = _run_all_basins_inference()
            print(report)

            new_alerts, all_clears, _ = _get_alert_plan()

            if new_alerts:
                basin_lines = "\n".join(f"- {basin}: {prob:.1f}%" for basin, prob, _ in new_alerts)
                msg = (
                    "⚠️ <b>[FAILSAFE ALERT]</b> AegisEco AI agents are currently unavailable.\n"
                    "Direct ML inference has detected flood risk in:\n\n"
                    f"{basin_lines}"
                )
                print(_send_telegram(msg))
                for basin, prob, _ in new_alerts:
                    _log_alert(basin, "flood_warning", prob)

            if all_clears:
                basin_lines = "\n".join(f"- {basin}: now {prob:.1f}%" for basin, prob, _ in all_clears)
                msg = (
                    "✅ <b>[FAILSAFE]</b> Flood warning lifted for:\n\n"
                    f"{basin_lines}"
                )
                print(_send_telegram(msg))
                for basin, prob, _ in all_clears:
                    _log_alert(basin, "all_clear", prob)

            if not new_alerts and not all_clears:
                print("Failsafe check complete: No alert changes.")
        except Exception as fe:
            print(f"Failsafe check failed: {fe}")

def print_next_run_time(event=None):
    now = datetime.now()
    print(f"\n[Scheduler] Action completed. System is standing by...\n")

if __name__ == "__main__":
    load_dotenv()
    
    print("AegisEco Controller Started (Paid Tier Enabled).")
    print("Monitoring Israel Floods...")
    print("Press Ctrl+C to exit.\n")
    
    # Run a full cycle immediately on startup
    run_system_cycle(mode="full")
    # 1. Full cycle exactly on the hour (xx:00)
    scheduler.add_job(
        run_system_cycle, 
        'cron', 
        minute=0, 
        kwargs={"mode": "full"}, 
        misfire_grace_time=900, 
        coalesce=True, 
        max_instances=1,
        id='full_cycle_job'
    ) 
    
    # 2. Data sync only every 10 minutes
    scheduler.add_job(
        run_system_cycle, 
        'cron', 
        minute= '10,20,30,40,50',
        kwargs={"mode": "data_only"}, 
        misfire_grace_time=300, 
        coalesce=True, 
        max_instances=1,
        id='data_sync_job'
    )
    
    scheduler.add_listener(print_next_run_time, EVENT_JOB_EXECUTED)
    scheduler.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        current_time = time.time()
        if current_time - last_sigint_time < 3:
            print("\nConfirmed. AegisEco Controller Shutting Down...")
            scheduler.shutdown(wait=False)
            sys.exit(0)
        else:
            print("\n[?] Press Ctrl+C again within 3 seconds to confirm exit.")
            last_sigint_time = current_time
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nConfirmed. AegisEco Controller Shutting Down...")
                scheduler.shutdown(wait=False)
                sys.exit(0)