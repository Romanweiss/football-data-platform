"""Offline notification policy/transport/scheduling tests; no external delivery."""
import contextlib
from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import Mock, patch, MagicMock

from src.alerts.policy import identity, observations, notification, classify
from src.alerts.transport import deliver, select_provider, InvalidProviderConfiguration, TransientDeliveryError, PermanentDeliveryError, LOG_SINK, DELIVERY_BUDGET
from src.alerts.store import after_persistence, enabled, dispatch
from src.alerts.operations import operation_observation, observe_operation
from src.dq.model import Run, Rule
from src.orchestration.monitoring import registered_contexts, scheduled_dq
from src.statsbomb.discovery import catalog_entries, change_status, discover

C = {'competition_id':77,'season_id':88}
RULE = Rule('test.grain','structural','silver','events','Synthetic grain')


class AlertPolicyTests(unittest.TestCase):
    def test_identity_stable_without_execution_message_and_separate_context_build_scope(self):
        args = ('DATA_QUALITY_FAILURE',C,'full','silver','events','test.grain','a'*64)
        key,_=identity(*args)
        self.assertEqual(key,identity(*args)[0])
        for changed in (('DATA_QUALITY_FAILURE',{**C,'season_id':99},*args[2:]),
                        (*args[:-1],'b'*64), (*args[:2],'api',*args[3:])):
            self.assertNotEqual(key,identity(*changed)[0])
        with self.assertRaises(ValueError):
            identity(*args[:5],'postgres://secret@host',args[-1])

    def test_classification_remains_stable_on_fail_and_pass_without_message(self):
        for category,layer,expected in [('structural','silver','DATA_QUALITY_FAILURE'),
                                        ('operational','api','SERVING_FAILURE'),
                                        ('operational','bronze','SOURCE_ACCESS_FAILURE'),
                                        ('operational','operational','PIPELINE_FAILURE')]:
            self.assertEqual(classify(dict(category=category,layer=layer)),expected)

    def test_status_and_severity_are_preserved_not_invented(self):
        run=Run(C,'full')
        run.record(RULE,passed=False)
        run.record(Rule('test.warn','operational','api','matches','Warning','WARNING'),passed=False)
        run.record(Rule('test.skip','regression','api','analysis','Inapplicable'),skip=True,reason='not applicable')
        run.record(Rule('test.info','operational','serving','events','Informational','INFO'))
        rows=list(observations(run.report()))
        eligible=[r for r in rows if r['status']=='FAIL' and r['severity']=='ERROR']
        self.assertEqual(len(eligible),1)
        self.assertEqual({r['status'] for r in rows},{'FAIL','WARN','SKIP','PASS'})

    def test_notification_is_fixed_safe_and_contains_actionable_references(self):
        _,record=identity('DATA_QUALITY_FAILURE',C,'full','silver','events','test.grain')
        message=notification(dict(record,alert_id='fixture',created_at=datetime.now(timezone.utc),
                                  message='password=synthetic-secret postgres://private'),
                             {'dag_id':'platform_dq_validation','run_id':'manual__fixture','task_id':'validate'})
        rendered=json.dumps(message)
        self.assertNotIn('synthetic-secret',rendered)
        self.assertNotIn('postgres://',rendered)
        self.assertEqual(message['environment'],'local')
        self.assertIn('var-rule_id=test.grain',message['grafana'])
        self.assertEqual(message['airflow']['task_id'],'validate')
        self.assertEqual(message['status'],'OPEN')

    def test_transport_retries_only_transient_three_times_and_discards_raw_error(self):
        transport=Mock()
        transport.send.side_effect=[TransientDeliveryError('secret'),TransientDeliveryError('secret'),None]
        sleep=Mock()
        self.assertEqual(deliver(transport,{},sleep=sleep),('SENT',3,'delivered'))
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[1,2])
        transport.send.side_effect=TransientDeliveryError('private')
        self.assertEqual(deliver(transport,{},sleep=Mock()),('FAILED',3,'transient exhausted'))
        transport.send.side_effect=PermanentDeliveryError('token=private')
        sleep=Mock()
        self.assertEqual(deliver(transport,{},sleep=sleep),('FAILED',1,'provider rejected'))
        sleep.assert_not_called()

    def test_local_transport_stdout_json_is_not_polluted_and_invalid_provider_safe(self):
        output,errors=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(errors):
            select_provider('log').send({'status':'OPEN'})
        self.assertEqual(output.getvalue(),'')
        self.assertIn('Platform notification:',errors.getvalue())
        with self.assertRaises(InvalidProviderConfiguration):
            select_provider('https://user:secret@provider')
        messages=[]
        token=LOG_SINK.set(messages.append)
        try:
            select_provider().send({'status':'OPEN'})
        finally:
            LOG_SINK.reset(token)
        self.assertEqual(messages,[{'status':'OPEN'}])

    def test_bridge_dispatch_budget_bounds_claims_across_observers(self):
        c=MagicMock();cur=c.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[]
        token=DELIVERY_BUDGET.set(3)
        try:
            self.assertEqual(dispatch(c),{'sent':0,'failed':0})
            self.assertEqual(cur.execute.call_args.args[1][-1],3)
            DELIVERY_BUDGET.set(0)
            self.assertEqual(dispatch(c),{'sent':0,'failed':0})
            self.assertEqual(cur.execute.call_args.args[1][-1],0)
        finally:
            DELIVERY_BUDGET.reset(token)

    def test_default_off_failure_never_undoes_dq_and_intentional_tests_skip(self):
        with patch.dict('os.environ',{},clear=True):
            self.assertFalse(enabled())
            self.assertEqual(after_persistence('fixture'),{'enabled':False})
        with patch.dict('os.environ',{'PLATFORM_ALERTS_ENABLED':'true'}), \
             patch('src.common.postgres.create_postgres_connection',side_effect=RuntimeError('password=private')), \
             contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertFalse(after_persistence('fixture')['available'])
            self.assertNotIn('private',output.getvalue())
            self.assertEqual(observe_operation({'step':'source','context':C,'test_mode':True},passed=False),{'enabled':False})

    def test_source_failure_after_exhaustion_is_separate_and_recovery_identity_matches(self):
        failed=operation_observation({'step':'source','context':C},passed=False,source_access=True)
        passed=operation_observation({'step':'source','context':C},passed=True,source_access=True)
        self.assertEqual(failed['dedup_key'],passed['dedup_key'])
        self.assertEqual(failed['alert_class'],'SOURCE_ACCESS_FAILURE')
        self.assertEqual(passed['status'],'PASS')

    def test_persisted_dq_takes_precedence_over_duplicate_operational_failure(self):
        with patch.dict('os.environ',{'PLATFORM_ALERTS_ENABLED':'true'}), \
             patch('src.common.postgres.create_postgres_connection',return_value=MagicMock()), \
             patch('src.alerts.operations.apply',return_value='NO_ALERT') as apply, \
             patch('src.alerts.operations.dispatch',return_value={'sent':0,'failed':0}):
            observe_operation({'step':'scheduled_dq','context':C},passed=False,dq_reported=True)
            self.assertEqual([call.args[1]['status'] for call in apply.call_args_list],['PASS','PASS'])
            apply.reset_mock()
            observe_operation({'step':'source','context':C},passed=False,source_access=True)
            self.assertEqual(apply.call_count,1)
            self.assertEqual(apply.call_args.args[1]['status'],'FAIL')
            self.assertEqual(apply.call_args.args[1]['alert_class'],'SOURCE_ACCESS_FAILURE')

    def test_discovery_cli_alerts_only_terminal_failures_and_dryrun_never_alerts(self):
        from scripts.discover_statsbomb_source import main
        from src.common.http import DownloadError
        with patch('scripts.discover_statsbomb_source.create_postgres_connection',return_value=MagicMock()), \
             patch('scripts.discover_statsbomb_source.discover',side_effect=DownloadError('secret')), \
             patch('src.alerts.operations.observe_operation') as observer, \
             contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main(['--dry-run']),1)
            observer.assert_not_called()
            self.assertEqual(main([]),1)
            self.assertEqual(observer.call_count,1)
            self.assertTrue(observer.call_args.kwargs['source_access'])
            self.assertNotIn('secret',output.getvalue())


class SchedulingTests(unittest.TestCase):
    def test_registered_contexts_are_dynamic_and_exclusions_are_explicit_validated(self):
        c=MagicMock()
        cur=c.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[(11,12),(13,14)]
        self.assertEqual(registered_contexts(c,exclusions='11/12'),[{'competition_id':13,'season_id':14}])
        self.assertIn('metadata.clickhouse_loads',cur.execute.call_args.args[0])
        self.assertIn('metadata.dq_executions',cur.execute.call_args.args[0])
        with self.assertRaises(ValueError):
            registered_contexts(c,exclusions='password=private')

    def test_periodic_validation_uses_only_existing_read_only_suites_and_no_source(self):
        lease=MagicMock()
        cur=lease.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=(True,)
        def report(ctx,**kw):
            run=Run(ctx,kw['suite']);run.record(RULE)
            return {**run.report(),'persisted':True}
        with patch('src.common.postgres.create_postgres_connection',return_value=lease), \
             patch('src.dq.cli.execute',side_effect=report) as execute:
            result=scheduled_dq(C)
        self.assertEqual([c.kwargs['suite'] for c in execute.call_args_list],['references','gold','api'])
        self.assertEqual(result['dq_status'],'PASS')
        self.assertTrue(result['dq_persisted'])
        self.assertEqual(len(result['dq_execution_ids']),3)

    def test_busy_context_does_not_fake_dq_history(self):
        lease=MagicMock();lease.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value=(False,)
        with patch('src.common.postgres.create_postgres_connection',return_value=lease),patch('src.dq.cli.execute') as execute:
            self.assertEqual(scheduled_dq(C)['status'],'BUSY')
        execute.assert_not_called()

    def test_source_catalog_and_status_detection_are_pure_not_ingestion(self):
        raw=json.dumps([C]).encode()
        entries=catalog_entries(raw)
        self.assertEqual(set(entries),{(77,88)})
        self.assertEqual(change_status('a','b',None,first_snapshot=True),'BASELINE')
        self.assertEqual(change_status('a','b',None,first_snapshot=False),'NEW')
        self.assertEqual(change_status('a','b',('a','b')),'UNCHANGED')
        self.assertEqual(change_status('c','b',('a','b')),'CHANGED')
        self.assertEqual(change_status('a','b',None,'c',first_snapshot=True),'CHANGED')
        with self.assertRaises(ValueError):
            catalog_entries(json.dumps([C,C]).encode())

    def test_source_discovery_dry_run_writes_nothing_and_does_not_scan_children(self):
        c=MagicMock();cur=c.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[]
        cur.fetchone.side_effect=[(False,),('a'*64,)]
        match=[{'match_id':123,'competition':{'competition_id':77},'season':{'season_id':88}}]
        downloader=Mock(side_effect=[json.dumps([C]).encode(),json.dumps(match).encode()])
        with patch('src.statsbomb.discovery.registered_contexts',return_value=[C]), \
             patch('src.statsbomb.discovery.matches_context'),patch('src.alerts.operations.observe_operation') as notify:
            result=discover(c,dry_run=True,downloader=downloader)
        self.assertTrue(result['dry_run']);self.assertFalse(result['auto_trigger'])
        self.assertEqual(downloader.call_count,2)
        self.assertTrue(all('/events/' not in call.args[0] and '/lineups/' not in call.args[0] for call in downloader.call_args_list))
        self.assertFalse(any('INSERT' in call.args[0] for call in cur.execute.call_args_list))
        notify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
