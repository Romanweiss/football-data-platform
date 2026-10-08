"""Weekly public-source snapshot check, never auto-ingests a context."""
from datetime import datetime, timedelta, timezone
from airflow.sdk import DAG, get_current_context, task
from src.orchestration.runtime import invoke

with DAG(dag_id='statsbomb_source_discovery',schedule='0 4 * * 0',
         start_date=datetime(2026,10,9,tzinfo=timezone.utc),catchup=False,
         is_paused_upon_creation=True,max_active_runs=1,max_active_tasks=1,
         default_args={'retries':0,'execution_timeout':timedelta(minutes=10)},
         tags=['statsbomb','discovery','weekly'],
         doc_md='Sunday 04:00 UTC (07:00 Moscow). Catalog GET plus matches GET for registered contexts; recommends review only. No event/lineup scan, ingestion, ETL trigger or publication.') as dag:
    @task
    def discover():
        c=get_current_context();ti=c['ti']
        return invoke({'step':'source_discovery',
                       'airflow':{'dag_id':ti.dag_id,'run_id':c['run_id'],'task_id':ti.task_id}})

    discover()
