import os
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from src.crew.tools.db_tools import get_high_rainfall_events, run_all_basins_inference_tool, get_affected_roads_tool, get_alert_plan_tool, log_alert_tool
from src.crew.tools.data_tools import sync_rain_data_tool, update_forecasts_tool, fetch_ims_warnings_tool, sync_flow_data_tool, search_flood_news_tool, search_israeli_rss_tool, search_telegram_channels_tool
from src.crew.tools.alert_tools import send_telegram_alert_tool

@CrewBase
class AegisEcoCrew():
    """AegisEco Flood Detection Crew"""
    
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def data_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['data_engineer'],
            tools=[sync_rain_data_tool, sync_flow_data_tool, update_forecasts_tool] 
        )

    @agent
    def warning_monitor(self) -> Agent:
        return Agent(
            config=self.agents_config['warning_monitor'],
            tools=[fetch_ims_warnings_tool]
        )
    
    @agent
    def flood_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['flood_analyst'],
            tools=[run_all_basins_inference_tool] 
        )
    
    @agent
    def osint_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['osint_analyst'],
            tools=[search_flood_news_tool]
        )

    @agent
    def rss_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['rss_analyst'],
            tools=[search_israeli_rss_tool]
        )

    @agent
    def telegram_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['telegram_analyst'],
            tools=[search_telegram_channels_tool]
        )

    @agent
    def communications_officer(self) -> Agent:
        return Agent(
            config=self.agents_config['communications_officer'],
            tools=[get_alert_plan_tool, get_affected_roads_tool, send_telegram_alert_tool, log_alert_tool]
        )

    @task
    def fetch_and_store_task(self) -> Task:
        return Task(
            config=self.tasks_config['fetch_and_store_task'],
            agent=self.data_engineer()
        )

    @task
    def analyze_risk_task(self) -> Task:
        return Task(
            config=self.tasks_config['analyze_risk_task'],
            agent=self.flood_analyst()
        )

    @task
    def monitor_warnings_task(self) -> Task:
        return Task(
            config=self.tasks_config['monitor_warnings_task'],
            agent=self.warning_monitor()
        )
    
    @task
    def verify_floods_task(self) -> Task:
        return Task(
            config=self.tasks_config['verify_floods_task'],
            agent=self.osint_analyst()
        )

    @task
    def verify_rss_task(self) -> Task:
        return Task(
            config=self.tasks_config['verify_rss_task'],
            agent=self.rss_analyst()
        )

    @task
    def verify_telegram_task(self) -> Task:
        return Task(
            config=self.tasks_config['verify_telegram_task'],
            agent=self.telegram_analyst()
        )
    
    @task
    def alert_task(self) -> Task:
        return Task(
            config=self.tasks_config['alert_task'],
            agent=self.communications_officer()
        )
    
    # Main crew that runs all agents
    @crew
    def crew(self) -> Crew:
        """Creates the AegisEco crew"""
        return Crew(
            agents=self.agents,
            # EXPLICIT ORDER: This guarantees the workflow follows the right logic!
            tasks=[
                self.fetch_and_store_task(),   # 1. Ingest Data
                self.analyze_risk_task(),      # 2. Run ML Inference
                self.verify_floods_task(),     # 3. DuckDuckGo OSINT
                self.verify_rss_task(),        # 4. Israeli News RSS
                self.verify_telegram_task(),   # 5. Telegram Emergency Channels
                self.monitor_warnings_task(),  # 6. IMS Warnings
                self.alert_task()              # 7. Send Alert
            ],
            process=Process.sequential,
            verbose=True
        )
    
    # This is a sub-crew that only runs the data fetching and storing
    def data_only_crew(self) -> Crew:
        """Creates a sub-crew that only fetches and stores data"""
        return Crew(
            agents=[self.data_engineer()],
            tasks=[self.fetch_and_store_task()],
            process=Process.sequential,
            verbose=True
        )