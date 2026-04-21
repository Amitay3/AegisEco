import os
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
# Import the database and data tools using absolute paths from the root
from src.crew.tools.db_tools import get_high_rainfall_events, run_all_basins_inference_tool
from src.crew.tools.data_tools import sync_rain_data_tool, update_forecasts_tool, fetch_ims_warnings_tool, sync_flow_data_tool


@CrewBase
class AegisEcoCrew():
    """AegisEco Flood Detection Crew"""
    
    # Define the paths to the YAML configuration files
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
            # החלפנו את כלי השאילתה הפשוט בכלי הלמידת מכונה האמיתי!
            tools=[run_all_basins_inference_tool] 
        )

    @agent
    def communications_officer(self) -> Agent:
        return Agent(
            config=self.agents_config['communications_officer'],
            tools=[]
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
    def alert_task(self) -> Task:
        return Task(
            config=self.tasks_config['alert_task'],
            agent=self.communications_officer()
        )
    
    @task
    def monitor_warnings_task(self) -> Task:
        return Task(
            config=self.tasks_config['monitor_warnings_task'],
            agent=self.warning_monitor()
        )
    
    @crew
    def crew(self) -> Crew:
        """Creates the AegisEco crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True
        )