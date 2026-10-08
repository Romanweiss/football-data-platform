"""Transactional incident/delivery tests; synthetic contexts always roll back."""
import contextlib
from datetime import datetime, timezone, timedelta
import io
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from src.common.postgres import create_postgres_connection
from src.dq.model import Run,Rule
from src.dq.store import persist
from src.alerts.store import evaluate,dispatch
from src.alerts.operations import operation_observation
from src.alerts.store import apply
from src.alerts.transport import DELIVERY_BUDGET, LOG_SINK
from src.orchestration.monitoring import registered_contexts

C={'competition_id':4294967291,'season_id':4294967291}
RULE=Rule('test.alert.grain','structural','silver','events','Synthetic rolled-back grain')


class AlertPostgresTests(unittest.TestCase):
    def report(self,c,passed=False,ctx=C,offset=0):
        run=Run(ctx,'full');run.record(RULE,passed=passed,build_id='a'*64)
        report=run.report()
        report['finished_at']=(datetime.now(timezone.utc)+timedelta(seconds=offset)).isoformat()
        persist(c,report)
        return report['execution_id']

    def test_open_dedup_delivery_context_separation_resolution_and_late_fail(self):
        with create_postgres_connection() as c:
            with c.transaction(force_rollback=True):
                first=self.report(c)
                self.assertEqual(evaluate(c,first),{'OPENED':1})
                self.assertEqual(evaluate(c,first),{'IGNORED':1})
                with c.cursor() as q:
                    q.execute('SELECT alert_id FROM metadata.alerts WHERE competition_id=%s',(C['competition_id'],))
                    alert=q.fetchone()[0]
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(dispatch(c,alert_id=alert),{'sent':1,'failed':0})
                    self.assertEqual(dispatch(c,alert_id=alert),{'sent':0,'failed':0})
                repeated=self.report(c,offset=1)
                self.assertEqual(evaluate(c,repeated),{'DEDUPLICATED':1})
                other=self.report(c,ctx={**C,'season_id':4294967290})
                self.assertEqual(evaluate(c,other),{'OPENED':1})
                recovered=self.report(c,passed=True,offset=3)
                self.assertEqual(evaluate(c,recovered),{'RESOLVED':1})
                late=self.report(c,offset=2)
                self.assertEqual(evaluate(c,late),{'IGNORED':1})
                with c.cursor() as q:
                    q.execute('SELECT status FROM metadata.alerts WHERE alert_id=%s',(alert,))
                    self.assertEqual(q.fetchone()[0],'RESOLVED')
                    q.execute('SELECT delivery_status FROM metadata.alert_delivery_events WHERE alert_id=%s ORDER BY id',(alert,))
                    self.assertEqual([r[0] for r in q.fetchall()],['STARTED','SENT'])
            with c.cursor() as q:
                q.execute('SELECT count(*) FROM metadata.alerts WHERE competition_id=%s',(C['competition_id'],))
                self.assertEqual(q.fetchone()[0],0)

    def test_warn_skip_info_dryrun_no_delivery_and_real_bundesliga_skips(self):
        with create_postgres_connection() as c:
            with c.transaction(force_rollback=True):
                run=Run(C,'full')
                run.record(Rule('test.alert.warn','operational','api','matches','Warning','WARNING'),passed=False)
                run.record(Rule('test.alert.skip','regression','api','analysis','Intentional'),skip=True,reason='not applicable')
                run.record(Rule('test.alert.info','operational','api','matches','Info','INFO'))
                persist(c,run.report())
                self.assertEqual(evaluate(c,run.execution_id),{'NO_ALERT':3})
                fail=self.report(c)
                self.assertEqual(evaluate(c,fail,dry_run=True),{'dry_run':True,'eligible_failures':1})
                with patch('src.alerts.store.select_provider') as provider:
                    self.assertEqual(dispatch(c,dry_run=True),{'dry_run':True,'deliveries':0})
                provider.assert_not_called()
                with c.cursor() as q:
                    q.execute("SELECT execution_id FROM metadata.dq_latest_executions WHERE competition_id=9 AND season_id=281 AND suite='full'")
                    id_=q.fetchone()[0]
                    q.execute("SELECT count(*) FROM metadata.dq_results WHERE execution_id=%s AND status='SKIP'",(id_,))
                    self.assertEqual(q.fetchone()[0],2)
                self.assertEqual(evaluate(c,id_).get('OPENED',0),0)

    def test_failed_provider_and_uncertain_claim_are_not_resent(self):
        with create_postgres_connection() as c:
            with c.transaction(force_rollback=True):
                fail=self.report(c);evaluate(c,fail)
                with c.cursor() as q:
                    q.execute('SELECT alert_id FROM metadata.alerts WHERE competition_id=%s',(C['competition_id'],))
                    id_=q.fetchone()[0]
                self.assertEqual(dispatch(c,alert_id=id_,provider='invalid-secret-config'),{'sent':0,'failed':1})
                self.assertEqual(dispatch(c,alert_id=id_),{'sent':0,'failed':0})
                with c.cursor() as q:
                    q.execute('SELECT delivery_status,provider,reason FROM metadata.alert_delivery_events WHERE alert_id=%s ORDER BY id',(id_,))
                    events=q.fetchall()
                    self.assertEqual(events[-1],('FAILED','invalid','invalid configuration'))
                    self.assertNotIn('secret',str(events))

    def test_registered_contexts_remain_discoverable_and_fake_context_is_not_scheduled(self):
        with create_postgres_connection() as c:
            contexts=registered_contexts(c,exclusions='')
            self.assertTrue({(43,106),(9,281)} <= {tuple(ctx.values()) for ctx in contexts})
            self.assertNotIn(C,contexts)

    def test_shared_bridge_budget_leaves_excess_incidents_unclaimed(self):
        messages=[]
        sink_token=LOG_SINK.set(messages.append)
        budget_token=DELIVERY_BUDGET.set(1)
        try:
            with create_postgres_connection() as c:
                with c.transaction(force_rollback=True):
                    evaluate(c,self.report(c))
                    evaluate(c,self.report(c,ctx={**C,'season_id':4294967290}))
                    with c.cursor() as q:
                        q.execute('SELECT alert_id FROM metadata.alerts WHERE competition_id=%s ORDER BY season_id',
                                  (C['competition_id'],))
                        first,second=[r[0] for r in q.fetchall()]
                    self.assertEqual(dispatch(c,alert_id=first),{'sent':1,'failed':0})
                    self.assertEqual(DELIVERY_BUDGET.get(),0)
                    self.assertEqual(dispatch(c,alert_id=second),{'sent':0,'failed':0})
                    self.assertEqual(len(messages),1)
                    with c.cursor() as q:
                        q.execute('SELECT count(*) FROM metadata.alert_delivery_events WHERE alert_id=%s',(second,))
                        self.assertEqual(q.fetchone()[0],0)
        finally:
            LOG_SINK.reset(sink_token)
            DELIVERY_BUDGET.reset(budget_token)

    def test_uncertain_delivery_claim_is_not_resent_and_operational_reference_is_retained(self):
        with create_postgres_connection() as c:
            with c.transaction(force_rollback=True):
                request={'step':'source_discovery','context':C,'airflow':{
                    'dag_id':'statsbomb_source_discovery','run_id':'manual__fixture','task_id':'discover'}}
                self.assertEqual(apply(c,operation_observation(request,passed=False,source_access=True)),'OPENED')
                with c.cursor() as q:
                    q.execute('SELECT alert_id,airflow_task_id FROM metadata.alerts WHERE competition_id=%s',
                              (C['competition_id'],))
                    id_,task=q.fetchone()
                    self.assertEqual(task,'discover')
                    q.execute("INSERT INTO metadata.alert_delivery_events(alert_id,attempt_id,delivery_status,provider,attempts,reason) "
                              "VALUES(%s,%s,'STARTED','log',0,'delivery started')",(id_,uuid4()))
                with patch('src.alerts.store.select_provider') as provider:
                    self.assertEqual(dispatch(c,alert_id=id_),{'sent':0,'failed':0})
                provider.assert_not_called()
                self.assertEqual(apply(c,operation_observation(request,passed=True,source_access=True)),'RESOLVED')


if __name__ == '__main__':
    unittest.main()
