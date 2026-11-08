"""项目便携依赖入口，不改动现有虚拟环境。例：python scripts/run_module.py pytest ..."""
import os,runpy,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
deps=root/'runtime-packages'
sys.path.insert(0,str(deps))
sys.path.insert(0,str(root/'backend'))
os.environ['PYTHONPATH']=str(deps)+os.pathsep+str(root/'backend')
os.environ.setdefault('DEEPEVAL_TELEMETRY_OPT_OUT','YES')
os.environ.setdefault('RAGAS_DO_NOT_TRACK','true')
if len(sys.argv)<2:raise SystemExit('Pass a Python module name')
module=sys.argv.pop(1)
if module.endswith('.py'):
    sys.argv[0]=module
    runpy.run_path(module,run_name='__main__')
else:
    runpy.run_module(module,run_name='__main__',alter_sys=True)
