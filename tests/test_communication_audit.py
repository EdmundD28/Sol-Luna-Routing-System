from __future__ import annotations
import importlib.util, json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCRIPT=ROOT/'.agents/skills/sol-luna/scripts/communication_audit.py'
spec=importlib.util.spec_from_file_location('communication_audit',SCRIPT); MOD=importlib.util.module_from_spec(spec); spec.loader.exec_module(MOD)
D='sha256:'+'a'*64
def arm(protocol='natural', messages=None, source='unavailable'):
    if messages is None:
        messages=[{'message_id':'i','direction':'SOL_TO_LUNA_INITIAL','content':'请处理 CJK任务 ABC-12','measured_tokens':None,'token_source':source}, {'message_id':'r','direction':'LUNA_TO_SOL_RECEIPT','content':'完成 CJK任务 ABC-12','measured_tokens':None,'token_source':source}]
    if protocol=='compact': messages=[{'message_id':'m','direction':'SOL_TO_LUNA_MANIFEST','content':'manifest','measured_tokens':None,'token_source':source}]+messages
    return {'schema_version':1,'arm_id':protocol+'-1','protocol':protocol,'task_digest':D,'acceptance_digest':D,'candidate_digest':D,'controller_model':'sol','controller_effort':'medium','luna_model':'luna','luna_effort':'medium','messages':messages,'controller_noncached_input_tokens':None,'controller_token_source':'unavailable','controller_full_reread':False,'controller_reimplemented':False,'elapsed_seconds':2.0,'quality':{'passed':3,'total':3,'defects':0}}
class CommunicationAuditTests(unittest.TestCase):
    def test_unicode_bytes_and_union_shingles(self):
        self.assertEqual(MOD.lexical_units('中文 ABC-12 中文'),['中','文','abc','12','中','文'])
        a=arm(messages=[{'message_id':'a','direction':'SOL_TO_LUNA_INITIAL','content':'one two three four five','measured_tokens':None,'token_source':'unavailable'},{'message_id':'b','direction':'LUNA_TO_SOL_RECEIPT','content':'one two three four five six','measured_tokens':None,'token_source':'unavailable'}])
        self.assertEqual(MOD.audit(a)['repetition']['per_later_message'][0]['repeated_lexical_units'],5)
    def test_aggregates_manifest_and_measurement_coupling(self):
        x=MOD.audit(arm('compact')); self.assertEqual(x['aggregates']['sol_to_luna_initial_handoff']['messages'],2); self.assertFalse(x['included_plan_conclusion_allowed'])
        bad=arm(); bad['messages'][0]['measured_tokens']=2
        with self.assertRaises(MOD.AuditError): MOD.validate_arm(bad)
    def test_strict_rejections_and_order(self):
        with self.assertRaises(MOD.AuditError): MOD.load_json_strict('{"x":1,"x":2}')
        with self.assertRaises(MOD.AuditError): MOD.load_json_strict('{"x":NaN}')
        bad=arm('compact'); bad['messages'][0],bad['messages'][1]=bad['messages'][1],bad['messages'][0]
        with self.assertRaises(MOD.AuditError): MOD.validate_arm(bad)
        for field in ('task_digest','acceptance_digest','candidate_digest'):
            bad=arm(); bad[field]='a'*64
            with self.assertRaises(MOD.AuditError): MOD.validate_arm(bad)
        bad=arm(); bad['schema_version']=True
        with self.assertRaises(MOD.AuditError): MOD.validate_arm(bad)
    def test_compare_gates_and_missing_provider(self):
        n=arm(); c=arm('compact'); c['messages']=[{'message_id':'m','direction':'SOL_TO_LUNA_MANIFEST','content':'m','measured_tokens':None,'token_source':'unavailable'},{'message_id':'i','direction':'SOL_TO_LUNA_INITIAL','content':'x','measured_tokens':None,'token_source':'unavailable'},{'message_id':'r','direction':'LUNA_TO_SOL_RECEIPT','content':'y','measured_tokens':None,'token_source':'unavailable'}]
        n['messages'][0]['content']='line1\nline2\tfield'; result=MOD.compare(n,c); self.assertFalse(result['provider_gate_passed']); self.assertFalse(result['included_plan_conclusion_allowed']); self.assertFalse(result['reductions']['controller_full_reread_changed']); self.assertFalse(result['reductions']['controller_reimplemented_changed'])
        with self.assertRaises(MOD.AuditError): MOD.compare(c,n)
        c['messages'][1]['content']='x'; c['messages'][2]['content']='y'; c['messages'][0]['content']='manifest'; c['messages'][1]['content']='x'; c['messages'][2]['content']='y'; n['messages'][0]['content']='a very long initial handoff with many distinct words and details'; n['messages'][1]['content']='a very long receipt with many distinct words and details'; n['controller_full_reread']=True
        c['controller_full_reread']=True; gated=MOD.compare(n,c); self.assertFalse(gated['mechanism_gate_passed']); self.assertFalse(gated['provider_gate_passed']); self.assertTrue(gated['mechanism_gate_reasons'])
    def test_cli_clean_deterministic_json(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'a.json'; path.write_text(json.dumps(arm(),ensure_ascii=False),encoding='utf-8')
            p=subprocess.run([sys.executable,'-B',str(SCRIPT),'audit','--input',str(path)],capture_output=True)
            self.assertEqual(p.returncode,0); self.assertEqual(p.stdout,subprocess.run([sys.executable,'-B',str(SCRIPT),'audit','--input',str(path)],capture_output=True).stdout); p=subprocess.run([sys.executable,'-B',str(SCRIPT),'audit','--input',str(Path(d)/'no')],capture_output=True); self.assertNotEqual(p.returncode,0); self.assertEqual(p.stdout,b''); self.assertEqual(p.stderr.count(b'\n'),1)
            p=subprocess.run([sys.executable,'-B',str(SCRIPT),'audit'],capture_output=True); self.assertNotEqual(p.returncode,0); self.assertEqual(p.stdout,b''); self.assertEqual(p.stderr.count(b'\n'),1); self.assertNotIn(b'usage',p.stderr.lower())
if __name__=='__main__': unittest.main()
