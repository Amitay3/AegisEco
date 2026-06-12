import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import time

db_url = st.secrets["DATABASE_URL"].replace("postgres://", "postgresql://")
engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=300)

def run_query(query: str, retries: int = 3) -> pd.DataFrame:
    if 'db_offline_since' not in st.session_state:
        st.session_state.db_offline_since = None
    if 'last_successful_update' not in st.session_state:
        st.session_state.last_successful_update = time.strftime('%H:%M')

    attempt = 0
    while attempt < retries:
        try:
            df = pd.read_sql(query, engine)
            
            # Connection is active, update timestamps
            st.session_state.last_successful_update = time.strftime('%H:%M')
            st.session_state.db_offline_since = None
                
            return df
            
        except Exception as e:
            attempt += 1
            engine.dispose()
            
            if attempt < retries:
                time.sleep(2)
                continue
            else:
                if st.session_state.db_offline_since is None:
                    st.session_state.db_offline_since = time.time()
                    
                print(f"DB Error: {e}")
                return pd.DataFrame()