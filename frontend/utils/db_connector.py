import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import time

# Cache the connection engine so it's strictly initialized once per server session
@st.cache_resource
def get_engine():
    db_url = st.secrets["DATABASE_URL"].replace("postgres://", "postgresql://")
    return create_engine(db_url, pool_pre_ping=True, pool_recycle=300)

# Cache the data explicitly for 60 seconds (ttl=60). 
# show_spinner=False prevents UI flickering during background loads.
@st.cache_data(ttl=60, show_spinner=False)
def run_query(query: str, retries: int = 3) -> pd.DataFrame:
    if 'db_offline_since' not in st.session_state:
        st.session_state.db_offline_since = None
    if 'last_successful_update' not in st.session_state:
        st.session_state.last_successful_update = time.strftime('%H:%M')

    engine = get_engine()
    attempt = 0
    
    while attempt < retries:
        try:
            df = pd.read_sql(query, engine)
            
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