"""Weekly serving/catalog/API DQ, paused until explicitly enabled. No parse IO."""
from datetime import datetime, timedelta, timezone
from airflow.sdk import DAG, get_current_context, task
from src.orchestration.runtime import invoke

with DAG(dag_id='platform_dq_validation',schedule='0 5 * * 0',
         start_date=datetime(2026,10,9,tzinfo=timezone.utc),catchup=False,
         is_paused_upon_creation=True,max_active_runs=1,max_active_tasks=1,
         default_args={'retries':0,'execution_timeout':timedelta(minutes=15)},
         tags=['platform','dq','weekly'],
         doc_md='Weekly Sunday 05:00 UTC (08:00 Moscow). Registered contexts only; existing references/gold/api validators. No rebuild, no S3; alerts separately opt-in.') as dag:
    @task
    def contexts():
        c = get_current_context()
        ti = c['ti']
        return invoke({'step':'registered_contexts',
                       'airflow':{'dag_id':ti.dag_id,'run_id':c['run_id'],'task_id':ti.task_id}})['contexts']

    @task(max_active_tis_per_dag=1)
    def validate_registered(ctx):
        c = get_current_context()
        ti = c['ti']
        return invoke({'step':'scheduled_dq','context':ctx,
                       'airflow':{'dag_id':ti.dag_id,'run_id':c['run_id'],'task_id':ti.task_id}})

    validate_registered.expand(ctx=contexts())
