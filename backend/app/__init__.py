"""AgentTestLab backend."""
"""加载项目独立依赖，避免修改用户现有 Python 安装。"""
import os,sys
from pathlib import Path
dependency_root=Path(__file__).resolve().parents[2]/'runtime-packages'
if dependency_root.is_dir():sys.path.insert(0,str(dependency_root))
os.environ.setdefault('DEEPEVAL_TELEMETRY_OPT_OUT','YES')
os.environ.setdefault('RAGAS_DO_NOT_TRACK','true')
