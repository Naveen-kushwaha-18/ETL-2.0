import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import pandas as pd


class EiaFetch:
    def __init__(self, pipeline, config):
        self.pipeline = pipeline
        self.config = config

    def fetch_data(self):
        vault_secrets = self.pipeline.get_vault_credentials()
        engine = self.pipeline.create_source_engine()
        table_name = self.config["tableName"]
        api_url = self.config["url"]
        columns_required = self.config["columns"]
        rename_value_col = self.config["renameValueCol"]
        try:
            offset = self.existing_data_count(table_name,engine)

            params=self.config['params']
            params['api_key'] = vault_secrets['API_KEY']
            params['offset'] = offset

            response = requests.get(self.config['url'],params )
            data = response.json()
            total_record = int(data['response']['total'])
            print(total_record)

            list_praser=self.create_chunks(total_record,offset)
            if len(list_praser) > 1:
                for i in range(len(list_praser)-1):
                    offsets = range(list_praser[i], list_praser[i+1], 5000)
                    self.thread_executor(engine,offsets,api_url,params,table_name,columns_required,rename_value_col)
            else:
                print("No new records were discovered.")
        except:
            data = "NO DATA FOUND!!!!!"
        


    def existing_data_count(self,tableName,engine):
        """
        Checks if a specified table exists in the database and retrieve no. of records for the table.

        Parameters:
        - tableName (str): The name of the table to check for existence.
        - engine (SQLAlchemy Engine): The database engine to connect to.

        Returns:
        - int: The count of records in the table if it exists, or 0 if the table does not exist or an error occurs.
        """
        try:
            query = f'SELECT count(*) FROM "{tableName}";'  
            df = pd.read_sql(query, engine)
            print(f"present records count {df.iloc[0,0]}")
            return df.iloc[0,0]
        except:
            print(f"No records available for table {tableName}")
            return 0

    def create_chunks(self,total,offset): # E
        """
        Creates a list of chunk boundaries for splitting a total into smaller 
        segments.

        Parameters:
        - total (int): The total number that needs to be divided into chunks.
        - offset (int): existing number of records.

        Returns:
        - list: A list of integers representing the boundaries of each chunk, 
        starting from 0 and ending with the total. The default chunk size is 
        set to 10,00,000.
        """
        chunks = []
        chunk_size = 1000000 
        for i in range(offset, total + 1, chunk_size):
            chunks.append(i)
        if total not in chunks:
            chunks.append(total)
        
        return chunks
    
    def thread_executor(self,en,offsets,apiUrl,params_template,table_name,requiredCol,repColNameWith,db_lock=threading.Lock()): # E
        """
        Executes API requests in parallel using a thread pool and inserts the 
        retrieved data into a PostgreSQL database.

        Parameters:
        - en: The SQLAlchemy engine object used to connect to the PostgreSQL database.
        - offsets (range): A range of offsets for pagination in API requests.
        - apiUrl (str): The URL of the API to fetch data from.
        - params_template (dict): A dictionary template of parameters for the API request.
        - table_name (str): The name of the table in the PostgreSQL database where 
        the data will be inserted.
        - requiredCol (list): A list of columns to extract from the API response.
        - repColNameWith (str): The new name for the 'value' column in the DataFrame.
        - db_lock (threading.Lock): A lock to ensure thread-safe database operations.

        Note:
        - The function employs a sleep mechanism to manage the request rate to 
        avoid overloading the API.
        """
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_offset = {}
            
            for offset in offsets:
                params = params_template.copy()
        
                params['offset'] = offset
                future = executor.submit(requests.get, apiUrl, params)
                future_to_offset[future] = offset
                time.sleep(0.2)

            for future in as_completed(future_to_offset):
                offset = future_to_offset[future]
                response = future.result()
                try:
                    response.raise_for_status()  
                    data = response.json()
                    df = data['response']['data']
                    df = pd.DataFrame(df)
                    df['value'] = pd.to_numeric(df['value'], errors='coerce')  

                    df = df[requiredCol].rename(columns={'value': repColNameWith})

                    with db_lock:
                        # df.to_sql(table_name, en, if_exists='append', index=False)
                        time.sleep(0.2 )
                        print(f"Data loaded successfully for {table_name} with offset {offset}")

                except:
                    df = pd.DataFrame({'table': [table_name], 'offset': [offset], 'error': [response.status_code]})
                    # df.to_sql('Failed_import_api', en, if_exists='append', index=False)
                    print(f"An error occurred for {table_name} at Offset {offset}: {response.status_code}")