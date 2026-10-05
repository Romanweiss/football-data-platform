"""Manual control plane for the existing StatsBomb CLI pipeline. No parse-time IO."""
from datetime import timedelta

from airflow.sdk import DAG, Param, TaskGroup, get_current_context, task
from src.orchestration.commands import GOLD, SILVER, context
from src.orchestration.runtime import invoke


with DAG(
    dag_id="statsbomb_context_pipeline", schedule=None, catchup=False,
    max_active_runs=1, max_active_tasks=2,
    params={"competition_id": Param(type="integer", minimum=1, maximum=2**32 - 1),
            "season_id": Param(type="integer", minimum=1, maximum=2**32 - 1)},
    default_args={"retries": 0, "execution_timeout": timedelta(minutes=65)},
    tags=["statsbomb", "manual", "context"],
    doc_md="""### StatsBomb context pipeline
    Manually orchestrates the existing Bronze -> Silver -> Gold -> ClickHouse
    jobs, with explicit preflight, integrity/DQ and serving/API validation gates.

    **Required params:** `competition_id` and `season_id`, both positive UInt32
    integers. No default context and no automatic schedule.

    **Authoritative state:** immutable S3 artifacts, the platform PostgreSQL
    catalog and ClickHouse serving builds. XCom carries small IDs/statuses only;
    the Airflow run ID never enters deterministic build identity. Completed
    artifacts/builds are verified and reused on replay.

    **Local execution:** one active DAG run across all contexts; `spark_local`
    allows one Spark-heavy task at a time. Stop independent manual writers before
    triggering. Automatic Airflow retries are disabled; project HTTP transport
    already applies bounded retries. Diagnose a failure, then start a fresh run
    or clear only failed tasks with still-valid upstream pins. Never bypass a
    failed validator or delete platform data to resume.

    **Quality evidence:** validation tasks persist normalized rule results in the
    platform PostgreSQL DQ history. Logs/XCom link the DQ execution and failed
    rule IDs; Airflow is not the authoritative quality store.
    """,
) as dag:
    @task
    def validate_context():
        c = context(get_current_context()["params"])
        print(f"Context competition_id={c['competition_id']} season_id={c['season_id']}")
        return c

    @task
    def run_step(step, ctx, snapshot=None, layer=None, dataset=None, upstream=None, build=None):
        task_context = get_current_context()
        ti = task_context['ti']
        return invoke({"step": step, "context": ctx, "snapshot": snapshot,
                       "layer": layer, "dataset": dataset, "upstream": upstream, "build": build,
                       'airflow': {'dag_id':ti.dag_id, 'run_id':task_context['run_id'], 'task_id':ti.task_id}})

    ctx = validate_context()
    with TaskGroup("source"):
        source = run_step.override(task_id="preflight")("source", ctx)
    with TaskGroup("bronze"):
        parent = run_step.override(task_id="parent_ingest")("parent", ctx, source)
        children = run_step.override(task_id="children_ingest")("children", ctx, source)
        parent >> children
        snapshot = run_step.override(task_id="freeze_snapshot")("freeze", ctx, source)
        children >> snapshot
        bronze_valid = run_step.override(task_id="validate")("bronze_validate", ctx, snapshot)

    silver, silver_valid = {}, {}
    with TaskGroup("silver"):
        for dataset in SILVER:
            with TaskGroup(dataset):
                upstream = {"teams": silver_valid["teams"]} if dataset == "matches" else {}
                checked = run_step.override(task_id="check", pool="spark_local")(
                    "build_check", ctx, snapshot, "silver", dataset, upstream)
                bronze_valid >> checked
                published = run_step.override(task_id="publish", pool="spark_local")(
                    "publish", ctx, snapshot, "silver", dataset, upstream, checked)
                silver[dataset] = published
                silver_valid[dataset] = run_step.override(task_id="validate")(
                    "artifact_validate", ctx, snapshot, "silver", dataset, upstream, published)

    gold, gold_valid = {}, {}
    with TaskGroup("gold"):
        for dataset, required in GOLD.items():
            with TaskGroup(dataset):
                upstream = {name: silver_valid[name] for name in required}
                checked = run_step.override(task_id="check", pool="spark_local")(
                    "build_check", ctx, snapshot, "gold", dataset, upstream)
                published = run_step.override(task_id="publish", pool="spark_local")(
                    "publish", ctx, snapshot, "gold", dataset, upstream, checked)
                gold[dataset] = published
                gold_valid[dataset] = run_step.override(task_id="validate")(
                    "artifact_validate", ctx, snapshot, "gold", dataset, upstream, published)

    previous = None
    with TaskGroup("clickhouse"):
        for layer, builds in (("silver", silver_valid), ("gold", gold_valid)):
            for dataset, build in builds.items():
                with TaskGroup(layer + "_" + dataset):
                    upstream = {name: silver_valid[name] for name in GOLD[dataset]} if layer == "gold" else {}
                    preflight = run_step.override(task_id="preflight")(
                        "load_preflight", ctx, snapshot, layer, dataset, upstream, build)
                    # All artifacts pass validation before the first serving write.
                    for gate in [*silver_valid.values(), *gold_valid.values()]:
                        gate >> preflight
                    if previous is not None:
                        previous >> preflight
                    previous = run_step.override(task_id="load")(
                        "load", ctx, snapshot, layer, dataset, upstream, preflight)
    with TaskGroup("validation"):
        model = run_step.override(task_id="serving_model")("serving_model", ctx)
        gold_model = run_step.override(task_id="gold_model")("serving_gold", ctx)
        results = run_step.override(task_id="match_results")("serving_results", ctx)
        previous >> [model, gold_model, results]
        api = run_step.override(task_id="application_api")("application", ctx)
        [model, gold_model, results] >> api
