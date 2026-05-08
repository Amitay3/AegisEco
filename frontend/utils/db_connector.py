import streamlit as st
import psycopg2
import pandas as pd

@st.cache_resource
def init_connection():
    """
    Initializes and caches the database connection.
    Sets autocommit to True to prevent transaction block errors.
    """
    conn = psycopg2.connect(st.secrets["DATABASE_URL"])
    conn.autocommit = True
    return conn

@st.cache_data(ttl=700) 
def run_query(query: str):
    """
    Runs a SELECT SQL query and returns the results as a Pandas DataFrame.
    The results are cached for 10 minutes (700 seconds) to avoid overloading the DB.
    """
    with init_connection().cursor() as cur:
        cur.execute(query)
        # Fetch the column names from the cursor description
        colnames = [desc[0] for desc in cur.description]
        # Fetch all rows
        data = cur.fetchall()
        # Convert to a DataFrame for easy display in Streamlit
        return pd.DataFrame(data, columns=colnames)